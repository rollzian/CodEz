import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import os
import threading
import unittest
from studio_bridge.transport import Client, HTTPTransport
from studio_bridge.protocol import BridgeError


class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,obj=None,status=200,sse=False,headers=None):
        data=b'' if obj is None else json.dumps(obj).encode()
        if sse:
            data=b': keepalive\n\ndata: '+json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{}}).encode()+b'\n\ndata: '+data+b'\n\n'
        self.send_response(status)
        self.send_header('Content-Type','text/event-stream' if sse else 'application/json')
        self.send_header('Content-Length',str(len(data)))
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        self.server.seen.append((self.path,self.headers.get('Authorization'),self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version')))
        if self.path=='/redirect':
            self.send(None,302,headers={'Location':'/leak'});return
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        ident=data.get('id'); method=data['method']
        if method=='initialize':
            self.send({'jsonrpc':'2.0','id':ident,'result':{'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}},headers={'Mcp-Session-Id':'test-session'});return
        if self.headers.get('Mcp-Session-Id')!='test-session' or self.headers.get('MCP-Protocol-Version')!='2025-06-18':
            self.send({},400);return
        if method=='notifications/initialized': self.send(None,202);return
        if method=='tools/list':
            self.send({'jsonrpc':'2.0','id':ident,'result':{'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}},sse=True);return
        if method=='tools/call':
            self.send({'jsonrpc':'2.0','id':ident,'result':{'content':[{'type':'text','text':json.dumps(data['params']['arguments'])}]}},sse=True);return
        self.send({},400)
    def do_DELETE(self):
        self.server.deleted=self.headers.get('Mcp-Session-Id');self.send(None,204)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.s=ThreadingHTTPServer(('127.0.0.1',0),Fixture);self.s.seen=[];self.s.deleted=None
        self.thread=threading.Thread(target=self.s.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.s.server_port}'
    def tearDown(self): self.s.shutdown();self.s.server_close();self.thread.join()
    def test_session_sse_and_delete(self):
        c=Client(HTTPTransport(self.base+'/mcp',None,3))
        try:
            self.assertEqual(set(c.discover()),{'echo'})
            self.assertEqual(json.loads(c.call('echo',{'num':7})['content'][0]['text']),{'num':7})
        finally: c.close()
        self.assertEqual(self.s.deleted,'test-session')
        self.assertEqual(self.s.seen[1][2:],('test-session','2025-06-18'))
    def test_no_redirect_or_token_forwarding(self):
        os.environ['TEST_BRIDGE_TOKEN']='test-token'
        try:
            with self.assertRaises(BridgeError): Client(HTTPTransport(self.base+'/redirect','TEST_BRIDGE_TOKEN',3))
            self.assertEqual(self.s.seen,[('/redirect','Bearer test-token',None,None)])
        finally: os.environ.pop('TEST_BRIDGE_TOKEN',None)
