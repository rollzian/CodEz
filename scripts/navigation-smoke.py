#!/usr/bin/env python3
import http.server
import json
import os
import pathlib
import pty
import select
import subprocess
import sys
import tempfile
import termios
import threading
import time

binary = pathlib.Path(sys.argv[1]).resolve()
requests = []
class Provider(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(request)
        data = json.dumps({'choices':[{'message':{'role':'assistant','content':'verified: '+request['messages'][-1]['content']}}]}).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self,*args): pass

with tempfile.TemporaryDirectory() as temp:
    root=pathlib.Path(temp)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    cfg=root/'config'/'codez';cfg.mkdir(parents=True)
    (cfg/'config.json').write_text(json.dumps({'provider':'compatible','base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'navigation-model','auth':'api_key'}))
    (cfg/'secret').write_text('test-key');(cfg/'secret').chmod(0o600)
    env={**os.environ,'XDG_CONFIG_HOME':str(root/'config'),'XDG_STATE_HOME':str(root/'state'),'TERM':'xterm-256color','CODEZ_NO_MOTION':'1'}
    env.pop('CODEZ_SIMPLE_UI',None)
    master,slave=pty.openpty();original=termios.tcgetattr(slave)
    proc=subprocess.Popen([str(binary)],stdin=slave,stdout=slave,stderr=slave,cwd=root,env=env)
    data=bytearray()
    def until(marker):
        deadline=time.monotonic()+8
        while marker not in data and time.monotonic()<deadline:
            if select.select([master],[],[],.2)[0]: data.extend(os.read(master,16384))
        assert marker in data, bytes(data).decode(errors='replace')
        end=data.index(marker)+len(marker);result=bytes(data[:end]);del data[:end];return result
    def send(keys): os.write(master,keys)
    try:
        first=until(b'Ctrl+K Menu');assert b'\x1b[2J\x1b[H' in first
        send(b'hel\x0b');until(b'Command palette');send(b'\x1b');until(b'Ctrl+K Menu');send(b'lo\r');until(b'verified: hello');until(b'Ctrl+K Menu')
        assert requests[-1]['messages'][-1]['content']=='hello',requests[-1]
        assert 'navigation-model' in requests[-1]['messages'][0]['content']
        send(b'\x1b[Z');until(b'Agent mode: Ask');until(b'Ctrl+K Menu')
        send(b'question\r');until(b'verified: question');until(b'Ctrl+K Menu')
        assert {x['function']['name'] for x in requests[-1]['tools']} <= {'list_files','read_file','grep','git_status','git_diff'}
        send(b'\x0e');until(b'New chat');until(b'Ctrl+K Menu');send(b'second\r');until(b'verified: second');until(b'Ctrl+K Menu')
        assert [m['content'] for m in requests[-1]['messages'] if m['role']=='user']==['second']
        send(b'\x1b[D');until(b'Back to chat');send(b'\x1b[C');until(b'Ctrl+K Menu')
        for key,name in [(b'D',b'Workspaces'),(b'C',b'Teams'),(b'A',b'Friends'),(b'B',b'Public Projects')]:
            send(b'\x1b[1;5'+key);result=until(b'Sign in with Auxia account');assert name in result,result
            send(b'\x1b[B\r');until(b'Ctrl+K Menu')
        send(b'/exit\r');assert proc.wait(timeout=5)==0;assert termios.tcgetattr(slave)==original
        saved=list((root/'state'/'codez'/'sessions').glob('*.jsonl'));assert len(saved)==2,saved
        result=subprocess.run([str(binary)],input='/resume\n/exit\n',text=True,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=5)
        assert result.returncode==0 and 'Restored 2 messages' in result.stdout,result.stdout
        print('PASS: startup clear, draft preservation, model identity, read-only mode, isolated chats, all four Cloud shortcuts, active chat persistence, terminal restore')
    finally:
        if proc.poll() is None: proc.kill();proc.wait()
        os.close(master);os.close(slave);server.shutdown();server.server_close()
