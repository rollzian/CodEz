import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from studio_bridge.protocol import Server,Registry,Tool,schema,integer,request,encode,decode,BridgeError,RPCError
from studio_bridge.config import endpoint,load,within
from studio_bridge.bridge import Bridge
from studio_bridge.transport import Client,StdioTransport

ROOT=Path(__file__).resolve().parent.parent


class ProtocolTests(unittest.TestCase):
    def test_handshake_and_validation(self):
        touched=[]
        r=Registry([Tool('write','Test',schema({'count':integer(1,3)},['count']),lambda count:touched.append(count) or {'count':count})])
        s=Server(r)
        self.assertEqual(s.handle(request('tools/list',ident=1))['error']['code'],-32002)
        self.assertEqual(s.handle(request('initialize',{'protocolVersion':'2025-06-18'},2))['result']['protocolVersion'],'2025-06-18')
        self.assertIsNone(s.handle(request('notifications/initialized')))
        self.assertEqual(s.handle(request('tools/list',ident=3))['result']['tools'][0]['name'],'write')
        for args in ({'count':True},{'count':4},{'count':1,'secret':'x'},{}):
            self.assertTrue(s.handle(request('tools/call',{'name':'write','arguments':args},4))['result']['isError'])
        self.assertEqual(touched,[])
        ok=s.handle(request('tools/call',{'name':'write','arguments':{'count':2}},5))
        self.assertEqual(json.loads(ok['result']['content'][0]['text']),{'count':2})
        self.assertEqual(touched,[2])
        self.assertEqual(s.handle(request('bogus',ident=6))['error']['code'],-32601)

    def test_strict_json_and_line_framing(self):
        for raw in (b'{"a":1,"a":2}',b'{"x":NaN}',b'not json'):
            with self.assertRaises(RPCError):
                decode(raw)
        inp=io.BytesIO(b'bad\n'+encode(request('ping',ident=7))+b'\n')
        out=io.BytesIO()
        Server(Registry([])).run(inp,out)
        lines=[json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(lines[0]['error']['code'],-32700)
        self.assertEqual(lines[1]['result'],{})

    def test_paths_and_endpoints(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'ok').write_text('x')
            self.assertEqual(within(root,'ok'),root/'ok')
            with self.assertRaises(BridgeError): within(root,'/etc/passwd')
            if os.name=='posix':
                (root/'escape').symlink_to('/etc/passwd')
                with self.assertRaises(BridgeError): within(root,'escape')
            cfg=root/'cfg.json'; cfg.write_text('{"version":1,"workspace":"'+d+'"}')
            self.assertEqual(load(cfg)[0]['workspace'],d)
            if os.name=='posix':
                cfg.chmod(0o666)
                with self.assertRaises(BridgeError): load(cfg)
        self.assertEqual(endpoint('http://127.0.0.1:8080/mcp'),'http://127.0.0.1:8080/mcp')
        for url in ['http://example.com/mcp','https://user:pw@example.com','https://example.com?q=x','https://example.com/#x','file:///tmp/x']:
            with self.assertRaises(BridgeError): endpoint(url)


class StdioTests(unittest.TestCase):
    def make(self,timeout=5):
        return Client(StdioTransport(sys.executable,[str(ROOT/'tests/mcp_fixture.py')],str(ROOT),[],timeout))

    def test_pagination_and_server_ping(self):
        c=self.make()
        try:
            self.assertEqual(set(c.discover()),{'echo','hidden','hang'})
            out=c.call('echo',{'value':'привет'})
            self.assertEqual(json.loads(out['content'][0]['text']),{'value':'привет'})
        finally: c.close()
        self.assertIsNotNone(c.transport.process.poll())

    def test_timeout_terminates_child(self):
        c=self.make(timeout=1)
        try:
            c.discover(); start=time.monotonic()
            with self.assertRaises(BridgeError): c.call('hang',{})
            self.assertLess(time.monotonic()-start,4)
        finally: c.close()
        self.assertIsNotNone(c.transport.process.poll())

    def test_bridge_allowlist_and_stop(self):
        spec={'enabled':True,'transport':'stdio','command':sys.executable,'args':[str(ROOT/'tests/mcp_fixture.py')],
              'allow_tools':['echo','hidden'],'read_tools':['echo']}
        cfg={'workspace':str(ROOT),'mode':'read-only','servers':{'fixture':spec}}
        b=Bridge(cfg,'unused')
        try:
            self.assertEqual({x['name'] for x in b.list()},{'bridge_status','bridge_stop','fixture__echo'})
            with self.assertRaises(BridgeError): b.call('fixture__hidden',{})
            self.assertEqual(json.loads(b.call('fixture__echo',{'ok':True})['content'][0]['text']),{'ok':True})
            self.assertEqual(json.loads(b.call('bridge_stop',{})['content'][0]['text']),{'stopped':True})
            with self.assertRaises(BridgeError): b.call('fixture__echo',{})
            self.assertEqual(set(x['name'] for x in b.list()),{'bridge_status','bridge_stop'})
        finally: b.close()
