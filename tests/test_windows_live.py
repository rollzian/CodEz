"""Run only on an explicitly selected interactive Windows desktop."""
import base64,io,json,os,sys,unittest
from studio_bridge.protocol import BridgeError

@unittest.skipUnless(sys.platform=='win32' and os.environ.get('CODEZ_WINDOWS_TEST')=='1','requires explicitly authorized interactive Windows desktop')
class WindowsLiveTests(unittest.TestCase):
    def test_real_window_capture_and_input(self):
        from studio_bridge.desktop_win import Windows
        from studio_bridge.desktop import Desktop
        from PIL import Image
        driver=Windows({})  # Set DPI awareness before creating the GUI.
        import tkinter as tk
        root=tk.Tk();self.addCleanup(root.destroy)
        root.title('CodEz isolated Windows test');root.geometry('480x300+30+30');root.configure(bg='#304050')
        value=tk.StringVar();entry=tk.Entry(root,textvariable=value);entry.place(x=30,y=30,width=220,height=35)
        count=[];button=tk.Button(root,text='Click test',command=lambda:count.append(True));button.place(x=30,y=100,width=120,height=40)
        root.update();root.focus_force();root.update()
        target=next((w['id'] for w in driver.windows() if w['title']=='CodEz isolated Windows test'),None)
        self.assertIsNotNone(target)
        driver.ident=int(target,0);driver.cfg={'title_contains':'CodEz isolated Windows test'}
        d=Desktop({},driver);self.addCleanup(d.close)
        self.assertTrue(d.focus()['foreground']);root.update()
        def capture():
            result=d.screenshot();meta=json.loads(result['content'][0]['text'])
            with Image.open(io.BytesIO(base64.b64decode(result['content'][1]['data']))) as im:
                self.assertEqual(im.size,(meta['width'],meta['height']))
            return meta
        meta=capture();d.click(meta['frame_id'],80,120);root.update();self.assertEqual(count,[True])
        with self.assertRaises(BridgeError):d.click(meta['frame_id'],80,120)
        meta=capture();d.click(meta['frame_id'],80,48);root.update()
        meta=capture();d.type_text(meta['frame_id'],'CodEz 42');root.update();self.assertEqual(value.get(),'CodEz 42')
