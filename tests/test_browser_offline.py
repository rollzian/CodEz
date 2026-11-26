"""Actual Chromium DOM actions without web navigation; no browser policy changes."""
import base64,io,json,shutil,tempfile,unittest
from pathlib import Path
from studio_bridge.browser import Browser,registry
from studio_bridge.protocol import BridgeError
from test_browser import PAGE


class OfflineBrowserTests(unittest.TestCase):
    def test_real_dom_screenshot_and_permissions(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            cfg={'origins':['http://127.0.0.1:8080'],'headless':True,'executable':shutil.which('chromium'),'sandbox':False,'allow_uploads':True}
            b=Browser(cfg,tmp)
            try:
                b.start()
                # Inject only test-owned markup into about:blank. The shipped adapter has no set_content/evaluate tool.
                b.page().set_content(PAGE.replace(b'<img src="http://127.0.0.1:1/private">',b'').decode())
                def ref(name):return next(e['ref'] for e in b.snapshot()['elements'] if e['name']==name)
                name=ref('Name'); b.fill(name,'Studio')
                with self.assertRaises(BridgeError): b.fill(name,'stale')
                b.click(ref('Run'))
                self.assertIn('Hello Studio',b.read()['text'])
                self.assertTrue(any('button executed' in e['text'] for e in b.console))
                with self.assertRaises(BridgeError):b.fill(ref('Password'),'secret')
                with self.assertRaises(BridgeError):b.open('http://127.0.0.1:1/private')
                (Path(tmp)/'test.txt').write_text('test')
                b.upload(ref('Upload'),'test.txt');self.assertIn('test.txt',b.read()['text'])
                shot=b.screenshot();im=Image.open(io.BytesIO(base64.b64decode(shot['content'][1]['data'])))
                self.assertEqual(im.size,(1280,800));self.assertEqual(im.format,'JPEG')
                b.viewport(600,480);self.assertEqual(b.page().viewport_size,{'width':600,'height':480})
                first=b.tabs()[0]['id'];second=b.new_tab()['tab'];self.assertNotEqual(first,second)
                b.switch_tab(first);self.assertEqual(b.read()['title'],'CodEz browser test')
            finally:b.close()
