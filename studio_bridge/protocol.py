import json
import math
from . import __version__
import re
import sys
import threading
import queue
from dataclasses import dataclass
from typing import Callable

PROTOCOL = '2025-11-25'
VERSIONS = ('2024-11-05', '2025-03-26', '2025-06-18', PROTOCOL)
MAX_MESSAGE = 12 * 1024 * 1024
MAX_ARGUMENTS = 128 * 1024
NAME = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


class BridgeError(Exception):
    pass


class RPCError(BridgeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def encode(value):
    data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_MESSAGE:
        raise BridgeError('Message exceeds size limit')
    return data


def decode(data):
    if len(data) > MAX_MESSAGE:
        raise BridgeError('Message exceeds size limit')
    def pairs(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise ValueError('Duplicate JSON key')
            obj[k] = v
        return obj
    def finite(value):
        n=float(value)
        if not math.isfinite(n):
            raise ValueError('Nonfinite number')
        return n
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_float=finite, parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Nonfinite number')))
    except (ValueError, UnicodeError, RecursionError) as e:
        raise RPCError(-32700, 'Invalid JSON') from e


def request(method, params=None, ident=None):
    r = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
    if ident is not None:
        r['id'] = ident
    return r


def result(ident, value):
    return {'jsonrpc': '2.0', 'id': ident, 'result': value}


def error(ident, code, message):
    return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': code, 'message': message}}


def text_result(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
    return {'content': [{'type': 'text', 'text': text}]}


def image_result(data, mime, metadata):
    import base64
    return {'content': [{'type': 'text', 'text': json.dumps(metadata)},
                        {'type': 'image', 'data': base64.b64encode(data).decode('ascii'), 'mimeType': mime}]}


def fail_result(message):
    return {**text_result(message), 'isError': True}


def schema(properties=None, required=()):
    return {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False}


def string(maximum=1024, **kw):
    return {'type': 'string', 'minLength': 1, 'maxLength': maximum, **kw}


def integer(lo, hi):
    return {'type': 'integer', 'minimum': lo, 'maximum': hi}


def validate(value, rule, path='arguments'):
    # Built-in schemas use a deliberately small, explicit JSON Schema subset.
    t = rule.get('type')
    ok = {'object': isinstance(value, dict), 'array': isinstance(value, list),
          'string': isinstance(value, str), 'integer': type(value) is int,
          'boolean': type(value) is bool}.get(t, False)
    if not ok:
        raise BridgeError(f'{path}: expected {t}')
    if 'enum' in rule and value not in rule['enum']:
        raise BridgeError(f'{path}: value not allowed')
    if t == 'object':
        props = rule.get('properties', {})
        if set(rule.get('required', ())) - value.keys():
            raise BridgeError(f'{path}: missing required fields')
        if rule.get('additionalProperties') is False and value.keys() - props.keys():
            raise BridgeError(f'{path}: unknown fields')
        for k, v in value.items():
            if k in props:
                validate(v, props[k], f'{path}.{k}')
    elif t == 'array':
        if not rule.get('minItems', 0) <= len(value) <= rule.get('maxItems', 100):
            raise BridgeError(f'{path}: invalid array length')
        for v in value:
            validate(v, rule['items'], path + '[]')
    elif t == 'string':
        if not rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', 65536) or '\x00' in value:
            raise BridgeError(f'{path}: invalid string length or content')
    elif t == 'integer' and not rule.get('minimum', -2**63) <= value <= rule.get('maximum', 2**63-1):
        raise BridgeError(f'{path}: number out of range')


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable
    read_only: bool = False

    def definition(self):
        return {'name': self.name, 'description': self.description, 'inputSchema': self.input_schema,
                'annotations': {'readOnlyHint': self.read_only}}

    def call(self, args):
        validate(args, self.input_schema)
        value = self.fn(**args)
        if isinstance(value, dict) and isinstance(value.get('content'), list):
            return value
        return text_result(value)


class Registry:
    def __init__(self, tools):
        self.tools = {tool.name: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError('Duplicate tools')

    def list(self):
        return [t.definition() for t in self.tools.values()]

    def call(self, name, args):
        if name not in self.tools:
            raise BridgeError('Unknown or unapproved tool')
        return self.tools[name].call(args)

    def close(self):
        pass


class Server:
    def __init__(self, registry, name='codez-studio-bridge'):
        self.registry = registry
        self.name = name
        self.initialized = False
        self.ready = False

    def handle(self, msg):
        if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or not isinstance(msg.get('method'), str):
            return error(None, -32600, 'Invalid request')
        ident = msg.get('id')
        has_id = 'id' in msg
        if has_id and (type(ident) not in (str, int) or len(str(ident)) > 128):
            return error(None, -32600, 'Invalid id')
        params = msg.get('params', {})
        if not isinstance(params, dict):
            return error(ident, -32602, 'Invalid params') if has_id else None
        method = msg['method']
        if not has_id:
            if method == 'notifications/initialized' and self.initialized:
                self.ready = True
            return None
        try:
            if method == 'initialize':
                if self.initialized:
                    raise RPCError(-32600, 'Already initialized')
                version = params.get('protocolVersion')
                if version not in VERSIONS:
                    version = PROTOCOL
                self.initialized = True
                value = {'protocolVersion': version, 'capabilities': self.registry.capabilities() if hasattr(self.registry,'capabilities') else {'tools': {}},
                         'serverInfo': {'name': self.name, 'version': __version__}}
            elif method == 'ping':
                value = {}
            elif not self.ready:
                raise RPCError(-32002, 'Initialize first')
            elif method == 'tools/list':
                if params.get('cursor'):
                    raise RPCError(-32602, 'Invalid cursor')
                value = {'tools': self.registry.list()}
            elif method == 'tools/call':
                name, args = params.get('name'), params.get('arguments', {})
                if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(args, dict):
                    raise RPCError(-32602, 'Invalid tool call')
                if len(encode(args)) > MAX_ARGUMENTS:
                    raise RPCError(-32602, 'Arguments too large')
                try:
                    value = self.registry.call(name, args)
                except BridgeError as e:
                    value = fail_result(str(e))
            elif method in ('resources/list','resources/read','resources/templates/list','prompts/list','prompts/get') and hasattr(self.registry,'context_request'):
                try:
                    value = self.registry.context_request(method,params)
                except BridgeError as e:
                    raise RPCError(-32602,str(e)) from e
            else:
                raise RPCError(-32601, 'Method not supported')
            return result(ident, value)
        except RPCError as e:
            return error(ident, e.code, str(e))
        except Exception as e:
            # Do not write exception arguments, screenshots or credentials to logs.
            print(f'{self.name}: {type(e).__name__}', file=sys.stderr, flush=True)
            return error(ident, -32603, 'Internal error; inspect local configuration')

    def _respond(self,out,response):
        if response is None:
            return
        try:
            payload = encode(response)
        except BridgeError:
            payload = encode(error(response.get('id'), -32603, 'Result exceeds message limit'))
        out.write(payload + b'\n')
        out.flush()

    def _read_message(self,line):
        try:
            return decode(line)
        except RPCError as e:
            return e

    def _dispatch(self,msg):
        if isinstance(msg,RPCError):
            return error(None,msg.code,str(msg))
        return self.handle(msg)

    def _interruptible(self,inp,out):
        pending=queue.Queue(maxsize=8)
        eof=threading.Event()
        state_lock=threading.Lock()
        active=[None]
        cancelled=set()
        def reader():
            try:
                while line:=inp.readline(MAX_MESSAGE+2):
                    if len(line)>MAX_MESSAGE+1 or not line.endswith(b'\n'):
                        self.registry.interrupt()
                        break
                    msg=self._read_message(line)
                    if isinstance(msg,dict) and msg.get('jsonrpc')=='2.0':
                        params=msg.get('params')
                        if isinstance(params,dict):
                            if msg.get('method')=='notifications/cancelled' and 'id' not in msg:
                                target=params.get('requestId')
                                if type(target) in (int,str):
                                    with state_lock:
                                        if len(cancelled)<128:
                                            cancelled.add(target)
                                        running=active[0]==target
                                    if running:
                                        self.registry.interrupt()
                                continue
                            if msg.get('method')=='tools/call' and params.get('name')=='bridge_stop' and params.get('arguments',{})=={} and type(msg.get('id')) in (int,str):
                                self.registry.interrupt()
                    try:
                        pending.put_nowait(msg)
                    except queue.Full:
                        self.registry.interrupt()
                        break
            finally:
                eof.set()
                # A disconnected host cannot approve additional queued actions.
                self.registry.interrupt()
        thread=threading.Thread(target=reader,daemon=True)
        thread.start()
        while not eof.is_set() or not pending.empty():
            try:
                msg=pending.get(timeout=0.1)
            except queue.Empty:
                continue
            ident=msg.get('id') if isinstance(msg,dict) else None
            if type(ident) not in (int,str):
                ident=None
            with state_lock:
                was_cancelled=ident is not None and ident in cancelled
                active[0]=ident
                if was_cancelled:
                    cancelled.discard(ident)
            try:
                response=error(ident,-32800,'Request cancelled') if was_cancelled else self._dispatch(msg)
                self._respond(out,response)
            finally:
                with state_lock:
                    active[0]=None

    def run(self, inp=None, out=None):
        inp = inp or sys.stdin.buffer
        out = out or sys.stdout.buffer
        try:
            if hasattr(self.registry,'interrupt'):
                self._interruptible(inp,out)
            else:
                while line := inp.readline(MAX_MESSAGE + 2):
                    if len(line)>MAX_MESSAGE+1 or not line.endswith(b'\n'):
                        break
                    self._respond(out,self._dispatch(self._read_message(line)))
        finally:
            self.registry.close()
