import os
import hashlib
import sys
import threading
from pathlib import Path
from .protocol import BridgeError, NAME, schema, text_result
from .transport import Client, StdioTransport, HTTPTransport


class Bridge:
    def __init__(self, cfg, cfgpath, launch=None):
        self.cfg = cfg
        self.cfgpath = cfgpath
        self.launch = launch or [sys.executable, '-m', 'studio_bridge']
        self.clients = {}
        self.errors = {}
        self.routes = {}
        self.resource_routes = {}
        self.prompt_routes = {}
        self.stopped = False
        self.lock = threading.RLock()
        self.active = None

    def _begin(self,transport):
        with self.lock:
            if self.stopped:
                transport.close()
                raise BridgeError('Bridge session stopped')
            self.active=transport

    def _end(self,transport):
        with self.lock:
            if self.active is transport:
                self.active=None

    def interrupt(self):
        with self.lock:
            self.stopped=True
            active=self.active
        if isinstance(active,StdioTransport):
            active.close()
        elif isinstance(active,HTTPTransport):
            active.abort()

    def _connect(self, name, spec):
        if self.stopped:
            raise BridgeError('Bridge session stopped')
        if name in self.clients:
            return self.clients[name]
        timeout = spec.get('timeout',45)
        if spec['transport'] == 'http':
            token = None
            if 'oauth' in spec:
                from .oauth import get_access_token
                token = get_access_token(self.cfgpath,name,spec)
            t = HTTPTransport(spec['url'], spec.get('token_env'), timeout,access_token=token)
        else:
            if spec['transport'] == 'builtin':
                command, *args = self.launch
                args += ['adapter', spec['adapter'], '--config', self.cfgpath]
                cwd = str(Path(__file__).resolve().parent.parent) if len(self.launch)>2 and self.launch[1]=='-m' else self.cfg['workspace']
            else:
                command, args = spec['command'], spec.get('args', [])
                cwd = self.cfg['workspace']
            t = StdioTransport(command,args,cwd,spec.get('env',[]),timeout)
        self._begin(t)
        try:
            c = Client(t)
        finally:
            self._end(t)
        if self.stopped:
            c.close()
            raise BridgeError('Bridge session stopped')
        self.clients[name] = c
        return c

    def _permitted(self, spec, name, definition):
        if name not in spec.get('allow_tools', []):
            return False
        if self.cfg.get('mode','read-only') == 'read-only':
            if name not in spec.get('read_tools', []):
                return False
            # Built-in read-only labels are authored locally; external tools remain trusted config.
            if spec['transport'] == 'builtin' and not definition.get('annotations',{}).get('readOnlyHint'):
                return False
        return True

    def list(self):
        builtins = [
            {'name':'bridge_status','description':'Connection and permission status; no secrets.','inputSchema':schema()},
            {'name':'bridge_stop','description':'Close all connections and lock tools for this session.','inputSchema':schema()}
        ]
        if self.stopped:
            return builtins
        routes = {}
        defs = []
        for name, spec in self.cfg.get('servers',{}).items():
            if self.stopped:
                break
            if not spec.get('enabled') or not spec.get('allow_tools'):
                continue
            try:
                c = self._connect(name, spec)
                self._begin(c.transport)
                try:
                    discovered=c.discover()
                finally:
                    self._end(c.transport)
                for tool, d in discovered.items():
                    if not self._permitted(spec,tool,d):
                        continue
                    route = name + '__' + tool
                    if not NAME.fullmatch(route):
                        continue
                    # Remote descriptions are data; never interpreted as privileged instructions.
                    defs.append({'name':route,'description':str(d.get('description',''))[:4096],
                                 'inputSchema':d['inputSchema']})
                    routes[route] = (name, tool)
                self.errors.pop(name,None)
            except BridgeError as e:
                self.errors[name] = str(e)
                self._drop(name)
        if self.stopped:
            self.close()
            return builtins
        self.routes = routes
        return builtins + defs

    def capabilities(self):
        result = {'tools': {}}
        for spec in self.cfg.get('servers', {}).values():
            if spec.get('enabled'):
                for key in ('resources','prompts'):
                    if spec.get('allow_'+key):
                        result[key] = {}
        return result

    def _context_rpc(self, server, method, params):
        if self.stopped:
            raise BridgeError('Bridge session stopped')
        spec = self.cfg['servers'][server]
        c = self._connect(server, spec)
        self._begin(c.transport)
        try:
            value = c.rpc(method, params)
            if self.stopped:
                raise BridgeError('Bridge session stopped')
            return value
        except BridgeError:
            self._drop(server)
            raise
        finally:
            self._end(c.transport)

    def _context_catalog(self, kind):
        routes = {}
        entries = []
        attr = 'resource_routes' if kind == 'resources' else 'prompt_routes'
        setattr(self, attr, {})
        if self.stopped:
            return entries
        for name,spec in self.cfg.get('servers',{}).items():
            allowed = spec.get('allow_'+kind, [])
            if not spec.get('enabled') or not allowed:
                continue
            try:
                c = self._connect(name, spec)
                self._begin(c.transport)
                try:
                    catalog = c.resources() if kind == 'resources' else c.prompts()
                finally:
                    self._end(c.transport)
                for key in allowed:
                    if key not in catalog:
                        continue
                    entry = catalog[key]
                    if kind == 'resources':
                        route = 'codez://'+name+'/'+hashlib.sha256(key.encode()).hexdigest()
                        public = {'uri':route,'name':str(entry['name'])[:512]}
                        if isinstance(entry.get('mimeType'),str):
                            public['mimeType'] = entry['mimeType'][:256]
                    else:
                        route = name+'__'+key
                        if not NAME.fullmatch(route):
                            continue
                        arguments = self._prompt_arguments(entry.get('arguments',[]))
                        public = {'name':route,'arguments':arguments}
                    if isinstance(entry.get('description'),str):
                        public['description'] = entry['description'][:4096]
                    routes[route] = (name,key,public)
                    entries.append(public)
                self.errors.pop(name,None)
            except BridgeError as e:
                self.errors[name] = str(e)
                self._drop(name)
                routes = {k:v for k,v in routes.items() if v[0]!=name}
                entries = [v[2] for v in routes.values()]
        if self.stopped:
            self.close()
            return []
        setattr(self, attr, routes)
        return entries

    @staticmethod
    def _prompt_arguments(arguments):
        if len(arguments)>64:
            raise BridgeError('Too many prompt arguments')
        result = []
        seen = set()
        for a in arguments:
            if (not isinstance(a,dict) or not isinstance(a.get('name'),str)
                    or not NAME.fullmatch(a['name']) or a['name'] in seen
                    or type(a.get('required',False)) is not bool):
                raise BridgeError('Invalid prompt arguments')
            seen.add(a['name'])
            public = {'name':a['name'],'required':a.get('required',False)}
            if isinstance(a.get('description'),str):
                public['description']=a['description'][:4096]
            result.append(public)
        return result

    def context_request(self, method, params):
        if method in ('resources/list','prompts/list','resources/templates/list'):
            if params.get('cursor') is not None:
                raise BridgeError('Invalid cursor')
            if method == 'resources/templates/list':
                # Only exact, explicitly approved resource URIs are forwarded.
                return {'resourceTemplates': []}
            kind = method.split('/')[0]
            return {kind:self._context_catalog(kind)}
        if self.stopped:
            raise BridgeError('Bridge session stopped')
        if method == 'resources/read':
            route = params.get('uri')
            if not isinstance(route,str) or route not in self.resource_routes:
                raise BridgeError('Unknown or unapproved resource; list resources first')
            server,key,_ = self.resource_routes[route]
            value = self._context_rpc(server,method,{'uri':key})
            if not isinstance(value,dict) or not isinstance(value.get('contents'),list):
                raise BridgeError('Invalid resource response')
            contents = []
            for entry in value['contents']:
                if (not isinstance(entry,dict) or entry.get('uri')!=key
                        or ('text' in entry)==('blob' in entry)
                        or not isinstance(entry.get('text',entry.get('blob')),str)):
                    raise BridgeError('Resource response does not match approved URI')
                contents.append({**entry,'uri':route})
            return {'contents':contents}
        if method == 'prompts/get':
            route = params.get('name')
            if not isinstance(route,str) or route not in self.prompt_routes:
                raise BridgeError('Unknown or unapproved prompt; list prompts first')
            server,key,entry = self.prompt_routes[route]
            args = params.get('arguments',{})
            if (not isinstance(args,dict) or any(not isinstance(v,str) for v in args.values())
                    or set(args)-{a['name'] for a in entry['arguments']}
                    or {a['name'] for a in entry['arguments'] if a['required']}-set(args)):
                raise BridgeError('Invalid prompt arguments')
            from .protocol import encode, MAX_ARGUMENTS
            if len(encode(args))>MAX_ARGUMENTS:
                raise BridgeError('Arguments too large')
            value = self._context_rpc(server,method,{'name':key,'arguments':args})
            if not isinstance(value,dict) or not isinstance(value.get('messages'),list):
                raise BridgeError('Invalid prompt response')
            for msg in value['messages']:
                if not isinstance(msg,dict) or msg.get('role') not in ('user','assistant') or not isinstance(msg.get('content'),dict):
                    raise BridgeError('Invalid prompt message')
            return value
        raise BridgeError('Unsupported context operation')

    def status(self):
        return {'stopped':self.stopped,'mode':self.cfg.get('mode','read-only'),
                'servers':[{'name':n,'enabled':bool(s.get('enabled')),'connected':n in self.clients,
                            'error':self.errors.get(n),'allowed':len(s.get('allow_tools',[]))}
                           for n,s in self.cfg.get('servers',{}).items()]}

    def call(self, name, args):
        if name == 'bridge_status' and not args:
            return text_result(self.status())
        if name == 'bridge_stop' and not args:
            self.interrupt()
            self.close()
            return text_result({'stopped':True})
        if self.stopped or name not in self.routes:
            raise BridgeError('Unknown or unapproved tool; call tools/list first')
        server, tool = self.routes[name]
        c = self.clients.get(server)
        if c is None:
            raise BridgeError('Server disconnected; refresh tools/list')
        self._begin(c.transport)
        try:
            value=c.call(tool,args)
            if self.stopped:
                raise BridgeError('Operation interrupted; outcome unknown')
            return value
        except BridgeError as e:
            self.errors[server] = str(e)
            self._drop(server)
            raise
        finally:
            self._end(c.transport)

    def _drop(self, name):
        c = self.clients.pop(name,None)
        if c:
            c.close()
        self.routes = {k:v for k,v in self.routes.items() if v[0] != name}
        self.resource_routes = {k:v for k,v in self.resource_routes.items() if v[0] != name}
        self.prompt_routes = {k:v for k,v in self.prompt_routes.items() if v[0] != name}

    def close(self):
        for name in list(self.clients):
            self._drop(name)
