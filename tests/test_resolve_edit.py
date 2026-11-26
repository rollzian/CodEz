import tempfile,unittest
from test_resolve import App,Timeline,Pool
from studio_bridge.resolve import Resolve,registry
from studio_bridge.protocol import BridgeError

class EditTimeline(Timeline):
    def __init__(self,name,ident):
        super().__init__(name,ident);self.tracks={'video':[],'audio':[],'subtitle':[]};self.tc='01:00:00:00';self.captions=0
    def GetTrackCount(self,typ):return len(self.tracks[typ])
    def AddTrack(self,typ,*args):
        self.tracks[typ].append({'name':typ,'enabled':True,'locked':False});return True
    def GetTrackName(self,t,i):return self.tracks[t][i-1]['name']
    def GetIsTrackEnabled(self,t,i):return self.tracks[t][i-1]['enabled']
    def GetIsTrackLocked(self,t,i):return self.tracks[t][i-1]['locked']
    def SetTrackName(self,t,i,name):self.tracks[t][i-1]['name']=name;return True
    def SetTrackEnable(self,t,i,enabled):self.tracks[t][i-1]['enabled']=enabled;return True
    def SetTrackLock(self,t,i,locked):self.tracks[t][i-1]['locked']=locked;return True
    def GetCurrentTimecode(self):return self.tc
    def SetCurrentTimecode(self,tc):self.tc=tc;return True
    def CreateSubtitlesFromAudio(self):self.captions+=1;return True
    def InsertFusionTitleIntoTimeline(self,name):return Timeline(name,'title-id')

class ResolveEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=App();self.t=EditTimeline('Edit','timeline-a');self.app.p.timelines=[self.t];self.app.p.current=self.t
        self.cfg={'project_name':'Approved'}
        self.r=Resolve(self.cfg,self.tmp.name,self.app)
    def test_track_mutations_and_readback(self):
        self.assertEqual(self.r.add_track('timeline-a','video')['index'],1)
        self.assertEqual(self.r.add_track('timeline-a','audio','mono')['type'],'audio')
        self.assertEqual(self.r.rename_track('timeline-a','video',1,'Main')['name'],'Main')
        self.assertFalse(self.r.enable_track('timeline-a','video',1,False)['enabled'])
        self.assertTrue(self.r.lock_track('timeline-a','audio',1,True)['locked'])
        self.assertEqual(self.r.tracks('timeline-a'),[{'type':'video','index':1,'name':'Main','enabled':False,'locked':False},{'type':'audio','index':1,'name':'audio','enabled':True,'locked':True}])
        with self.assertRaises(BridgeError):self.r.rename_track('timeline-a','video',2,'Missing')
    def test_timecode_subtitles_and_title(self):
        self.assertEqual(self.r.seek('timeline-a','01:00:02:12')['timecode'],'01:00:02:12')
        with self.assertRaises(BridgeError):self.r.seek('timeline-a','invalid')
        self.assertEqual(self.t.tc,'01:00:02:12')
        self.assertTrue(self.r.subtitles('timeline-a')['accepted']);self.assertEqual(self.t.captions,1)
        self.assertEqual(self.r.insert_title('timeline-a','Text+'),{'id':'title-id','name':'Text+'})
        self.app.p.current=EditTimeline('Other','other')
        with self.assertRaises(BridgeError):self.r.subtitles('timeline-a')
        self.assertEqual(self.t.captions,1)
    def test_tool_schema_blocks_unknown_track_type(self):
        r=registry(self.cfg,self.tmp.name,self.app)
        with self.assertRaises(BridgeError):r.call('add_track',{'timeline_id':'timeline-a','track_type':'invalid'})
        self.assertEqual(self.t.tracks,{'video':[],'audio':[],'subtitle':[]})
