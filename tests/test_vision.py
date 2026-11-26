import base64,io,json,os,sys,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from PIL import Image
from studio_bridge.vision import VisionProvider,run
from studio_bridge.protocol import BridgeError,image_result
from studio_bridge.desktop import registry

class Provider(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.server.received.append(body)
        action=self.server.actions.pop(0)
        data=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(action)}}]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

class FakeBridge:
    def __init__(self,mode='approved'):
        self.cfg={'servers':{'desktop':{'enabled':True,'transport':'builtin','adapter':'desktop'}},'mode':mode}
        self.calls=[]
    def list(self):
        r=registry({});return [{**x,'name':'desktop__'+x['name']} for x in r.list() if x['name'] in ('screenshot','type')]
    def call(self,name,args):
        self.calls.append((name,args))
        if name.endswith('screenshot'):
            buf=io.BytesIO();Image.new('RGB',(480,300),'white').save(buf,'JPEG')
            return image_result(buf.getvalue(),'image/jpeg',{'frame_id':'a'*32,'width':480,'height':300})
        return {'content':[{'type':'text','text':'typed'}]}

class VisionTests(unittest.TestCase):
    def setUp(self):
        self.s=ThreadingHTTPServer(('127.0.0.1',0),Provider);self.s.received=[];self.s.actions=[]
        self.th=threading.Thread(target=self.s.serve_forever,daemon=True);self.th.start()
        self.provider=VisionProvider({'base_url':f'http://127.0.0.1:{self.s.server_port}/v1','model':'test-vision','output_tokens':256})
    def tearDown(self):self.s.shutdown();self.s.server_close();self.th.join()
    def test_structured_plan_preserves_task_and_only_latest_image(self):
        self.s.actions=[{'action':'type','arguments':{'text':'CodEz'},'reason':'Type into field'},{'action':'done','arguments':{},'reason':'Visible result'}]
        b=FakeBridge();approvals=[]
        result=run(b,self.provider,'Type CodEz into the test field','desktop',3,lambda *a: approvals.append(a) or True)
        self.assertEqual(result['status'],'model_reported_done');self.assertEqual(len(approvals),1)
        self.assertEqual(b.calls[1],('desktop__type',{'text':'CodEz','frame_id':'a'*32}))
        self.assertEqual(len(self.s.received),2)
        for body in self.s.received:
            self.assertEqual(body['max_completion_tokens'],256)
            content=body['messages'][1]['content'];self.assertEqual(len(content),2)
            self.assertIn('Type CodEz into the test field',content[0]['text'])
            raw=base64.b64decode(content[1]['image_url']['url'].split(',',1)[1]);self.assertEqual(Image.open(io.BytesIO(raw)).size,(480,300))
        self.assertEqual(json.loads(self.s.received[1]['messages'][1]['content'][0]['text'])['recent_actions'][0]['action'],'type')
    def test_unapproved_or_injected_action_is_rejected(self):
        for action in [{'action':'launch_app','arguments':{},'reason':'No'},{'action':'type','arguments':{'text':'x','frame_id':'fake'},'reason':'No'}]:
            self.s.actions=[action];b=FakeBridge()
            with self.assertRaises(BridgeError):run(b,self.provider,'test','desktop',1,lambda *_: True)
            self.assertEqual([x[0] for x in b.calls],['desktop__screenshot'])
    def test_denied_confirmation_prevents_action(self):
        self.s.actions=[{'action':'type','arguments':{'text':'x'},'reason':'Type'}];b=FakeBridge()
        self.assertEqual(run(b,self.provider,'test','desktop',1,lambda *_:False)['status'],'operator_stopped')
        self.assertEqual([x[0] for x in b.calls],['desktop__screenshot'])
