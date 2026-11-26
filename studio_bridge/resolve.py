import importlib
import os
import re
from pathlib import Path
import sys
from uuid import uuid4
from .config import within
from .protocol import BridgeError, Tool, Registry, schema, string, integer


def api(obj, name, *args):
    fn = getattr(obj, name, None)
    if not callable(fn):
        raise BridgeError(f'Resolve API method {name} is unavailable in the installed version')
    try:
        return fn(*args)
    except Exception as e:
        raise BridgeError(f'Resolve API {name} failed ({type(e).__name__})') from e


def checked(value, operation):
    if not value:
        raise BridgeError(f'Resolve rejected {operation}')
    return value


def sequence(value):
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list,tuple)):
        return list(value)
    return []


def uid(obj, method='GetUniqueId'):
    return str(checked(api(obj,method),'object identifier'))


class Resolve:
    def __init__(self,cfg,workspace,app=None):
        self.cfg=cfg
        self.workspace=workspace
        self.app=app
        self.project_id=None
        self.jobs={}

    def connect(self):
        if self.app is not None:
            return self.app
        # This module and library must come from the operator's installed Resolve.
        raw=self.cfg.get('module_dir') or (str(Path(os.environ['RESOLVE_SCRIPT_API'])/'Modules') if os.environ.get('RESOLVE_SCRIPT_API') else None)
        if not raw:
            raise BridgeError('Configure the installed Resolve scripting module directory')
        path=Path(raw).expanduser().resolve(strict=True)
        if not (path/'DaVinciResolveScript.py').is_file():
            raise BridgeError('DaVinciResolveScript.py not found in the selected module directory')
        if self.cfg.get('script_library'):
            lib=Path(self.cfg['script_library']).expanduser().resolve(strict=True)
            if not lib.is_file():
                raise BridgeError('Invalid Resolve scripting library path')
            os.environ['RESOLVE_SCRIPT_LIB']=str(lib)
        sys.path.insert(0,str(path))
        try:
            module=importlib.import_module('DaVinciResolveScript')
            app=module.scriptapp('Resolve')
        except Exception as e:
            raise BridgeError('Resolve scripting connection failed; check installed version and local scripting access') from e
        finally:
            sys.path.remove(str(path))
        if not app:
            raise BridgeError('DaVinci Resolve is not running or local scripting is disabled')
        self.app=app
        return app

    def manager(self):
        return checked(api(self.connect(),'GetProjectManager'),'project manager')

    def project(self):
        p=checked(api(self.manager(),'GetCurrentProject'),'current project')
        approved=self.cfg.get('project_name')
        if not approved or api(p,'GetName')!=approved:
            raise BridgeError('Open the exact operator-approved Resolve project first')
        ident=uid(p)
        if self.cfg.get('project_id') and ident!=self.cfg['project_id']:
            raise BridgeError('Resolve project ID does not match configuration')
        if self.project_id is not None and ident!=self.project_id:
            raise BridgeError('Resolve project identity changed; restart after approval')
        self.project_id=ident
        return p

    def info(self):
        p=self.project()
        t=api(p,'GetCurrentTimeline')
        return {'version':str(api(self.connect(),'GetVersionString')),'project':api(p,'GetName'),
                'project_id':self.project_id,'timelines':int(api(p,'GetTimelineCount')),
                'current_timeline':uid(t) if t else None}

    def create_project(self,name):
        if self.cfg.get('allow_create_project') is not True or name!=self.cfg.get('project_name'):
            raise BridgeError('Project creation is not approved for this name')
        if self.project_id is not None:
            raise BridgeError('A project is already locked to this session')
        p=checked(api(self.manager(),'CreateProject',name),'project creation')
        self.project_id=uid(p)
        return {'name':api(p,'GetName'),'id':self.project_id}

    def save(self):
        self.project()
        checked(api(self.manager(),'SaveProject'),'project save')
        return {'saved':True}

    def timelines(self):
        p=self.project()
        count=int(api(p,'GetTimelineCount'))
        if count>500:
            raise BridgeError('Timeline count exceeds 500; select a smaller project')
        current=api(p,'GetCurrentTimeline')
        active=uid(current) if current else None
        out=[]
        for i in range(1,count+1):
            t=api(p,'GetTimelineByIndex',i)
            if t:
                ident=uid(t)
                out.append({'id':ident,'name':api(t,'GetName'),'active':active==ident})
        return out

    def timeline(self,ident,active=False):
        p=self.project()
        if active:
            t=api(p,'GetCurrentTimeline')
            if not t or uid(t)!=ident:
                raise BridgeError('Selected Resolve timeline changed')
            return p,t
        count=int(api(p,'GetTimelineCount'))
        if count>500:
            raise BridgeError('Timeline count exceeds 500')
        for i in range(1,count+1):
            t=api(p,'GetTimelineByIndex',i)
            if t and uid(t)==ident:
                return p,t
        raise BridgeError('Timeline no longer exists')

    def create_timeline(self,name):
        p=self.project()
        pool=checked(api(p,'GetMediaPool'),'media pool')
        t=checked(api(pool,'CreateEmptyTimeline',name),'timeline creation')
        return {'id':uid(t),'name':api(t,'GetName')}

    def select_timeline(self,timeline_id):
        p,t=self.timeline(timeline_id)
        checked(api(p,'SetCurrentTimeline',t),'timeline selection')
        if uid(checked(api(p,'GetCurrentTimeline'),'current timeline'))!=timeline_id:
            raise BridgeError('Resolve did not select the requested timeline')
        return {'selected':timeline_id}

    def _clips(self,p):
        pool=checked(api(p,'GetMediaPool'),'media pool')
        stack=[(checked(api(pool,'GetRootFolder'),'root folder'),0)]
        clips={}
        folders=0
        while stack:
            folder,depth=stack.pop()
            folders+=1
            if folders>200 or depth>16:
                raise BridgeError('Media pool exceeds bounded folder scan')
            for c in sequence(api(folder,'GetClipList')):
                ident=uid(c,'GetMediaId')
                clips[ident]=c
                if len(clips)>500:
                    raise BridgeError('Media pool exceeds 500 clips')
            stack.extend((f,depth+1) for f in sequence(api(folder,'GetSubFolderList')))
        return pool,clips

    def media(self):
        _,clips=self._clips(self.project())
        return [{'id':k,'name':api(v,'GetName')} for k,v in clips.items()]

    def import_media(self,paths):
        p=self.project()
        files=[]
        for path in paths:
            f=within(self.workspace,path)
            if not f.is_file():
                raise BridgeError('Media imports require regular files in the approved workspace')
            files.append(str(f))
        pool=checked(api(p,'GetMediaPool'),'media pool')
        imported=sequence(api(pool,'ImportMedia',files))
        if not imported:
            raise BridgeError('Resolve imported no media')
        # One input can expand to multiple clips; do not claim every import succeeded.
        return {'requested':len(files),'returned_clips':[{'id':uid(c,'GetMediaId'),'name':api(c,'GetName')} for c in imported]}

    def append(self,timeline_id,clip_ids):
        p,t=self.timeline(timeline_id,active=True)
        pool,clips=self._clips(p)
        if any(c not in clips for c in clip_ids):
            raise BridgeError('Media pool clip not found')
        # Re-check active timeline after catalog lookup.
        self.timeline(timeline_id,active=True)
        items=sequence(api(pool,'AppendToTimeline',[clips[c] for c in clip_ids]))
        if not items:
            raise BridgeError('Resolve appended no timeline items')
        return {'requested':len(clip_ids),'appended_items':len(items),'timeline_id':timeline_id}

    def items(self,timeline_id):
        _,t=self.timeline(timeline_id)
        out=[]
        for typ in ('video','audio','subtitle'):
            count=int(api(t,'GetTrackCount',typ))
            if count>100:
                raise BridgeError('Too many timeline tracks')
            for i in range(1,count+1):
                items=sequence(api(t,'GetItemListInTrack',typ,i))
                if len(out)+len(items)>500:
                    raise BridgeError('Timeline exceeds 500 item inspection limit')
                for item in items:
                    out.append({'track_type':typ,'track':i,'name':api(item,'GetName'),
                                'start':api(item,'GetStart'),'end':api(item,'GetEnd'),'duration':api(item,'GetDuration')})
        return out

    def tracks(self,timeline_id):
        _,t=self.timeline(timeline_id)
        out=[]
        for typ in ('video','audio','subtitle'):
            count=int(api(t,'GetTrackCount',typ))
            if not 0<=count<=100:
                raise BridgeError('Invalid or excessive timeline track count')
            for index in range(1,count+1):
                out.append(self._track_info(t,typ,index))
        return out

    def _track_info(self,t,track_type,index):
        return {'type':track_type,'index':index,'name':str(api(t,'GetTrackName',track_type,index)),
                'enabled':bool(api(t,'GetIsTrackEnabled',track_type,index)),
                'locked':bool(api(t,'GetIsTrackLocked',track_type,index))}

    def add_track(self,timeline_id,track_type,audio_type='stereo'):
        _,t=self.timeline(timeline_id,active=True)
        before=int(api(t,'GetTrackCount',track_type))
        if not 0<=before<100:
            raise BridgeError('Timeline track limit reached')
        args=(track_type,audio_type) if track_type=='audio' else (track_type,)
        checked(api(t,'AddTrack',*args),'track creation')
        if int(api(t,'GetTrackCount',track_type))!=before+1:
            raise BridgeError('Track count changed unexpectedly; inspect timeline')
        return self._track_info(t,track_type,before+1)

    def _track(self,timeline_id,track_type,index):
        _,t=self.timeline(timeline_id,active=True)
        count=int(api(t,'GetTrackCount',track_type))
        if not 1<=index<=count<=100:
            raise BridgeError('Invalid track index')
        return t

    def rename_track(self,timeline_id,track_type,index,name):
        t=self._track(timeline_id,track_type,index)
        checked(api(t,'SetTrackName',track_type,index,name),'track rename')
        info=self._track_info(t,track_type,index)
        if info['name']!=name:
            raise BridgeError('Resolve did not apply track name')
        return info

    def enable_track(self,timeline_id,track_type,index,enabled):
        t=self._track(timeline_id,track_type,index)
        checked(api(t,'SetTrackEnable',track_type,index,enabled),'track enable state')
        info=self._track_info(t,track_type,index)
        if info['enabled']!=enabled:
            raise BridgeError('Resolve did not apply track enable state')
        return info

    def lock_track(self,timeline_id,track_type,index,locked):
        t=self._track(timeline_id,track_type,index)
        checked(api(t,'SetTrackLock',track_type,index,locked),'track lock state')
        info=self._track_info(t,track_type,index)
        if info['locked']!=locked:
            raise BridgeError('Resolve did not apply track lock state')
        return info

    def playhead(self,timeline_id):
        _,t=self.timeline(timeline_id,active=True)
        return {'timecode':str(checked(api(t,'GetCurrentTimecode'),'playhead timecode'))}

    def seek(self,timeline_id,timecode):
        if not re.fullmatch(r'[0-9]{2}:[0-5][0-9]:[0-5][0-9][:;][0-9]{2}',timecode):
            raise BridgeError('Use HH:MM:SS:FF or drop-frame HH:MM:SS;FF')
        _,t=self.timeline(timeline_id,active=True)
        checked(api(t,'SetCurrentTimecode',timecode),'playhead seek')
        return {'requested':timecode,**self.playhead(timeline_id)}

    def subtitles(self,timeline_id):
        _,t=self.timeline(timeline_id,active=True)
        checked(api(t,'CreateSubtitlesFromAudio'),'subtitle generation')
        return {'accepted':True,'timeline_id':timeline_id}

    def insert_title(self,timeline_id,title_name):
        _,t=self.timeline(timeline_id,active=True)
        item=checked(api(t,'InsertFusionTitleIntoTimeline',title_name),'Fusion title insertion')
        return {'id':uid(item),'name':str(api(item,'GetName'))}

    def markers(self,timeline_id):
        _,t=self.timeline(timeline_id)
        markers=api(t,'GetMarkers') or {}
        if not isinstance(markers,dict) or len(markers)>500:
            raise BridgeError('Invalid or oversized marker catalog')
        return [{'frame':frame,**{k:v for k,v in props.items() if k in ('name','color','note','duration')}}
                for frame,props in markers.items() if isinstance(props,dict)]

    def add_marker(self,timeline_id,frame,name,color='Blue',note=''):
        _,t=self.timeline(timeline_id,active=True)
        duration=int(api(t,'GetEndFrame'))-int(api(t,'GetStartFrame'))
        if not 0<=frame<duration:
            raise BridgeError('Marker outside timeline duration')
        checked(api(t,'AddMarker',frame,color,name,note,1),'marker creation')
        return {'frame':frame,'name':name}

    def page(self,page):
        self.project()
        checked(api(self.connect(),'OpenPage',page),'page switch')
        return {'page':page}

    def presets(self):
        p=self.project()
        values=sequence(api(p,'GetRenderPresetList'))
        return [str(x) for x in values[:200]]

    def queue_render(self,timeline_id,preset,filename):
        p,_=self.timeline(timeline_id,active=True)
        if preset not in self.presets():
            raise BridgeError('Render preset not found in installed Resolve')
        if filename in ('.','..') or not filename or any(c in filename for c in '/\\:\x00'):
            raise BridgeError('Invalid render filename')
        folder=self.cfg.get('render_dir')
        if not folder:
            raise BridgeError('Render output directory is not approved')
        root=within(self.workspace,folder)
        if not root.is_dir():
            raise BridgeError('Render output path must be an existing directory')
        # Unique output directory avoids overwriting existing user exports.
        dest=root/('codez-'+uuid4().hex)
        dest.mkdir(mode=0o700)
        try:
            self.timeline(timeline_id,active=True)
            checked(api(p,'LoadRenderPreset',preset),'render preset')
            checked(api(p,'SetRenderSettings',{'TargetDir':str(dest),'CustomName':filename,'SelectAllFrames':True}),'render settings')
            job=checked(api(p,'AddRenderJob'),'render job creation')
            if not isinstance(job,str):
                raise BridgeError('Unsupported render job identifier format')
        except Exception:
            if not any(dest.iterdir()):
                dest.rmdir()
            raise
        self.jobs[job]=self.project_id
        return {'job_id':job,'directory':str(dest.relative_to(self.workspace))}

    def _job(self,job_id):
        p=self.project()
        if self.jobs.get(job_id)!=self.project_id:
            raise BridgeError('Only render jobs queued in this approved session are controllable')
        return p

    def start_render(self,job_id):
        p=self._job(job_id)
        if api(p,'IsRenderingInProgress'):
            raise BridgeError('Resolve is already rendering another job')
        checked(api(p,'StartRendering',[job_id]),'render start')
        return {'started':job_id}

    def render_status(self,job_id):
        p=self._job(job_id)
        status=api(p,'GetRenderJobStatus',job_id)
        if not isinstance(status,dict):
            raise BridgeError('Render status unavailable')
        return {'job_id':job_id,'status':str(status.get('JobStatus','unknown')),
                'completion':status.get('CompletionPercentage')}


def registry(cfg,workspace,app=None):
    r=Resolve(cfg,workspace,app)
    ident=string(128)
    tl={'timeline_id':ident}
    track={**tl,'track_type':string(16,enum=['video','audio','subtitle']),'index':integer(1,100)}
    clips={'type':'array','items':ident,'minItems':1,'maxItems':50}
    paths={'type':'array','items':string(4096),'minItems':1,'maxItems':50}
    tools=[
        Tool('project_info','Read approved project and Resolve version.',schema(),r.info,True),
        Tool('create_project','Create exactly the project preapproved in configuration.',schema({'name':string(128)},['name']),r.create_project),
        Tool('save_project','Save the approved project.',schema(),r.save),
        Tool('timelines','List timelines in the approved project.',schema(),r.timelines,True),
        Tool('create_timeline','Create an empty timeline in the approved project.',schema({'name':string(128)},['name']),r.create_timeline),
        Tool('select_timeline','Select a timeline by stable identifier.',schema(tl,['timeline_id']),r.select_timeline),
        Tool('media','List bounded media pool clip IDs and names.',schema(),r.media,True),
        Tool('import_media','Import only existing approved workspace media files.',schema({'paths':paths},['paths']),r.import_media),
        Tool('append','Append selected media IDs to the approved active timeline.',schema({**tl,'clip_ids':clips},['timeline_id','clip_ids']),r.append),
        Tool('items','Read timeline track items and frame positions.',schema(tl,['timeline_id']),r.items,True),
        Tool('tracks','List track names, enabled and locked state.',schema(tl,['timeline_id']),r.tracks,True),
        Tool('add_track','Add a video, audio or subtitle track to the active timeline.',schema({**tl,'track_type':string(16,enum=['video','audio','subtitle']),'audio_type':string(8,enum=['mono','stereo'])},['timeline_id','track_type']),r.add_track),
        Tool('rename_track','Rename a track and verify its name.',schema({**track,'name':string(128)},(*track,'name')),r.rename_track),
        Tool('enable_track','Enable or disable a track and verify its state.',schema({**track,'enabled':{'type':'boolean'}},(*track,'enabled')),r.enable_track),
        Tool('lock_track','Lock or unlock an active timeline track.',schema({**track,'locked':{'type':'boolean'}},(*track,'locked')),r.lock_track),
        Tool('playhead','Read active timeline timecode.',schema(tl,['timeline_id']),r.playhead,True),
        Tool('seek','Move active timeline playhead to a supplied timecode.',schema({**tl,'timecode':string(11)},['timeline_id','timecode']),r.seek),
        Tool('subtitles','Request Resolve subtitle generation from audio using installed defaults.',schema(tl,['timeline_id']),r.subtitles),
        Tool('insert_title','Insert an installed Fusion title by name at the playhead.',schema({**tl,'title_name':string(128)},['timeline_id','title_name']),r.insert_title),
        Tool('markers','Read timeline markers.',schema(tl,['timeline_id']),r.markers,True),
        Tool('add_marker','Add a one-frame marker to the active timeline.',schema({**tl,'frame':integer(0,2**31-1),'name':string(256),'color':string(32,enum=['Blue','Cyan','Green','Yellow','Red','Pink','Purple','Fuchsia','Rose','Lavender','Sky','Mint','Lemon','Sand','Cocoa','Cream']),'note':{'type':'string','maxLength':2000}},['timeline_id','frame','name']),r.add_marker),
        Tool('page','Switch to a standard Resolve page.',schema({'page':string(16,enum=['media','cut','edit','fusion','color','fairlight','deliver'])},['page']),r.page),
        Tool('render_presets','List installed render presets.',schema(),r.presets,True),
        Tool('queue_render','Queue current timeline into a new approved output directory.',schema({**tl,'preset':string(128),'filename':string(128)},['timeline_id','preset','filename']),r.queue_render),
        Tool('start_render','Start a render job created in this session only.',schema({'job_id':ident},['job_id']),r.start_render),
        Tool('render_status','Read status of a render job queued in this session.',schema({'job_id':ident},['job_id']),r.render_status,True),
    ]
    return Registry(tools)
