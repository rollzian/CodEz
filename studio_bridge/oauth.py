"""Explicit native OAuth authorization for registered MCP public clients."""
import base64
import hashlib
import http.server
import os
import secrets
import stat
import sys
import tempfile
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from urllib import request, error, parse
from .config import endpoint
from .protocol import BridgeError, decode, encode, request as rpc_request, PROTOCOL
from .transport import NoRedirect

LIMIT = 256 * 1024


def validate_spec(spec):
    conf = spec.get('oauth')
    if not isinstance(conf, dict) or spec.get('transport') != 'http' or spec.get('token_env'):
        raise BridgeError('OAuth requires an HTTP server and no token_env')
    if set(conf) - {'issuer', 'client_id', 'scopes', 'redirect_port', 'resource_metadata'}:
        raise BridgeError('Unknown OAuth configuration fields')
    endpoint(conf.get('issuer'))
    if conf.get('resource_metadata'):
        endpoint(conf['resource_metadata'])
        if origin(conf['resource_metadata']) != origin(spec['url']):
            raise BridgeError('Resource metadata must use the configured MCP origin')
    client = conf.get('client_id')
    if not isinstance(client, str) or not 0 < len(client) <= 2048 or any(ord(c) < 33 for c in client):
        raise BridgeError('Configure a registered OAuth public client ID')
    scopes = conf.get('scopes', [])
    if (not isinstance(scopes, list) or len(scopes) > 64 or
            any(not isinstance(s, str) or not 0 < len(s) <= 256 or any(not 33 <= ord(c) <= 126 or c in '\\"' for c in s) for s in scopes)
            or len(set(scopes)) != len(scopes)):
        raise BridgeError('Invalid OAuth scopes')
    port = conf.get('redirect_port', 0)
    if type(port) is not int or not 0 <= port <= 65535:
        raise BridgeError('Invalid OAuth redirect port')
    return conf


def origin(url):
    p = parse.urlsplit(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)


def well_known(url, kind):
    p = parse.urlsplit(url)
    return parse.urlunsplit((p.scheme, p.netloc, '/.well-known/'+kind+p.path.rstrip('/'), '', ''))


def json_request(url, form=None, optional=False):
    endpoint(url)
    opener = request.build_opener(NoRedirect(), request.ProxyHandler({}))
    headers = {'Accept': 'application/json'}
    data = None
    if form is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        data = parse.urlencode(form).encode('ascii')
    try:
        with opener.open(request.Request(url, data=data, headers=headers), timeout=15) as r:
            if r.headers.get_content_type() != 'application/json':
                raise BridgeError('OAuth response is not JSON')
            raw = r.read(LIMIT+1)
    except error.HTTPError as e:
        status = e.code
        e.close()
        if optional and status == 404:
            return None
        raise BridgeError(f'OAuth HTTP {status}; no automatic retry') from e
    except OSError as e:
        raise BridgeError('OAuth connection failed') from e
    if len(raw)>LIMIT:
        raise BridgeError('OAuth response exceeds size limit')
    value = decode(raw)
    if not isinstance(value,dict):
        raise BridgeError('Invalid OAuth JSON object')
    return value


def bearer_challenge(headers):
    """Parse Bearer auth parameters without treating another scheme as Bearer."""
    for header in headers:
        if not isinstance(header,str) or len(header)>8192:
            raise BridgeError('Invalid OAuth challenge header')
        active=False
        fields={}
        for part in request.parse_http_list(header):
            part=part.strip()
            first=part.split(None,1)
            if first and first[0].lower()=='bearer':
                if active:
                    raise BridgeError('Ambiguous OAuth Bearer challenge')
                active=True
                part=first[1] if len(first)>1 else ''
            elif active and ('=' not in part or (' ' in part.split('=',1)[0].strip())):
                break
            if active and part:
                if '=' not in part:
                    raise BridgeError('Malformed OAuth Bearer challenge')
                key,value=part.split('=',1)
                key=key.strip().lower();value=value.strip()
                if key in fields:
                    raise BridgeError('Duplicate OAuth challenge parameter')
                if len(value)>=2 and value[0]==value[-1]=='"':
                    value=value[1:-1]
                fields[key]=value
        if active:
            return fields
    return {}


def probe_challenge(resource):
    # Only explicit login/refresh invokes unauthenticated discovery; never replay tools.
    body=rpc_request('initialize',{'protocolVersion':PROTOCOL,'capabilities':{},
        'clientInfo':{'name':'codez-studio-bridge','version':'0.2.0'}},1)
    req=request.Request(resource,data=encode(body),headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'},method='POST')
    opener=request.build_opener(NoRedirect(),request.ProxyHandler({}))
    try:
        with opener.open(req,timeout=15):
            raise BridgeError('MCP did not request OAuth; configure resource_metadata explicitly if needed')
    except error.HTTPError as e:
        try:
            if e.code==401:
                return bearer_challenge(e.headers.get_all('WWW-Authenticate',[]))
            if e.code in (404,405):
                return {}
            raise BridgeError(f'OAuth discovery HTTP {e.code}') from e
        finally:e.close()
    except OSError as e:
        raise BridgeError('MCP OAuth discovery failed') from e


def discover(spec):
    conf = validate_spec(spec)
    resource = spec['url']
    issuer = conf['issuer']
    challenge=probe_challenge(resource) if not conf.get('resource_metadata') else {}
    required=challenge.get('scope','').split()
    if set(required)-set(conf.get('scopes',[])):
        raise BridgeError('MCP requires additional OAuth scopes; update explicit scopes before login')
    metadata_url=conf.get('resource_metadata') or challenge.get('resource_metadata')
    if metadata_url:
        endpoint(metadata_url)
        if origin(metadata_url)!=origin(resource):
            raise BridgeError('OAuth resource metadata origin not approved')
        paths=[metadata_url]
    else:
        paths=[well_known(resource,'oauth-protected-resource'),well_known(resource.split('://',1)[0]+'://'+parse.urlsplit(resource).netloc,'oauth-protected-resource')]
    metadata = None
    for url in dict.fromkeys(paths):
        metadata = json_request(url,optional=True)
        if metadata is not None:
            break
    if not metadata or metadata.get('resource') != resource or not isinstance(metadata.get('authorization_servers'),list) or issuer not in metadata['authorization_servers']:
        raise BridgeError('Protected resource metadata does not match the pinned resource and issuer')
    paths = [well_known(issuer,'oauth-authorization-server'),well_known(issuer,'openid-configuration'),issuer.rstrip('/')+'/.well-known/openid-configuration']
    auth = None
    for url in dict.fromkeys(paths):
        auth = json_request(url,optional=True)
        if auth is not None:
            break
    if not auth or auth.get('issuer') != issuer:
        raise BridgeError('OAuth issuer metadata mismatch')
    if not isinstance(auth.get('code_challenge_methods_supported'),list) or 'S256' not in auth['code_challenge_methods_supported']:
        raise BridgeError('Authorization server must advertise S256 PKCE')
    for field in ('authorization_endpoint','token_endpoint'):
        endpoint(auth.get(field))
        # Never downgrade a real HTTPS issuer to local HTTP endpoints.
        if issuer.startswith('https://') and not auth[field].startswith('https://'):
            raise BridgeError('OAuth endpoint is not HTTPS')
    methods = auth.get('token_endpoint_auth_methods_supported')
    if methods is not None and (not isinstance(methods,list) or 'none' not in methods):
        raise BridgeError('Authorization server does not advertise public clients')
    return auth


def callback(authorization_url, state, issuer, port, open_browser):
    result = {}
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def setup(self):
            super().setup()
            self.connection.settimeout(3)
        def do_GET(self):
            valid = False
            try:
                p = parse.urlsplit(self.path)
                q = parse.parse_qs(p.query,keep_blank_values=True,max_num_fields=16)
                valid = (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and p.path == '/callback'
                         and q.get('state') == [state] and ('iss' not in q or q['iss']==[issuer])
                         and not result)
                if valid:
                    code = q.get('code',[])
                    if len(code)==1 and 0<len(code[0])<=4096 and 'error' not in q:
                        result['code']=code[0]
                    else:
                        result['error']=True
            except ValueError:
                valid=False
            payload = b'Authorization received. Return to CodEz.' if valid else b'Invalid OAuth callback.'
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    with http.server.HTTPServer(('127.0.0.1',port),Handler) as server:
        redirect = f'http://127.0.0.1:{server.server_port}/callback'
        open_browser(authorization_url(redirect))
        deadline=time.monotonic()+180
        server.timeout=0.25
        while not result and time.monotonic()<deadline:
            server.handle_request()
        if 'code' not in result:
            raise BridgeError('OAuth authorization denied or expired')
        return result['code'],redirect


def token_value(value, spec, previous=None):
    access=value.get('access_token')
    expiry=value.get('expires_in')
    refresh=value.get('refresh_token',previous.get('refresh_token') if previous else None)
    def valid(t):
        return isinstance(t,str) and 0<len(t)<=16384 and all(33<=ord(c)<=126 for c in t)
    if (not valid(access) or str(value.get('token_type','')).lower()!='bearer'
            or type(expiry) is not int or not 1<=expiry<=2592000 or (refresh is not None and not valid(refresh))):
        raise BridgeError('Invalid or non-expiring OAuth bearer token response')
    conf=spec['oauth']
    scopes=value.get('scope', ' '.join(conf.get('scopes',[])))
    if not isinstance(scopes,str) or set(scopes.split())-set(conf.get('scopes',[])):
        raise BridgeError('OAuth returned scopes beyond explicit configuration')
    return {'resource':spec['url'],'issuer':conf['issuer'],'client_id':conf['client_id'],
            'access_token':access,'refresh_token':refresh,'expires_at':int(time.time())+expiry,'scope':scopes}


def open_auth_url(url):
    print('Open this authorization URL in your browser:\n'+url,file=sys.stderr,flush=True)
    webbrowser.open(url)


def authorize(spec, open_browser=open_auth_url):
    conf=validate_spec(spec)
    auth=discover(spec)
    verifier=secrets.token_urlsafe(64)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
    state=secrets.token_urlsafe(32)
    def url(redirect):
        params={'response_type':'code','client_id':conf['client_id'],'redirect_uri':redirect,
                'state':state,'code_challenge':challenge,'code_challenge_method':'S256','resource':spec['url']}
        if conf.get('scopes'):
            params['scope']=' '.join(conf['scopes'])
        return auth['authorization_endpoint']+'?'+parse.urlencode(params)
    code,redirect=callback(url,state,conf['issuer'],conf.get('redirect_port',0),open_browser)
    response=json_request(auth['token_endpoint'],{'grant_type':'authorization_code','client_id':conf['client_id'],
        'redirect_uri':redirect,'code':code,'code_verifier':verifier,'resource':spec['url']})
    return token_value(response,spec)


def cache_path(cfgpath,name,create=False):
    # Windows ACL semantics require a dedicated credential-store integration; fail closed.
    if os.name!='posix':
        raise BridgeError('OAuth local cache currently requires POSIX; use token_env on Windows')
    from .protocol import NAME
    if not NAME.fullmatch(name):
        raise BridgeError('Invalid OAuth server name')
    folder=Path(cfgpath).parent/('.'+Path(cfgpath).name+'.oauth')
    if create:
        folder.mkdir(mode=0o700,exist_ok=True)
    if folder.exists() or folder.is_symlink():
        st=folder.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.geteuid() or st.st_mode & 0o077:
            raise BridgeError('OAuth cache directory must be private and user-owned')
    return folder/(name+'.json')


@contextmanager
def auth_lock(cfgpath,name):
    # Serialize refresh-token rotation and login/logout within this configuration.
    import fcntl
    path=cache_path(cfgpath,name,create=True).with_suffix('.lock')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_mode & 0o077:
            raise BridgeError('OAuth lock must be private and user-owned')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise BridgeError('Another OAuth operation is active') from e
        yield
    finally:os.close(fd)


def load_token(cfgpath,name,spec):
    path=cache_path(cfgpath,name)
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError as e:
        raise BridgeError('OAuth login required: use auth login') from e
    except OSError as e:
        raise BridgeError('Cannot securely open OAuth token file') from e
    with os.fdopen(fd,'rb') as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.geteuid() or st.st_mode & 0o077 or st.st_size>LIMIT:
            raise BridgeError('OAuth token file must be private and user-owned')
        token=decode(f.read(LIMIT+1))
    conf=validate_spec(spec)
    if (not isinstance(token,dict) or token.get('resource')!=spec['url'] or token.get('issuer')!=conf['issuer']
            or token.get('client_id')!=conf['client_id'] or type(token.get('expires_at')) is not int
            or not isinstance(token.get('scope'),str) or set(token['scope'].split())-set(conf.get('scopes',[]))):
        raise BridgeError('OAuth cached token does not match configuration')
    for field in ('access_token','refresh_token'):
        v=token.get(field)
        if (field=='access_token' or v is not None) and (not isinstance(v,str) or not 0<len(v)<=16384 or any(not 33<=ord(c)<=126 for c in v)):
            raise BridgeError('Invalid cached OAuth token')
    return token


def save_token(cfgpath,name,token):
    path=cache_path(cfgpath,name,create=True)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.token-')
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(encode(token));f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def refresh_token(spec,token):
    if not token.get('refresh_token'):
        raise BridgeError('No refresh token; use auth login')
    auth=discover(spec)
    response=json_request(auth['token_endpoint'],{'grant_type':'refresh_token','client_id':spec['oauth']['client_id'],
        'refresh_token':token['refresh_token'],'resource':spec['url']})
    return token_value(response,spec,token)


def get_access_token(cfgpath,name,spec):
    token=load_token(cfgpath,name,spec)
    if token['expires_at']<=time.time()+15:
        raise BridgeError('OAuth access token expired; use auth refresh or auth login')
    return token['access_token']
