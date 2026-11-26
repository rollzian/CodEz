import json
import os
from pathlib import Path
from .protocol import BridgeError


def default_config(workspace):
    return {'version':1,'mode':'read-only','workspace':str(workspace),
            'servers':{
                'browser':{'enabled':False,'transport':'builtin','adapter':'browser','timeout':45,
                           'allow_tools':['tabs','read','snapshot','screenshot','console','network'],
                           'read_tools':['tabs','read','snapshot','screenshot','console','network']},
                'desktop':{'enabled':False,'transport':'builtin','adapter':'desktop','timeout':20,
                           'allow_tools':['windows','screenshot'],'read_tools':['windows','screenshot']},
                'resolve':{'enabled':False,'transport':'builtin','adapter':'resolve','timeout':60,
                           'allow_tools':['project_info','timelines','media','items','markers','render_presets'],
                           'read_tools':['project_info','timelines','media','items','markers','render_presets']},
            },
            'browser':{'origins':[],'engine':'chromium','headless':False,'sandbox':True,'allow_uploads':False,'allow_websockets':False},
            'desktop':{'window_id':None,'title_contains':'','portal_scope':None,'allow_portal_input':False,'allow_global_keyboard':False},
            'resolve':{'module_dir':'','script_library':'','project_name':'','project_id':'','render_dir':'','allow_create_project':False},
            'vision':{'desktop_server':'desktop','base_url':'https://api.openai.com/v1','model':'','api_key_env':'CODEZ_VISION_API_KEY',
                      'output_tokens':512,'output_token_field':'max_completion_tokens','json_mode':True,'timeout':60}}


def write_config(path,workspace):
    w=Path(workspace).expanduser().resolve(strict=True)
    if not w.is_dir():
        raise BridgeError('Workspace must be an existing directory')
    p=Path(path).expanduser().absolute()
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError as e:
        raise BridgeError('Configuration already exists; not overwritten') from e
    with os.fdopen(fd,'w',encoding='utf8') as f:
        json.dump(default_config(w),f,indent=2,ensure_ascii=True)
        f.write('\n')
    return p
