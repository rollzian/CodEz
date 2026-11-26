import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import zipfile
from . import __version__
from .bridge import Bridge
from .config import load
from .protocol import BridgeError, Server, decode


def launch_command():
    # zipapp contains the package; spawn that exact archive rather than relying on PYTHONPATH.
    p=Path(sys.argv[0]).resolve()
    if p.is_file() and zipfile.is_zipfile(p):
        return [sys.executable,str(p)]
    return [sys.executable,'-m','studio_bridge']


def adapter(name,cfg):
    if name=='browser':
        from .browser import registry
        return registry(cfg.get('browser',{}),cfg['workspace'])
    if name=='desktop':
        from .desktop import registry
        return registry(cfg.get('desktop',{}),mode=cfg.get('mode','read-only'))
    if name=='resolve':
        from .resolve import registry
        return registry(cfg.get('resolve',{}),cfg['workspace'])
    raise BridgeError('Unknown adapter')


def doctor(cfg):
    import importlib.util
    packages={name:importlib.util.find_spec(name) is not None for name in ('playwright','PIL','Xlib','gi')}
    return {'bridge':__version__,'python':sys.version.split()[0],'platform':sys.platform,
            'workspace':cfg['workspace'],'mode':cfg.get('mode','read-only'),
            'optional_packages':packages,'display':bool(os.environ.get('DISPLAY')),
            'wayland':bool(os.environ.get('WAYLAND_DISPLAY')) or os.environ.get('XDG_SESSION_TYPE')=='wayland',
            'browser_executable':bool(cfg.get('browser',{}).get('executable') and Path(cfg['browser']['executable']).is_file()),
            'resolve_module':bool(cfg.get('resolve',{}).get('module_dir') and (Path(cfg['resolve']['module_dir'])/'DaVinciResolveScript.py').is_file()),
            'servers':[{'name':k,'enabled':bool(v.get('enabled')),'transport':v.get('transport'),
                        'command_present':bool(shutil.which(v['command'])) if v.get('transport')=='stdio' and v.get('command') else None}
                       for k,v in cfg.get('servers',{}).items()]}


def output(value):
    print(json.dumps(value,ensure_ascii=True,indent=2,allow_nan=False))


def confirmation(name,args,reason):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise BridgeError('Interactive terminal required for action confirmation')
    # JSON escaping prevents control sequences in model-generated text reaching the terminal.
    print(json.dumps({'action':name,'arguments':args,'reason':reason},ensure_ascii=True),file=sys.stderr)
    print('Approve this action? [y/N] ',end='',file=sys.stderr,flush=True)
    return sys.stdin.readline().strip().lower()=='y'


def parser():
    p=argparse.ArgumentParser(prog='codez-studio-bridge')
    p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='sub',required=True)
    for name in ('init','serve','doctor','tools','call','vision','adapter','auth'):
        q=sub.add_parser(name)
        if name=='adapter':
            q.add_argument('adapter',choices=('browser','desktop','resolve'))
        q.add_argument('--config',required=True,help='Absolute path to user-owned configuration JSON')
        if name=='init':
            q.add_argument('--workspace',default='.',help='Existing workspace directory')
        if name=='auth':
            q.add_argument('action',choices=('login','refresh','logout','status'))
            q.add_argument('server')
        if name=='call':
            q.add_argument('tool')
            q.add_argument('--args',default='{}',help='JSON object')
            q.add_argument('--approve',action='store_true',help='Explicitly approve this configured tool invocation')
        if name=='vision':
            q.add_argument('--task',required=True)
            q.add_argument('--allow-screen',action='store_true',help='Consent to send the selected window or portal-approved monitor to the configured vision provider')
            q.add_argument('--approve-actions',action='store_true',help='Preapprove actions already allowed by local configuration')
            q.add_argument('--steps',type=int,default=8)
    return p


def auth_command(cfg,cfgpath,args):
    from .oauth import authorize,load_token,save_token,refresh_token,cache_path,validate_spec,auth_lock
    spec=cfg.get('servers',{}).get(args.server,{})
    if not spec.get('enabled'):
        raise BridgeError('OAuth server must be explicitly enabled')
    validate_spec(spec)
    path=cache_path(cfgpath,args.server)
    if args.action=='status':
        token=load_token(cfgpath,args.server,spec)
    else:
        with auth_lock(cfgpath,args.server):
            if args.action=='logout':
                path.unlink(missing_ok=True)
                output({'logged_out_locally':True,'remote_revocation':False})
                return 0
            token=authorize(spec) if args.action=='login' else refresh_token(spec,load_token(cfgpath,args.server,spec))
            save_token(cfgpath,args.server,token)
    output({'server':args.server,'expires_at':token['expires_at'],'scope':token['scope'],'refresh_available':bool(token.get('refresh_token'))})
    return 0


def main(argv=None):
    args=parser().parse_args(argv)
    if hasattr(signal,'SIGTERM'):
        signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    bridge=None
    try:
        if args.sub=='init':
            from .defaults import write_config
            output({'config':str(write_config(args.config,args.workspace)),'mode':'read-only','enabled_servers':0})
            return 0
        cfg,cfgpath=load(args.config)
        if args.sub=='adapter':
            # Adapter is an internal, local child interface. Apply the same allowlists even when invoked directly.
            from .protocol import Registry
            specs=[s for s in cfg.get('servers',{}).values() if s.get('enabled') and s.get('transport')=='builtin' and s.get('adapter')==args.adapter]
            if len(specs)!=1:
                raise BridgeError('Exactly one enabled built-in server is required for this adapter')
            allowed=set(specs[0].get('allow_tools',[]))
            if args.adapter=='desktop':
                dc=cfg.get('desktop',{})
                cfg={**cfg,'desktop':{**dc,
                    'allow_portal_input':dc.get('allow_portal_input') is True and bool(allowed & {'click','move','drag','scroll','type','key'}),
                    'allow_global_keyboard':dc.get('allow_global_keyboard') is True and bool(allowed & {'type','key'})}}
            r=adapter(args.adapter,cfg)
            if cfg.get('mode','read-only')=='read-only':
                allowed &= set(specs[0].get('read_tools',[]))
                r.tools={k:v for k,v in r.tools.items() if k in allowed and v.read_only}
            else:
                r.tools={k:v for k,v in r.tools.items() if k in allowed}
            Server(r,'codez-'+args.adapter).run()
            return 0
        if args.sub=='auth':
            return auth_command(cfg,cfgpath,args)
        if args.sub=='doctor':
            output(doctor(cfg))
            return 0
        if args.sub=='vision':
            if not args.allow_screen:
                raise BridgeError('Vision requires --allow-screen: images will be sent to the configured provider')
            if not 1<=args.steps<=20:
                raise BridgeError('Vision steps must be 1..20')
            name=cfg.get('vision',{}).get('desktop_server','desktop')
            if name not in cfg.get('servers',{}):
                raise BridgeError('Configured Vision desktop server is missing')
            from .desktop import is_wayland
            if args.approve_actions and is_wayland() and cfg.get('desktop',{}).get('allow_global_keyboard') is True:
                raise BridgeError('Global Wayland keyboard requires per-action confirmation')
            if args.approve_actions and cfg.get('mode')!='approved':
                raise BridgeError('Action preapproval requires approved mode')
            if not args.approve_actions and not (sys.stdin.isatty() and sys.stderr.isatty()):
                # Read-only Vision is usable from noninteractive callers.
                if cfg.get('mode')=='approved':
                    raise BridgeError('Use a terminal for confirmations or explicitly preapprove configured actions')
            cfg={**cfg,'servers':{name:cfg['servers'][name]}}
            bridge=Bridge(cfg,cfgpath,launch_command())
            from .vision import VisionProvider,run
            provider=VisionProvider(cfg.get('vision',{}))
            output(run(bridge,provider,args.task,name,args.steps,(lambda *_:True) if args.approve_actions else confirmation))
            return 0
        bridge=Bridge(cfg,cfgpath,launch_command())
        if args.sub=='serve':
            Server(bridge).run()
        elif args.sub=='tools':
            output({'tools':bridge.list(),'status':bridge.status()})
        elif args.sub=='call':
            if not args.approve:
                raise BridgeError('Use --approve for a single explicit tool invocation; tools must also be locally allowed')
            value=decode(args.args.encode('utf8'))
            if not isinstance(value,dict):
                raise BridgeError('Tool arguments must be a JSON object')
            bridge.list()
            result=bridge.call(args.tool,value)
            output(result)
            return 1 if result.get('isError') else 0
        return 0
    except KeyboardInterrupt:
        print('Stopped by operator',file=sys.stderr)
        return 130
    except (BridgeError,OSError,ValueError) as e:
        print(str(e) if isinstance(e,BridgeError) else f'Configuration or local I/O error: {type(e).__name__}',file=sys.stderr)
        return 1
    finally:
        if bridge:
            bridge.close()


if __name__=='__main__':
    raise SystemExit(main())
