import json,os,unittest
from unittest.mock import patch
from PIL import Image
from studio_bridge.desktop_portal import Wayland
from studio_bridge.desktop import Desktop,registry
from studio_bridge.protocol import BridgeError

class PortalFixture:
    def __init__(self):self.calls=[];self.closed=False;self.size=(1920,1080)
    def open(self,scope,devices):self.calls.append(('open',scope,devices));return 7,{'logical_size':(1280,720)}
    def check(self):
        if self.closed:raise BridgeError('closed')
    def image(self):self.check();return Image.new('RGB',self.size,'white')
    def input(self,method,signature,values):self.check();self.calls.append((method,signature,values))
    def close(self):self.closed=True

class PortalTests(unittest.TestCase):
    def test_window_capture_never_enables_input(self):
        p=PortalFixture();d=Wayland({'portal_scope':'window'},p)
        self.assertEqual(p.calls,[('open','window',0)])
        image,geo=d.capture();self.assertEqual(geo,(0,0,1920,1080))
        with self.assertRaises(BridgeError):d.click(7,100,100,1,1)
        with self.assertRaises(BridgeError):d.type_text('a')
        d.close();self.assertTrue(p.closed)
        with self.assertRaises(BridgeError):Wayland({'portal_scope':'window','allow_portal_input':True},PortalFixture())
    def test_monitor_coordinates_frame_and_keyboard(self):
        p=PortalFixture();driver=Wayland({'portal_scope':'monitor','allow_portal_input':True,'allow_global_keyboard':True},p)
        d=Desktop({},driver)
        shot=json.loads(d.screenshot()['content'][0]['text']);self.assertEqual(shot['width'],1600)
        d.click(shot['frame_id'],800,450)
        self.assertEqual(p.calls,[('open','monitor',3),('NotifyPointerMotionAbsolute','udd',(7,640.,360.)),('NotifyPointerButton','iu',(272,1)),('NotifyPointerButton','iu',(272,0))])
        with self.assertRaises(BridgeError):d.click(shot['frame_id'],800,450)
        shot=json.loads(d.screenshot()['content'][0]['text']);d.key(shot['frame_id'],'a',ctrl=True)
        self.assertEqual(p.calls[-4:],[('NotifyKeyboardKeysym','iu',(0xffe3,1)),('NotifyKeyboardKeysym','iu',(97,1)),('NotifyKeyboardKeysym','iu',(97,0)),('NotifyKeyboardKeysym','iu',(0xffe3,0))])
        shot=json.loads(d.screenshot()['content'][0]['text']);p.size=(1024,768)
        with self.assertRaisesRegex(BridgeError,'changed size'):d.move(shot['frame_id'],2,2)
        self.assertTrue(p.closed)
    def test_readonly_registry_exposes_only_capture(self):
        with patch.dict(os.environ,{'XDG_SESSION_TYPE':'wayland'}):
            r=registry({'portal_scope':'monitor','allow_portal_input':True,'allow_global_keyboard':True},mode='read-only')
            self.assertEqual(set(r.tools),{'screenshot'})
            r=registry({'portal_scope':'monitor','allow_portal_input':True},mode='approved')
            self.assertEqual(set(r.tools),{'screenshot','click','move','drag','scroll'})
