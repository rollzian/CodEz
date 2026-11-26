import json,sys
for line in sys.stdin:
    m=json.loads(line)
    if 'id' not in m: continue
    method=m['method'];p=m.get('params',{})
    if method=='initialize':
        value={'protocolVersion':'2025-11-25','capabilities':{'resources':{},'prompts':{}},'serverInfo':{'name':'context','version':'1'}}
    elif method=='resources/list':
        if p.get('cursor')=='page2':
            value={'resources':[{'uri':'local://hidden','name':'Hidden'},{'uri':'local://doc','name':'Doc'}]}
        else: value={'resources':[{'uri':'local://other','name':'Other'}],'nextCursor':'page2'}
    elif method=='resources/read':
        uri=p['uri'];value={'contents':[{'uri':'local://hidden' if uri=='local://bad' else uri,'text':'documentation'}]}
    elif method=='prompts/list':
        value={'prompts':[{'name':'review','arguments':[{'name':'file','required':True}]},{'name':'hidden'}]}
    elif method=='prompts/get':
        value={'messages':[{'role':'user','content':{'type':'text','text':'Review '+p['arguments']['file']}}]}
    else:
        print(json.dumps({'jsonrpc':'2.0','id':m['id'],'error':{'code':-32601,'message':'not supported'}}),flush=True);continue
    print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':value}),flush=True)
