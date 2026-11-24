#!/usr/bin/env python3
"""Exercise actual terminal streaming, model discovery, and safe output."""
import errno
import http.server
import json
import os
import pathlib
import pty
import select
import subprocess
import sys
import tempfile
import threading
import time

binary = pathlib.Path(sys.argv[1]).resolve()
class Provider(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"data":[{"id":"test-model"}]}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert request['stream'] is True
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.end_headers()
        for chunk in ['streamed ', 'answer ', 'test-', 'secret']:
            event = {'choices':[{'delta':{'content':chunk}}]}
            self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.flush()
            time.sleep(.02)
        self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    def log_message(self,*args): pass

with tempfile.TemporaryDirectory() as temp:
    root=pathlib.Path(temp)
    env={**os.environ,'XDG_CONFIG_HOME':str(root/'config'),'XDG_STATE_HOME':str(root/'state'),'CODEZ_API_KEY':'test-secret','TERM':'xterm-256color'}
    for key in ['NO_COLOR','CODEZ_NO_MOTION','CODEZ_NO_STREAM']:
        env.pop(key,None)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        setup=subprocess.run([str(binary)],input=f'3\nhttp://127.0.0.1:{server.server_port}/v1\n\n1\n/exit\n',text=True,cwd=root,env=env,capture_output=True,timeout=15)
        assert setup.returncode==0,setup.stdout+setup.stderr
        assert 'test-model' in setup.stdout and '\x1b' not in setup.stdout, setup.stdout
        master,slave=pty.openpty()
        proc=subprocess.Popen([str(binary)],stdin=slave,stdout=slave,stderr=slave,cwd=root,env=env)
        os.close(slave)
        try:
            os.write(master,b'/help\nstream test\n/exit\n')
            output=bytearray();deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if not select.select([master],[],[],.2)[0]:
                    if proc.poll() is not None:break
                    continue
                try: chunk=os.read(master,8192)
                except OSError as e:
                    if e.errno==errno.EIO:break
                    raise
                if not chunk:break
                output.extend(chunk)
            assert proc.wait(timeout=3)==0
            text=output.decode(errors='replace')
            assert '\x1b[' in text and 'Commands' in text, text
            assert text.count('streamed answer [REDACTED]')==1, text
            assert 'test-secret' not in text, text
            print('PASS: numbered model setup, ANSI terminal, SSE text, split-secret redaction, no duplicate answer')
        finally:
            os.close(master)
            if proc.poll() is None:proc.kill();proc.wait()
    finally:
        server.shutdown();server.server_close()
