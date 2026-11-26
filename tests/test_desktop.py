"""Real X11 window integration; run on an isolated Xvfb display."""
import base64
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from studio_bridge.desktop import X11,Desktop
from studio_bridge.protocol import BridgeError


@unittest.skipUnless(os.environ.get('CODEZ_X11_TEST')=='1','requires explicitly isolated Xvfb display')
class X11Tests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk=tk
        self.root=tk.Tk();self.root.title('CodEz isolated window test');self.root.geometry('480x300+30+30');self.root.configure(bg='#304050')
        self.var=tk.StringVar(); self.entry=tk.Entry(self.root,textvariable=self.var);self.entry.place(x=30,y=30,width=200,height=35)
        self.count=0
        def clicked(): self.count+=1
        self.button=tk.Button(self.root,text='Click test',command=clicked);self.button.place(x=30,y=100,width=120,height=40)
        self.root.update();self.root.focus_force();self.entry.focus_set();self.root.update()
        probe=X11({});wins=probe.windows();probe.close()
        target=next((w['id'] for w in wins if w['title']=='CodEz isolated window test'),None)
        self.assertIsNotNone(target, wins)
        self.d=Desktop({'window_id':target,'title_contains':'CodEz isolated window test'})
    def tearDown(self):
        if hasattr(self,'d'): self.d.close()
        self.root.destroy()
    def capture(self):
        from PIL import Image
        self.root.update()
        result=self.d.screenshot()
        meta=json.loads(result['content'][0]['text']);im=Image.open(io.BytesIO(base64.b64decode(result['content'][1]['data'])))
        self.assertEqual(im.size,(meta['width'],meta['height']))
        return meta,im
    def test_real_window_capture_input_and_stale_frame(self):
        meta,image=self.capture();self.assertEqual(image.size,(480,300))
        pixel=image.getpixel((400,200));self.assertTrue(all(abs(a-b)<12 for a,b in zip(pixel,(48,64,80))),pixel)
        self.d.click(meta['frame_id'],80,120);self.root.update();self.assertEqual(self.count,1)
        with self.assertRaises(BridgeError):self.d.click(meta['frame_id'],80,120)
        meta,_=self.capture();self.d.click(meta['frame_id'],80,48);self.root.update()
        meta,_=self.capture();self.d.type_text(meta['frame_id'],'CodEz 42!');self.root.update();self.assertEqual(self.var.get(),'CodEz 42!')
        meta,_=self.capture();self.d.key(meta['frame_id'],'a',ctrl=True);self.root.update()
        meta,_=self.capture();self.d.type_text(meta['frame_id'],'New');self.root.update()
        # Tk entry on X11 uses Ctrl+A to move to line start, not Select All; assert actual text action.
        self.assertEqual(self.var.get(),'NewCodEz 42!')
        meta,_=self.capture();self.root.geometry('490x300+30+30');self.root.update()
        with self.assertRaises(BridgeError):self.d.click(meta['frame_id'],80,120)
