import http.server,json,os,pathlib,subprocess,sys,tempfile,threading
binary=str(pathlib.Path(sys.argv[1]).resolve())
requests=[]
class Provider(http.server.BaseHTTPRequestHandler):
 def reply(self,status,body):
  payload=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
 def do_GET(self):
  assert self.path=='/v1/models'
  self.reply(200,{'data':[{'id':'text-model'},{'id':'numeric-price','pricing':{'prompt':0.00001,'completion':0.00002}},{'id':'invalid-price','pricing':{'prompt':None,'completion':'0'}}]})
 def do_POST(self):
  assert self.path=='/v1/chat/completions';assert self.headers['Authorization']=='Bearer test-key'
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(data)
  assert data['model']=='text-model',data
  if 'tools' in data:
   self.reply(400,{'error':{'code':'unsupported_parameter','param':'tools','message':'This model only supports text'}})
  else:
   assert 'tool_choice' not in data
   self.reply(200,{'choices':[{'message':{'role':'assistant','content':'UNPRICED MODEL WORKS'},'finish_reason':'stop'}]})
 def log_message(self,*a):pass
with tempfile.TemporaryDirectory() as tmp:
 root=pathlib.Path(tmp);env={**os.environ,'XDG_CONFIG_HOME':str(root/'config'),'XDG_STATE_HOME':str(root/'state'),'CODEZ_API_KEY':'test-key','CODEZ_NO_STREAM':'1','CODEZ_SIMPLE_UI':'1'}
 srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider);threading.Thread(target=srv.serve_forever,daemon=True).start()
 try:
  out=subprocess.run([binary],input=f'3\nhttp://127.0.0.1:{srv.server_port}/v1\n3\nhello\n/mode\n5\nhello\n/exit\n',text=True,env=env,cwd=root,capture_output=True,timeout=20)
  assert out.returncode==0,out.stdout+out.stderr
  assert 'Provider configured' in out.stdout,out.stdout
  assert 'unsupported_parameter' in out.stdout and '/mode > Chat' in out.stdout,out.stdout
  assert 'UNPRICED MODEL WORKS' in out.stdout,out.stdout
  assert len(requests)==2,requests
  print('PASS: mixed-pricing catalog, exact unpriced model ID, actionable 400 error, explicit Chat mode, successful inference without tools')
 finally: srv.shutdown();srv.server_close()
