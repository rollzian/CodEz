import os
import http.client
import socket
import ssl
from urllib.parse import urlsplit
import queue
import signal
import subprocess
import sys
import threading
import time
from urllib import request as urlrequest, error as urlerror
from .config import endpoint
from . import __version__
from .protocol import BridgeError, RPCError, PROTOCOL, VERSIONS, NAME, MAX_MESSAGE, encode, decode, request, result, error


class StdioTransport:
    def __init__(self, command, args, cwd, env_names, timeout):
        keys = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP',
                'SystemRoot', 'WINDIR', 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'DISPLAY', 'XAUTHORITY',
                'XDG_RUNTIME_DIR', 'XDG_SESSION_TYPE', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS'} | set(env_names)
        env = {k: v for k, v in os.environ.items() if k in keys}
        env['PYTHONUNBUFFERED'] = '1'
        self.timeout = timeout
        self.queue = queue.Queue(maxsize=8)
        self.closed = threading.Event()
        self.close_lock = threading.Lock()
        try:
            self.process = subprocess.Popen([command, *args], cwd=cwd, env=env, stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, stderr=sys.stderr,
                                            start_new_session=(os.name == 'posix'), bufsize=0)
        except OSError as e:
            raise BridgeError('Cannot start MCP process: ' + type(e).__name__) from e
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _put(self, value):
        while not self.closed.is_set():
            try:
                self.queue.put(value, timeout=0.2)
                return
            except queue.Full:
                continue

    def _read(self):
        try:
            # BufferedReader is important for large screenshots.
            import io
            with io.BufferedReader(self.process.stdout) as source:
                while not self.closed.is_set():
                    line = source.readline(MAX_MESSAGE + 2)
                    if not line:
                        break
                    if len(line) > MAX_MESSAGE + 1 or not line.endswith(b'\n'):
                        self._put(BridgeError('MCP response exceeds limit or is not newline terminated'))
                        return
                    try:
                        self._put(decode(line))
                    except BridgeError:
                        self._put(BridgeError('Invalid MCP JSON from child process'))
                        return
        except (OSError, ValueError):
            if not self.closed.is_set():
                self._put(BridgeError('MCP stdout closed'))
        finally:
            self._put(BridgeError('MCP process exited'))

    def _write(self, msg):
        if self.closed.is_set() or self.process.poll() is not None:
            raise BridgeError('MCP process is not running')
        payload = encode(msg) + b'\n'
        # Unbuffered pipe can perform partial writes.
        try:
            view = memoryview(payload)
            while view:
                written = self.process.stdin.write(view)
                if not written:
                    raise OSError('pipe closed')
                view = view[written:]
        except (OSError, ValueError) as e:
            self.close()
            raise BridgeError('MCP process disconnected') from e

    def exchange(self, msg):
        # Do not retry an ambiguous mutation after transport failure.
        ident = msg.get('id')
        deadline = time.monotonic() + self.timeout
        timer = threading.Timer(self.timeout, self.close)
        timer.daemon = True
        timer.start()
        try:
            self._write(msg)
            if ident is None:
                return None
            while not self.closed.is_set():
                try:
                    incoming = self.queue.get(timeout=min(0.25, max(0.001, deadline-time.monotonic())))
                except queue.Empty:
                    if time.monotonic() >= deadline:
                        break
                    continue
                if isinstance(incoming, Exception):
                    self.close()
                    raise incoming
                if not isinstance(incoming, dict) or incoming.get('jsonrpc') != '2.0':
                    self.close()
                    raise BridgeError('Invalid MCP message')
                if 'method' in incoming:
                    if 'id' in incoming:
                        rid = incoming['id']
                        self._write(result(rid, {}) if incoming['method'] == 'ping' else error(rid, -32601, 'Client capability not available'))
                    continue
                if type(incoming.get('id')) is not type(ident) or incoming.get('id') != ident:
                    self.close()
                    raise BridgeError('Unexpected MCP response id')
                return incoming
            self.close()
            raise BridgeError('MCP call timed out or was stopped; outcome unknown')
        finally:
            timer.cancel()

    def close(self):
        with self.close_lock:
            if self.closed.is_set():
                return
            self.closed.set()
        # Kill the approved child process group on POSIX, including browser descendants.
        try:
            if os.name == 'posix':
                os.killpg(self.process.pid, signal.SIGTERM)
            elif self.process.poll() is None:
                self.process.terminate()
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        if os.name == 'posix':
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.process.stdin.close()
        except OSError:
            pass
        self.reader.join(timeout=2)


class NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPTransport:
    def __init__(self, url, token_env, timeout, *, access_token=None):
        self.url = endpoint(url)
        self.parsed = urlsplit(self.url)
        self.timeout = timeout
        self.session = None
        self.version = None
        self.closed = False
        self.token = os.environ.get(token_env) if token_env else access_token
        if token_env and not self.token:
            raise BridgeError('MCP token environment variable is missing')
        if self.token and any(ord(c) < 33 or ord(c)>126 for c in self.token):
            raise BridgeError('Invalid MCP token')
        self.lock = threading.Lock()
        self.active_socket = None
        self.aborted = False

    def _headers(self):
        h = {'Accept':'application/json, text/event-stream', 'Content-Type':'application/json'}
        if self.token:
            h['Authorization'] = 'Bearer ' + self.token
        if self.session:
            h['Mcp-Session-Id'] = self.session
        if self.version:
            h['MCP-Protocol-Version'] = self.version
        return h

    def abort(self):
        # A network cancellation cannot undo a tool already executed on the remote server.
        with self.lock:
            self.aborted = True
            sock = self.active_socket
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _exchange(self, method, msg, timeout):
        deadline = time.monotonic() + timeout
        p = self.parsed
        if p.scheme == 'https':
            conn = http.client.HTTPSConnection(p.hostname,p.port,timeout=timeout,context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(p.hostname,p.port,timeout=timeout)
        timer = None
        try:
            conn.connect()
            with self.lock:
                if self.aborted:
                    raise BridgeError('MCP session stopped')
                self.active_socket = conn.sock
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise BridgeError('MCP connection timed out')
            timer = threading.Timer(remaining,self.abort)
            timer.daemon = True
            timer.start()
            conn.request(method,p.path or '/',body=encode(msg) if msg is not None else None,headers=self._headers())
            with conn.getresponse() as response:
                if not 200 <= response.status < 300:
                    if response.status == 404:
                        self.closed = True
                    raise BridgeError(f'MCP HTTP {response.status}')
                if method == 'DELETE':
                    return None
                sid = response.headers.get('Mcp-Session-Id')
                if sid:
                    if len(sid)>512 or any(ord(c)<33 or ord(c)>126 for c in sid) or (self.session and self.session != sid):
                        raise BridgeError('Invalid or changed MCP session id')
                    self.session = sid
                if 'id' not in msg and response.status in (202,204):
                    return None
                kind=response.headers.get_content_type()
                if kind == 'application/json':
                    data=response.read(MAX_MESSAGE+1)
                    if self.aborted:
                        raise BridgeError('MCP call cancelled or timed out; outcome unknown')
                    return decode(data)
                if kind == 'text/event-stream':
                    return self._sse(response,msg.get('id'),deadline)
                raise BridgeError('Unexpected MCP HTTP content type')
        except (OSError,http.client.HTTPException) as e:
            raise BridgeError('MCP HTTP connection failed or stopped; outcome unknown') from e
        finally:
            if timer:
                timer.cancel()
            with self.lock:
                self.active_socket = None
            conn.close()

    def exchange(self, msg):
        if self.closed or self.aborted:
            raise BridgeError('MCP session closed')
        return self._exchange('POST',msg,self.timeout)

    def _sse(self, response, ident, deadline):
        total = 0
        fields = []
        while time.monotonic() < deadline and not self.aborted:
            line = response.readline(MAX_MESSAGE + 1)
            total += len(line)
            if total > MAX_MESSAGE:
                raise BridgeError('SSE response too large')
            if not line:
                break
            line = line.rstrip(b'\r\n')
            if not line and fields:
                msg = decode(b'\n'.join(fields))
                fields.clear()
                if not isinstance(msg, dict):
                    raise BridgeError('Invalid MCP SSE message')
                if 'method' in msg and 'id' in msg:
                    raise BridgeError('Server-initiated requests are unsupported in HTTP transport')
                if msg.get('id') == ident and 'method' not in msg:
                    return msg
            elif line.startswith(b'data:'):
                value = line[5:]
                fields.append(value[1:] if value.startswith(b' ') else value)
        raise BridgeError('SSE ended before MCP response; outcome unknown')

    def close(self):
        if self.closed:
            return
        self.closed = True
        # Do not send any additional remote requests after an emergency stop.
        if self.aborted:
            return
        if self.session:
            try:
                self._exchange('DELETE',None,min(self.timeout,3))
            except BridgeError as e:
                print('MCP session cleanup failed',file=sys.stderr)


class Client:
    def __init__(self, transport):
        self.transport = transport
        self.ident = 0
        self.tools = {}
        try:
            init = self.rpc('initialize', {'protocolVersion':PROTOCOL, 'capabilities':{},
                                           'clientInfo':{'name':'codez-studio-bridge','version':__version__}})
            if not isinstance(init, dict) or init.get('protocolVersion') not in VERSIONS:
                raise BridgeError('Unsupported MCP protocol version')
            self.version = init['protocolVersion']
            self.capabilities = init.get('capabilities', {})
            if not isinstance(self.capabilities, dict):
                raise BridgeError('Invalid MCP capabilities')
            if isinstance(transport, HTTPTransport):
                transport.version = self.version
            transport.exchange(request('notifications/initialized'))
        except Exception:
            self.close()
            raise

    def rpc(self, method, params=None):
        self.ident += 1
        msg = self.transport.exchange(request(method, params, self.ident))
        if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or type(msg.get('id')) is not int or msg.get('id') != self.ident:
            raise BridgeError('Invalid MCP response')
        if ('error' in msg) == ('result' in msg):
            raise BridgeError('MCP response must contain exactly one result or error')
        if 'error' in msg:
            code = msg['error'].get('code') if isinstance(msg['error'], dict) else None
            # Do not leak arbitrary remote error text into logs.
            raise RPCError(code if type(code) is int else -32603, f'MCP RPC error ({code})')
        if 'result' not in msg:
            raise BridgeError('MCP response has no result')
        return msg['result']

    def _catalog(self, capability, method, field, key, check):
        if capability not in self.capabilities:
            return {}
        found = {}
        cursor = None
        seen = set()
        total = 0
        for _ in range(16):
            response = self.rpc(method, {'cursor': cursor} if cursor else {})
            total += len(encode(response))
            if total > 2*1024*1024:
                raise BridgeError('MCP catalog exceeds size limit')
            if not isinstance(response, dict) or not isinstance(response.get(field), list):
                raise BridgeError('Invalid MCP catalog')
            for entry in response[field]:
                if not isinstance(entry, dict) or not check(entry):
                    raise BridgeError('Invalid MCP catalog definition')
                ident = entry[key]
                if ident in found:
                    raise BridgeError('Duplicate MCP catalog entry')
                found[ident] = entry
                if len(found) > 1024:
                    raise BridgeError('Too many MCP catalog entries')
            cursor = response.get('nextCursor')
            if cursor is None:
                return found
            if not isinstance(cursor, str) or not cursor or len(cursor)>4096 or cursor in seen:
                raise BridgeError('Invalid or repeated MCP cursor')
            seen.add(cursor)
        raise BridgeError('Too many MCP catalog pages')

    def discover(self):
        self.tools = self._catalog('tools', 'tools/list', 'tools', 'name',
            lambda t: isinstance(t.get('name'), str) and bool(NAME.fullmatch(t['name']))
            and isinstance(t.get('inputSchema'), dict) and t['inputSchema'].get('type') == 'object')
        return self.tools

    def resources(self):
        return self._catalog('resources', 'resources/list', 'resources', 'uri',
            lambda t: isinstance(t.get('uri'), str) and 0 < len(t['uri']) <= 4096
            and all(ord(c)>=32 and not 0xd800<=ord(c)<=0xdfff for c in t['uri'])
            and isinstance(t.get('name'), str))

    def prompts(self):
        return self._catalog('prompts', 'prompts/list', 'prompts', 'name',
            lambda t: isinstance(t.get('name'), str) and bool(NAME.fullmatch(t['name']))
            and isinstance(t.get('arguments', []), list))

    def call(self, name, arguments):
        if name not in self.tools:
            raise BridgeError('Tool not discovered')
        value = self.rpc('tools/call', {'name':name,'arguments':arguments})
        if not isinstance(value, dict) or not isinstance(value.get('content'), list):
            raise BridgeError('Invalid MCP tool result')
        return value

    def close(self):
        self.transport.close()
