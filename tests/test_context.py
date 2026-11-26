import sys,unittest
from pathlib import Path
from studio_bridge.bridge import Bridge
from studio_bridge.protocol import Server,request,BridgeError
ROOT=Path(__file__).resolve().parent.parent

class ContextTests(unittest.TestCase):
    def setUp(self):
        spec={'enabled':True,'transport':'stdio','command':sys.executable,'args':[str(ROOT/'tests/context_fixture.py')],
              'allow_resources':['local://doc'],'allow_prompts':['review'],'allow_tools':[]}
        self.bridge=Bridge({'workspace':str(ROOT),'mode':'read-only','servers':{'fixture':spec}},'unused')
        self.addCleanup(self.bridge.close)
        self.server=Server(self.bridge)
        self.assertEqual(self.server.handle(request('initialize',{'protocolVersion':'2025-11-25'},1))['result']['capabilities'],{'tools':{},'resources':{},'prompts':{}})
        self.server.handle(request('notifications/initialized'))
    def rpc(self,method,params=None):
        return self.server.handle(request(method,params,2))
    def test_resource_filter_and_namespacing(self):
        rows=self.rpc('resources/list')['result']['resources']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['name'],'Doc')
        uri=rows[0]['uri'];self.assertTrue(uri.startswith('codez://fixture/'))
        self.assertEqual(self.rpc('resources/read',{'uri':uri})['result']['contents'],[{'uri':uri,'text':'documentation'}])
        for raw in ('local://doc','local://hidden',uri+'x'):
            self.assertIn('error',self.rpc('resources/read',{'uri':raw}))
        self.bridge.interrupt()
        self.assertIn('error',self.rpc('resources/read',{'uri':uri}))
    def test_prompts_require_explicit_allowlist_and_args(self):
        rows=self.rpc('prompts/list')['result']['prompts']
        self.assertEqual([r['name'] for r in rows],['fixture__review'])
        for args in ({},{'file':12},{'file':'a','extra':'b'}):
            self.assertIn('error',self.rpc('prompts/get',{'name':'fixture__review','arguments':args}))
        self.assertIn('error',self.rpc('prompts/get',{'name':'fixture__hidden'}))
        self.assertEqual(self.rpc('prompts/get',{'name':'fixture__review','arguments':{'file':'main.go'}})['result']['messages'][0]['content']['text'],'Review main.go')
    def test_server_without_tools(self):
        self.bridge.cfg['servers']['fixture']['allow_tools']=['echo']
        self.assertEqual({t['name'] for t in self.bridge.list()},{'bridge_stop','bridge_status'})
        self.assertEqual(len(self.rpc('resources/list')['result']['resources']),1)
