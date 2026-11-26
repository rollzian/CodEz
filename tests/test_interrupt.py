import json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from studio_bridge.protocol import request
ROOT=Path(__file__).resolve().parent.parent

class InterruptTests(unittest.TestCase):
    def test_stop_interrupts_inflight_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Path(tmp)/'config.json';cfg.write_text(json.dumps({'version':1,'mode':'approved','workspace':tmp,'servers':{'fixture':{'enabled':True,'transport':'stdio','command':sys.executable,'args':[str(ROOT/'tests/mcp_fixture.py')],'allow_tools':['hang','echo'],'timeout':30}}}))
            p=subprocess.Popen([sys.executable,'-m','studio_bridge','serve','--config',str(cfg)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
            def send(msg):p.stdin.write(json.dumps(msg)+'\n');p.stdin.flush()
            def get():return json.loads(p.stdout.readline())
            try:
                send(request('initialize',{'protocolVersion':'2025-11-25'},1));self.assertEqual(get()['id'],1)
                send(request('notifications/initialized'));send(request('tools/list',ident=2));self.assertIn('fixture__hang',[x['name'] for x in get()['result']['tools']])
                send(request('tools/call',{'name':'fixture__hang','arguments':{}},3))
                # Wait until the fixture has received the call by using a short explicit timer; stop must complete far below the 30-second timeout.
                time.sleep(.15);start=time.monotonic()
                send(request('tools/call',{'name':'bridge_stop','arguments':{}},4))
                r=get();self.assertEqual(r['id'],3);self.assertTrue(r['result']['isError'])
                stop=get();self.assertEqual(stop['id'],4);self.assertTrue(json.loads(stop['result']['content'][0]['text'])['stopped'])
                self.assertLess(time.monotonic()-start,5)
                send(request('tools/call',{'name':'fixture__echo','arguments':{}},5));self.assertTrue(get()['result']['isError'])
            finally:
                p.stdin.close()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
                p.stdout.close();p.stderr.close()
