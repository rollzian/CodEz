"""Contract tests with a deterministic stand-in for the installed Resolve RPC API."""
import tempfile
import unittest
from pathlib import Path
from studio_bridge.resolve import Resolve
from studio_bridge.protocol import BridgeError

class Clip:
    def __init__(self,name,ident): self.name=name;self.ident=ident
    def GetName(self):return self.name
    def GetMediaId(self):return self.ident

class Timeline:
    def __init__(self,name,ident):self.name=name;self.ident=ident;self.markers={};self.clips=[]
    def GetUniqueId(self):return self.ident
    def GetName(self):return self.name
    def GetStartFrame(self):return 1000
    def GetEndFrame(self):return 1100
    def AddMarker(self,frame,color,name,note,duration):
        self.markers[frame]={'color':color,'name':name,'note':note,'duration':duration};return True
    def GetMarkers(self):return self.markers

class Pool:
    def __init__(self,p):self.p=p;self.clips=[];self.imported=[]
    def GetRootFolder(self):return self
    def GetClipList(self):return self.clips
    def GetSubFolderList(self):return []
    def ImportMedia(self,paths):
        self.imported.extend(paths);out=[Clip(Path(x).name,f'id-{i+len(self.clips)}') for i,x in enumerate(paths)];self.clips.extend(out);return out
    def CreateEmptyTimeline(self,name):
        t=Timeline(name,'timeline-'+str(len(self.p.timelines)));self.p.timelines.append(t);self.p.current=t;return t
    def AppendToTimeline(self,clips):self.p.current.clips.extend(clips);return clips

class Project:
    def __init__(self):
        self.name='Approved';self.ident='project-1';self.timelines=[];self.current=None;self.pool=Pool(self);self.jobs=[];self.rendered=[];self.settings=None
    def GetUniqueId(self):return self.ident
    def GetName(self):return self.name
    def GetMediaPool(self):return self.pool
    def GetCurrentTimeline(self):return self.current
    def GetTimelineCount(self):return len(self.timelines)
    def GetTimelineByIndex(self,i):return self.timelines[i-1]
    def SetCurrentTimeline(self,t):self.current=t;return True
    def GetRenderPresetList(self):return ['H264']
    def LoadRenderPreset(self,preset):return preset=='H264'
    def SetRenderSettings(self,settings):self.settings=settings;return True
    def AddRenderJob(self):self.jobs.append('job-1');return 'job-1'
    def IsRenderingInProgress(self):return False
    def StartRendering(self,jobs):self.rendered.extend(jobs);return True
    def GetRenderJobStatus(self,job):return {'JobStatus':'Complete','CompletionPercentage':100}

class App:
    def __init__(self):self.p=Project();self.saved=0
    def GetProjectManager(self):return self
    def GetCurrentProject(self):return self.p
    def GetVersionString(self):return 'test-boundary'
    def SaveProject(self):self.saved+=1;return True

class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'media.mp4').write_bytes(b'fixture');(self.root/'renders').mkdir();self.app=App();self.r=Resolve({'project_name':'Approved','render_dir':'renders'},str(self.root),self.app)
    def tearDown(self):self.tmp.cleanup()
    def test_project_timeline_import_append_mark_and_render(self):
        self.assertEqual(self.r.info()['project_id'],'project-1')
        t=self.r.create_timeline('Edit')['id'];self.assertEqual(t,'timeline-0')
        out=self.r.import_media(['media.mp4']);self.assertEqual(out['returned_clips'][0]['name'],'media.mp4')
        self.assertEqual(self.app.p.pool.imported,[str(self.root/'media.mp4')])
        self.assertEqual(self.r.append(t,['id-0'])['appended_items'],1)
        self.assertEqual(len(self.app.p.current.clips),1)
        self.r.add_marker(t,10,'Cut');self.assertEqual(self.r.markers(t)[0]['frame'],10)
        job=self.r.queue_render(t,'H264','output');self.assertEqual(job['job_id'],'job-1')
        self.assertTrue((self.root/job['directory']).is_dir());self.assertEqual(self.app.p.settings['TargetDir'],str(self.root/job['directory']))
        self.r.start_render('job-1');self.assertEqual(self.app.p.rendered,['job-1']);self.assertEqual(self.r.render_status('job-1')['completion'],100)
        self.r.save();self.assertEqual(self.app.saved,1)
    def test_reject_other_project_timeline_paths_and_jobs(self):
        t=self.r.create_timeline('A')['id'];self.r.create_timeline('B')
        with self.assertRaises(BridgeError): self.r.append(t,['id-0'])
        with self.assertRaises(BridgeError):self.r.import_media(['/etc/passwd'])
        self.assertEqual(self.app.p.pool.imported,[])
        with self.assertRaises(BridgeError):self.r.start_render('someone-else')
        self.assertEqual(self.app.p.rendered,[])
        self.app.p.ident='different-project'
        with self.assertRaises(BridgeError):self.r.save()
        self.assertEqual(self.app.saved,0)
