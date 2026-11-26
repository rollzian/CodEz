import json,threading,unittest
from http.server import ThreadingHTTPServer
from studio_bridge.bridge import Bridge
from studio_bridge.protocol import BridgeError
from test_http import Fixture

class ReconnectFixture(Fixture):
    def do_POST(self):
        # The first request to this path fails after initialization. Track only real tool invocations.
        raw=self.rfile.read(int(self.headers['Content-Length']));msg=json.loads(raw);ident=msg.get('id');method=msg['method']
        if method=='initialize':
            self.server.initialized+=1
            self.send({'jsonrpc':'2.0','id':ident,'result':{'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}},headers={'Mcp-Session-Id':'session-'+str(self.server.initialized)});return
        if method=='notifications/initialized':self.send(None,202);return
        if method=='tools/list':self.send({'jsonrpc':'2.0','id':ident,'result':{'tools':[{'name':'write','inputSchema':{'type':'object'}}]}});return
        if method=='tools/call':
            self.server.calls+=1
            if self.server.calls==1:self.send({},404);return
            self.send({'jsonrpc':'2.0','id':ident,'result':{'content':[{'type':'text','text':'ok'}]}});return
        self.send({},400)

class ReconnectTests(unittest.TestCase):
    def test_session_loss_requires_explicit_retry(self):
        s=ThreadingHTTPServer(('127.0.0.1',0),ReconnectFixture);s.initialized=0;s.calls=0;s.deleted=None
        t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
        cfg={'mode':'approved','workspace':'.','servers':{'remote':{'enabled':True,'transport':'http','url':f'http://127.0.0.1:{s.server_port}/mcp','allow_tools':['write']}}}
        b=Bridge(cfg,'unused')
        try:
            self.assertIn('remote__write',{d['name'] for d in b.list()})
            with self.assertRaisesRegex(BridgeError,'404'):b.call('remote__write',{})
            with self.assertRaises(BridgeError):b.call('remote__write',{})
            self.assertEqual((s.initialized,s.calls),(1,1))
            self.assertIn('remote__write',{d['name'] for d in b.list()})
            self.assertEqual((s.initialized,s.calls),(2,1))
            self.assertEqual(b.call('remote__write',{})['content'][0]['text'],'ok')
            self.assertEqual(s.calls,2)
        finally:
            b.close();s.shutdown();s.server_close();t.join()
