import base64
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from studio_bridge.browser import registry
from studio_bridge.protocol import BridgeError

PAGE=b'''<!doctype html><html><head><title>CodEz browser test</title></head><body><label>Name<input id="name" placeholder="Name"></label><button id="go" onclick="document.querySelector('#result').textContent='Hello '+document.querySelector('#name').value;console.log('button executed')">Run</button><div id="result"></div><input type="password" placeholder="Password"><input type="file" aria-label="Upload" onchange="document.querySelector('#result').textContent=this.files[0].name"><a href="/download" download>Download</a><a href="/next">Next</a><img src="http://127.0.0.1:1/private"></body></html>'''
class Site(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        data=PAGE if self.path=='/' else b'hello artifact' if self.path=='/download' else b'<title>Second page</title><p>Second</p>'
        self.send_response(200);self.send_header('Content-Type','application/octet-stream' if self.path=='/download' else 'text/html');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)


@unittest.skipUnless(os.environ.get('CODEZ_LIVE_BROWSER_TEST')=='1','live browser navigation requires an environment that permits test URLs')
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); (self.root/'out').mkdir(); (self.root/'test.txt').write_text('test')
        self.s=ThreadingHTTPServer(('127.0.0.1',0),Site)
        self.th=threading.Thread(target=self.s.serve_forever,daemon=True);self.th.start()
        self.url=f'http://127.0.0.1:{self.s.server_port}'
        self.r=registry({'origins':[self.url],'headless':True,'executable':shutil.which('chromium'),'sandbox':False,'allow_uploads':True,'downloads_dir':'out'},str(self.root))
    def tearDown(self):
        self.r.close();self.s.shutdown();self.s.server_close();self.th.join();self.temp.cleanup()
    def text(self,tool,args=None): return json.loads(self.r.call(tool,args or {})['content'][0]['text'])
    def ref(self,name): return next(e['ref'] for e in self.text('snapshot')['elements'] if e['name']==name)
    def test_real_browser_interaction(self):
        from PIL import Image
        self.assertEqual(self.text('open',{'url':self.url})['title'],'CodEz browser test')
        name=self.ref('Name');self.text('fill',{'ref':name,'text':'Studio'})
        with self.assertRaises(BridgeError):self.text('fill',{'ref':name,'text':'stale'})
        self.text('click',{'ref':self.ref('Run')})
        self.assertIn('Hello Studio',self.text('read')['text'])
        self.assertTrue(any('button executed' in e['text'] for e in self.text('console')))
        with self.assertRaises(BridgeError):self.text('fill',{'ref':self.ref('Password'),'text':'secret'})
        with self.assertRaises(BridgeError):self.text('open',{'url':'http://127.0.0.1:1/private'})
        self.text('upload',{'ref':self.ref('Upload'),'path':'test.txt'})
        self.assertIn('test.txt',self.text('read')['text'])
        self.text('download',{'ref':self.ref('Download'),'filename':'artifact.bin'})
        self.assertEqual((self.root/'out/artifact.bin').read_bytes(),b'hello artifact')
        with self.assertRaises(BridgeError):self.text('download',{'ref':self.ref('Download'),'filename':'artifact.bin'})
        r=self.r.call('screenshot',{}); image=Image.open(io.BytesIO(base64.b64decode(r['content'][1]['data'])))
        self.assertEqual(image.size,(1280,800));self.assertEqual(image.format,'JPEG')
        self.text('viewport',{'width':600,'height':480})
        self.text('click',{'ref':self.ref('Next')});self.assertIn('Second',self.text('read')['text'])
        self.text('back');self.assertIn('Run',self.text('read')['text'])
        self.assertTrue(any(e.get('failure') for e in self.text('network')))
        first=self.text('tabs')[0]['id']; second=self.text('new_tab',{'url':self.url+'/next'})['tab']
        self.assertNotEqual(first,second);self.text('switch_tab',{'tab':first});self.assertEqual(self.text('read')['title'],'CodEz browser test')
