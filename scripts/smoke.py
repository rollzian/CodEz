#!/usr/bin/env python3
import http.server, json, os, pathlib, subprocess, sys, tempfile, threading
binary = pathlib.Path(sys.argv[1]).resolve()
requests = []
class Provider(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path == '/v1/models'
        self.reply({'data':[{'id':'test-model'}]})
    def do_POST(self):
        assert self.path == '/v1/chat/completions'
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(request)
        if len(requests) == 1:
            self.reply({'choices':[{'message':{'role':'assistant','content':'','tool_calls':[{'id':'a','type':'function','function':{'name':'list_files','arguments':'{}'}}]}}]})
        elif len(requests) == 2:
            assert 'example.txt' in request['messages'][-1]['content']
            self.reply({'choices':[{'message':{'role':'assistant','content':'','tool_calls':[{'id':'b','type':'function','function':{'name':'replace_text','arguments':json.dumps({'path':'example.txt','old':'old','new':'new'})}}]}}]})
        else:
            assert 'wrote example.txt' in request['messages'][-1]['content']
            self.reply({'choices':[{'message':{'role':'assistant','content':'verified replacement'}}]})
    def reply(self, data):
        body = json.dumps(data).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass
with tempfile.TemporaryDirectory() as temp:
    root=pathlib.Path(temp); work=root/'repo'; work.mkdir(); (work/'example.txt').write_text('user change\nold\n')
    env={**os.environ,'XDG_CONFIG_HOME':str(root/'config'),'XDG_STATE_HOME':str(root/'state'),'CODEZ_API_KEY':'test-secret'}
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider); thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        def run(text):
            proc=subprocess.run([str(binary)],input=text,text=True,cwd=work,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=25)
            assert proc.returncode==0,proc.stdout
            return proc.stdout
        out=run(f'3\nhttp://127.0.0.1:{server.server_port}/v1\ntest-model\n/models\nfix the file\ny\n/exit\n')
        assert 'verified replacement' in out,out
        assert 'test-model' in out,out
        assert (work/'example.txt').read_text()=='user change\nnew\n'
        assert len(requests)==3
        out=run('/resume\n/exit\n');assert 'Restored 2 messages' in out,out
        assert 'Select [1-5]' not in out,out
        conf=(root/'config'/'codez'/'config.json').read_text(); assert 'test-secret' not in conf
        print('PASS: first run, model discovery, 2 tool rounds, approved exact edit, resume, existing config')
    finally: server.shutdown();server.server_close()
