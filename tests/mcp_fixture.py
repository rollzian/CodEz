"""Independent small MCP wire fixture, used only by transport tests."""
import json, sys, time


def send(value):
    print(json.dumps(value),flush=True)


def tool(name):
    return {'name':name,'description':name,'inputSchema':{'type':'object','properties':{}}}


for line in sys.stdin:
    msg=json.loads(line)
    ident=msg.get('id')
    method=msg.get('method')
    params=msg.get('params',{})
    if ident is None:
        continue
    if method=='initialize':
        value={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
    elif method=='tools/list':
        if params.get('cursor')=='next':
            value={'tools':[tool('hidden'),tool('hang')]}
        else:
            value={'tools':[tool('echo')],'nextCursor':'next'}
    elif method=='tools/call':
        if params['name']=='hang':
            time.sleep(30)
        send({'jsonrpc':'2.0','id':'ping-from-server','method':'ping'})
        reply=json.loads(sys.stdin.readline())
        if reply.get('id')!='ping-from-server' or reply.get('result')!={}:
            raise RuntimeError('Missing ping response')
        value={'content':[{'type':'text','text':json.dumps(params.get('arguments',{}))}]}
    else:
        send({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'unknown'}})
        continue
    send({'jsonrpc':'2.0','id':ident,'result':value})
