"""Exercise the built executable and a context-only MCP server over stdio."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent

def main():
    exe=[sys.executable,str(Path(sys.argv[1]).resolve())]
    version=subprocess.check_output(exe+['--version'],text=True).strip()
    assert version=='0.2.0',version
    with tempfile.TemporaryDirectory() as tmp:
        cfg=Path(tmp)/'config.json'
        subprocess.run(exe+['init','--config',str(cfg),'--workspace',tmp],check=True,capture_output=True)
        value=json.loads(cfg.read_text());assert value['mode']=='read-only'
        value['servers']={'fixture':{'enabled':True,'transport':'stdio','command':sys.executable,'args':[str(ROOT/'tests/context_fixture.py')], 'allow_resources':['local://doc'],'allow_prompts':['review'],'allow_tools':[]}}
        cfg.write_text(json.dumps(value))
        status=json.loads(subprocess.check_output(exe+['doctor','--config',str(cfg)],text=True))
        assert status['bridge']==version
        p=subprocess.Popen(exe+['serve','--config',str(cfg)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        def request(method,params=None,ident=1):
            msg={'jsonrpc':'2.0','method':method,'params':params or {}}
            if ident is not None:msg['id']=ident
            p.stdin.write(json.dumps(msg)+'\n');p.stdin.flush()
            if ident is None:return
            res=json.loads(p.stdout.readline());assert res['id']==ident and 'error' not in res,res
            return res['result']
        try:
            info=request('initialize',{'protocolVersion':'2025-11-25'},1)
            assert info['serverInfo']['version']==version and 'resources' in info['capabilities'] and 'prompts' in info['capabilities']
            request('notifications/initialized',ident=None)
            uri=request('resources/list',ident=2)['resources'][0]['uri']
            assert request('resources/read',{'uri':uri},3)['contents'][0]['text']=='documentation'
            prompt=request('prompts/list',ident=4)['prompts'][0]['name']
            assert request('prompts/get',{'name':prompt,'arguments':{'file':'main.go'}},5)['messages'][0]['content']['text']=='Review main.go'
        finally:
            p.stdin.close()
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill();p.wait();raise
            p.stdout.close();p.stderr.close()
        assert p.returncode==0,p.returncode
    print('Package smoke passed:',sys.argv[1],version)

if __name__=='__main__':main()
