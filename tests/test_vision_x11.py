"""Real GUI + MCP child + HTTP model fixture, on a disposable X11 display."""
import base64,io,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from PIL import Image
from studio_bridge.desktop import X11
from test_vision import Provider

ROOT=Path(__file__).resolve().parent.parent
GUI='''import tkinter as tk,sys
from pathlib import Path
r=tk.Tk();r.title("CodEz Vision integration");r.geometry("480x300+30+30");r.configure(bg="#304050")
v=tk.StringVar();e=tk.Entry(r,textvariable=v);e.place(x=30,y=30,width=220,height=35)
v.trace_add("write",lambda *_:Path(sys.argv[1]).write_text(v.get()))
r.update();r.focus_force();e.focus_set();r.update();print("ready",flush=True);r.mainloop()
'''

@unittest.skipUnless(os.environ.get('CODEZ_X11_TEST')=='1','requires explicitly isolated Xvfb display')
class VisionX11Tests(unittest.TestCase):
    def test_real_vision_pipeline_types_into_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state.txt';state.write_text('')
            app=subprocess.Popen([sys.executable,'-c',GUI,str(state)],stdout=subprocess.PIPE,text=True)
            s=ThreadingHTTPServer(('127.0.0.1',0),Provider);s.received=[];s.actions=[{'action':'type','arguments':{'text':'CodEz Vision'},'reason':'Fill the focused field'},{'action':'done','arguments':{},'reason':'Check the field'}]
            th=threading.Thread(target=s.serve_forever,daemon=True);th.start()
            try:
                self.assertEqual(app.stdout.readline().strip(),'ready')
                probe=X11({});target=next(w['id'] for w in probe.windows() if w['title']=='CodEz Vision integration');probe.close()
                cfg=root/'bridge.json';cfg.write_text(json.dumps({'version':1,'mode':'approved','workspace':tmp,'desktop':{'window_id':target,'title_contains':'CodEz Vision integration'},'servers':{'desktop':{'enabled':True,'transport':'builtin','adapter':'desktop','allow_tools':['screenshot','type'],'read_tools':['screenshot'],'timeout':10}},'vision':{'base_url':f'http://127.0.0.1:{s.server_port}/v1','model':'fixture','desktop_server':'desktop','output_tokens':256}}))
                launch=[os.environ['CODEZ_BRIDGE_EXECUTABLE']] if os.environ.get('CODEZ_BRIDGE_EXECUTABLE') else [sys.executable,'-m','studio_bridge']
                cmd=launch+['vision','--config',str(cfg),'--task','Type CodEz Vision','--steps','3','--allow-screen','--approve-actions']
                result=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'],'model_reported_done')
                deadline=time.monotonic()+2
                while state.read_text()!='CodEz Vision' and time.monotonic()<deadline:
                    time.sleep(.02)
                self.assertEqual(state.read_text(),'CodEz Vision')
                self.assertEqual(len(s.received),2)
                for body in s.received:
                    raw=base64.b64decode(body['messages'][1]['content'][1]['image_url']['url'].split(',',1)[1]);im=Image.open(io.BytesIO(raw));self.assertEqual(im.size,(480,300))
            finally:
                app.terminate();app.wait(timeout=5);app.stdout.close();s.shutdown();s.server_close();th.join()
