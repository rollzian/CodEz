import base64, hashlib, json, os, tempfile, threading, time, unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit,urlencode
from urllib.request import urlopen
from urllib.error import HTTPError
from studio_bridge.oauth import authorize,save_token,load_token,get_access_token,refresh_token,discover,auth_lock,bearer_challenge
from studio_bridge.protocol import BridgeError
from studio_bridge.transport import Client,HTTPTransport

class OAuthFixture(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,value,status=200,headers=None):
        raw=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        b=self.server.base
        if self.path=='/.well-known/oauth-protected-resource/mcp':
            self.send({'resource':b+'/mcp','authorization_servers':[b+'/auth']})
        elif self.path=='/.well-known/oauth-authorization-server/auth':
            self.send({'issuer':b+'/auth','authorization_endpoint':b+'/authorize','token_endpoint':b+'/token','code_challenge_methods_supported':['S256'] if self.server.pkce else ['plain'],'token_endpoint_auth_methods_supported':['none']})
        else:self.send({},404)
    def do_POST(self):
        raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
        if self.path=='/token':
            p={k:v[0] for k,v in parse_qs(raw.decode()).items()};self.server.forms.append(p)
            if p['resource']!=self.server.base+'/mcp' or p['client_id']!='registered':self.send({},400);return
            if p['grant_type']=='authorization_code':
                challenge=base64.urlsafe_b64encode(hashlib.sha256(p['code_verifier'].encode()).digest()).decode().rstrip('=')
                if challenge!=self.server.challenge or p['code']!='test-code' or p['redirect_uri']!=self.server.redirect:self.send({},400);return
                token='access-one'
            elif p['grant_type']=='refresh_token' and p['refresh_token']=='refresh-one':token='access-two'
            else:self.send({},400);return
            self.send({'access_token':token,'refresh_token':'refresh-one' if token=='access-one' else 'refresh-two','expires_in':3600,'token_type':'Bearer','scope':'read'});return
        if self.path=='/mcp':
            self.server.received.append(self.headers.get('Authorization'))
            if self.headers.get('Authorization')!='Bearer access-two':self.send({},401,{'WWW-Authenticate':f'Bearer resource_metadata="{self.server.base}/.well-known/oauth-protected-resource/mcp", scope="read"'});return
            p=json.loads(raw)
            if 'id' not in p:self.send({},202);return
            value={'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}} if p['method']=='initialize' else {'tools':[]}
            self.send({'jsonrpc':'2.0','id':p['id'],'result':value});return
        self.send({},404)

@unittest.skipUnless(os.name=='posix','owner-only OAuth cache requires POSIX')
class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.s=ThreadingHTTPServer(('127.0.0.1',0),OAuthFixture);self.s.base=f'http://127.0.0.1:{self.s.server_port}';self.s.pkce=True;self.s.forms=[];self.s.received=[]
        self.t=threading.Thread(target=self.s.serve_forever,daemon=True);self.t.start()
        self.spec={'transport':'http','url':self.s.base+'/mcp','oauth':{'issuer':self.s.base+'/auth','client_id':'registered','scopes':['read']}}
        self.tmp=tempfile.TemporaryDirectory();self.cfg=str(Path(self.tmp.name)/'bridge.json')
    def tearDown(self):
        self.s.shutdown();self.s.server_close();self.t.join();self.tmp.cleanup()
    def login(self):
        errors=[];workers=[]
        def browser(url):
            p=parse_qs(urlsplit(url).query);self.assertEqual(p['resource'],[self.spec['url']]);self.assertEqual(p['code_challenge_method'],['S256'])
            self.s.challenge=p['code_challenge'][0];self.s.redirect=p['redirect_uri'][0]
            def visit():
                try:
                    wrong=self.s.redirect+'?'+urlencode({'state':'wrong','code':'bad'})
                    try:urlopen(wrong,timeout=5);raise AssertionError('wrong state accepted')
                    except HTTPError as e:self.assertEqual(e.code,400);e.close()
                    with urlopen(self.s.redirect+'?'+urlencode({'state':p['state'][0],'code':'test-code','iss':self.spec['oauth']['issuer']}),timeout=5) as r:self.assertEqual(r.status,200)
                except Exception as e:errors.append(e)
            t=threading.Thread(target=visit,daemon=True);workers.append(t);t.start()
        token=authorize(self.spec,browser)
        for t in workers:t.join(5)
        self.assertEqual(errors,[]);return token
    def test_pkce_callback_refresh_and_mcp(self):
        token=self.login();self.assertEqual(token['access_token'],'access-one')
        save_token(self.cfg,'example',token);self.assertEqual(get_access_token(self.cfg,'example',self.spec),'access-one')
        token=refresh_token(self.spec,load_token(self.cfg,'example',self.spec));self.assertEqual(token['refresh_token'],'refresh-two');save_token(self.cfg,'example',token)
        c=Client(HTTPTransport(self.spec['url'],None,3,access_token=get_access_token(self.cfg,'example',self.spec)))
        try:self.assertEqual(c.discover(),{})
        finally:c.close()
        self.assertEqual(self.s.received,[None,None]+['Bearer access-two']*3)
    def test_binding_permissions_and_expiry(self):
        token=self.login();token['expires_at']=int(time.time())-1;save_token(self.cfg,'example',token)
        with self.assertRaisesRegex(BridgeError,'expired'):get_access_token(self.cfg,'example',self.spec)
        with self.assertRaisesRegex(BridgeError,'does not match'):load_token(self.cfg,'example',{**self.spec,'url':self.s.base+'/other'})
        p=Path(self.tmp.name)/'.bridge.json.oauth/example.json';p.chmod(0o644)
        with self.assertRaisesRegex(BridgeError,'private'):load_token(self.cfg,'example',self.spec)
    def test_pkce_and_issuer_mismatch(self):
        self.s.pkce=False
        with self.assertRaisesRegex(BridgeError,'S256'):discover(self.spec)
        self.s.pkce=True
        with self.assertRaisesRegex(BridgeError,'pinned'):discover({**self.spec,'oauth':{**self.spec['oauth'],'issuer':self.s.base+'/evil'}})

    def test_challenge_and_lock(self):
        self.assertEqual(bearer_challenge(['Basic realm="test", Bearer resource_metadata="https://example.test/meta", scope="read"']),{'resource_metadata':'https://example.test/meta','scope':'read'})
        with self.assertRaises(BridgeError):bearer_challenge(['Bearer scope="a", scope="b"'])
        with auth_lock(self.cfg,'example'):
            with self.assertRaisesRegex(BridgeError,'Another OAuth'):
                with auth_lock(self.cfg,'example'):pass
        with self.assertRaisesRegex(BridgeError,'additional OAuth scopes'):
            discover({**self.spec,'oauth':{**self.spec['oauth'],'scopes':[]}})
