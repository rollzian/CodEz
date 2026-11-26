"""Wayland capture through XDG portals; input only for explicitly shared monitors."""
import io
import os
from uuid import uuid4
from .protocol import BridgeError
from .desktop import MAX_PIXELS

BUS='org.freedesktop.portal.Desktop'
PATH='/org/freedesktop/portal/desktop'
SCREEN=BUS.rsplit('.',1)[0]+'.ScreenCast'
REMOTE=BUS.rsplit('.',1)[0]+'.RemoteDesktop'
REQUEST=BUS.rsplit('.',1)[0]+'.Request'
SESSION=BUS.rsplit('.',1)[0]+'.Session'


class Portal:
    def __init__(self):
        try:
            import gi
            gi.require_version('Gst','1.0')
            from gi.repository import Gio,GLib,Gst
            from PIL import Image
        except (ImportError,ValueError) as e:
            raise BridgeError('Wayland requires PyGObject, GStreamer, PipeWire plugin and Pillow') from e
        self.Gio,self.GLib,self.Gst,self.Image=Gio,GLib,Gst,Image
        try:
            self.bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
        except GLib.Error as e:
            raise BridgeError('No accessible desktop portal session bus') from e
        self.Gst.init(None)
        self.session=None
        self.closed=False
        self.subscription=None
        self.pipeline=None
        self.fd=None
        self.sink=None

    def variant(self, signature, value):
        return self.GLib.Variant(signature,value)

    def call(self, interface, method, signature, values, path=PATH):
        try:
            return self.bus.call_sync(BUS,path,interface,method,self.variant(signature,values),None,
                                      self.Gio.DBusCallFlags.NONE,5000,None).unpack()
        except self.GLib.Error as e:
            raise BridgeError('Desktop portal rejected '+method) from e

    def request(self,interface,method,signature,values,options):
        token='codez_'+uuid4().hex
        sender=self.bus.get_unique_name().lstrip(':').replace('.','_')
        path=PATH+'/request/'+sender+'/'+token
        options={**options,'handle_token':self.variant('s',token)}
        responses=[]
        loop=self.GLib.MainLoop()
        def response(_conn,_sender,_path,_interface,_signal,params):
            responses.append(params.unpack());loop.quit()
        sub=self.bus.signal_subscribe(BUS,REQUEST,'Response',path,None,self.Gio.DBusSignalFlags.NONE,response)
        timer=None
        try:
            returned=self.call(interface,method,signature,(*values,options))
            if returned!=(path,):
                raise BridgeError('Portal returned unexpected request path')
            if not responses:
                def timeout(*_):
                    loop.quit()
                    return False
                timer=self.GLib.timeout_source_new_seconds(120)
                timer.set_callback(timeout);timer.attach(None)
                loop.run()
            if not responses:
                try:self.call(REQUEST,'Close','()',(),path)
                except BridgeError:pass
                raise BridgeError('Desktop portal consent timed out')
            status,results=responses[0]
            if status!=0 or not isinstance(results,dict):
                raise BridgeError('Desktop portal request denied or cancelled')
            return results
        finally:
            if timer:timer.destroy()
            self.bus.signal_unsubscribe(sub)

    def open(self,scope,input_devices):
        interface=REMOTE if input_devices else SCREEN
        opts={'session_handle_token':self.variant('s','codez_'+uuid4().hex)}
        result=self.request(interface,'CreateSession','(a{sv})',(),opts)
        self.session=result.get('session_handle')
        if not isinstance(self.session,str) or not self.session.startswith(PATH+'/session/'):
            raise BridgeError('Invalid desktop portal session')
        def closed(*_):self.closed=True
        self.subscription=self.bus.signal_subscribe(BUS,SESSION,'Closed',self.session,None,self.Gio.DBusSignalFlags.NONE,closed)
        if input_devices:
            self.request(REMOTE,'SelectDevices','(oa{sv})',(self.session,),{'types':self.variant('u',input_devices)})
        self.request(SCREEN,'SelectSources','(oa{sv})',(self.session,),{'types':self.variant('u',1 if scope=='monitor' else 2),'multiple':self.variant('b',False)})
        result=self.request(interface,'Start','(osa{sv})',(self.session,''),{})
        if input_devices and (type(result.get('devices')) is not int or result['devices'] & input_devices != input_devices):
            raise BridgeError('Portal did not grant requested input devices')
        streams=result.get('streams')
        if not isinstance(streams,(list,tuple)) or len(streams)!=1:
            raise BridgeError('Select exactly one source in the desktop portal')
        node,props=streams[0]
        if type(node) is not int or not 0<=node<2**32 or not isinstance(props,dict):
            raise BridgeError('Invalid PipeWire stream')
        expected=1 if scope=='monitor' else 2
        if props.get('source_type',expected)!=expected:
            raise BridgeError('Portal selected an unexpected source type')
        try:
            reply,fds=self.bus.call_with_unix_fd_list_sync(BUS,PATH,SCREEN,'OpenPipeWireRemote',self.variant('(oa{sv})',(self.session,{})),None,self.Gio.DBusCallFlags.NONE,5000,None,None)
            self.fd=fds.get(reply.unpack()[0])
            # No user-supplied strings enter the pipeline description.
            self.pipeline=self.Gst.parse_launch(f'pipewiresrc fd={self.fd} path={node} ! videoconvert ! jpegenc quality=85 ! appsink name=frames sync=false max-buffers=1 drop=true')
            self.sink=self.pipeline.get_by_name('frames')
            if self.pipeline.set_state(self.Gst.State.PLAYING)==self.Gst.StateChangeReturn.FAILURE:
                raise BridgeError('PipeWire capture pipeline failed to start')
        except self.GLib.Error as e:
            raise BridgeError('PipeWire capture unavailable; check GStreamer pipewiresrc and jpegenc') from e
        return node,props

    def check(self):
        context=self.GLib.MainContext.default()
        for _ in range(64):
            if not context.pending():break
            context.iteration(False)
        if self.closed or not self.session:
            raise BridgeError('Desktop portal session closed')

    def image(self):
        self.check()
        sample=self.sink.emit('try-pull-sample',5*self.Gst.SECOND)
        if sample is None:
            raise BridgeError('No fresh PipeWire frame')
        buffer=sample.get_buffer()
        if buffer.get_size()>12*1024*1024:
            raise BridgeError('PipeWire frame exceeds size limit')
        with self.Image.open(io.BytesIO(buffer.extract_dup(0,buffer.get_size()))) as im:
            if im.width*im.height>MAX_PIXELS:
                raise BridgeError('PipeWire frame exceeds pixel limit')
            image=im.convert('RGB')
        self.check()
        return image

    def input(self,method,signature,values):
        self.check()
        self.call(REMOTE,method,'(oa{sv}'+signature+')',(self.session,{},*values))

    def close(self):
        try:
            if self.pipeline:
                self.pipeline.set_state(self.Gst.State.NULL)
        finally:
            if self.fd is not None:
                # pipewiresrc duplicates its configured fd; release our original after NULL.
                try:os.close(self.fd)
                except OSError:pass
                self.fd=None
            if self.subscription is not None:
                self.bus.signal_unsubscribe(self.subscription);self.subscription=None
            if self.session and not self.closed:
                try:self.call(SESSION,'Close','()',(),self.session)
                except BridgeError:pass
            self.closed=True;self.session=None


class Wayland:
    def __init__(self,cfg,portal=None):
        self.scope=cfg.get('portal_scope')
        if self.scope not in ('window','monitor'):
            raise BridgeError('Explicit portal_scope window or monitor is required on Wayland')
        self.pointer=cfg.get('allow_portal_input') is True
        self.keyboard=cfg.get('allow_global_keyboard') is True
        if (self.pointer or self.keyboard) and self.scope!='monitor':
            raise BridgeError('Portal input requires explicit monitor scope')
        if self.keyboard and not self.pointer:
            raise BridgeError('Global keyboard permission requires portal input permission')
        self.portal=portal or Portal()
        try:
            self.node,self.props=self.portal.open(self.scope,(2 if self.pointer else 0)|(1 if self.keyboard else 0))
            self.logical=self.props.get('logical_size',self.props.get('size'))
            if self.pointer and (not isinstance(self.logical,(list,tuple)) or len(self.logical)!=2 or any(type(x) is not int or not 1<=x<=16384 for x in self.logical)):
                raise BridgeError('Portal did not report valid logical monitor dimensions')
            self.last_geometry=None
        except Exception:
            self.portal.close();raise

    def target(self):
        self.portal.check()
        return self.node

    def geometry(self,node):
        self.target()
        if node!=self.node or self.last_geometry is None:
            raise BridgeError('Capture a portal frame first')
        return self.last_geometry

    def check_frame(self):
        # A stream resolution change can invalidate the coordinate mapping.
        if self.portal.image().size!=self.frame_size:
            self.close()
            raise BridgeError('Portal stream changed size; reopen the session')

    def capture(self):
        image=self.portal.image()
        width,height=self.logical if self.pointer else image.size
        self.last_geometry=(0,0,width,height)
        self.frame_size=image.size
        return image,self.last_geometry

    def _move(self,x,y):
        if not self.pointer:
            raise BridgeError('Portal pointer input is not approved')
        _,_,w,h=self.geometry(self.node)
        if not 0<=x<w or not 0<=y<h:
            raise BridgeError('Point outside shared monitor')
        self.portal.input('NotifyPointerMotionAbsolute','udd',(self.node,float(x),float(y)))

    def _button(self,button,state):
        self.portal.input('NotifyPointerButton','iu',({1:272,2:274,3:273}[button],state))

    def click(self,node,x,y,button,count):
        for _ in range(count):
            self._move(x,y)
            self._button(button,1)
            self._button(button,0)

    def move(self,node,x,y):
        self._move(x,y)

    def drag(self,node,x,y,to_x,to_y):
        self._move(x,y)
        self._button(1,1)
        try:
            self._move(to_x,to_y)
        finally:
            self._button(1,0)

    def scroll(self,node,x,y,steps):
        self._move(x,y)
        if steps:
            self.portal.input('NotifyPointerAxisDiscrete','ui',(0,-steps))

    def _key_event(self,sym,state):
        if not self.keyboard:
            raise BridgeError('Portal global keyboard is not approved')
        self.portal.input('NotifyKeyboardKeysym','iu',(sym,state))

    def _tap(self,sym,ctrl=False,shift=False):
        pressed=[]
        try:
            for enabled,key in ((ctrl,0xffe3),(shift,0xffe1),(True,sym)):
                if enabled:
                    self._key_event(key,1);pressed.append(key)
        finally:
            for key in reversed(pressed):
                self._key_event(key,0)

    def type_text(self,text):
        if any(not (32<=ord(c)<=126 or c in '\t\n') for c in text):
            raise BridgeError('Portal text entry supports ASCII, tab and newline')
        for c in text:
            self._tap({'\t':0xff09,'\n':0xff0d}.get(c,ord(c)))

    def key(self,key,ctrl,shift):
        keys={'Enter':0xff0d,'Escape':0xff1b,'Tab':0xff09,'Backspace':0xff08,'Delete':0xffff,'Home':0xff50,'End':0xff57,'Left':0xff51,'Up':0xff52,'Right':0xff53,'Down':0xff54,'Page_Up':0xff55,'Page_Down':0xff56,'Space':32}
        keys.update({f'F{i}':0xffbd+i for i in range(1,13)})
        sym=keys.get(key,ord(key) if len(key)==1 else 0)
        if not sym:raise BridgeError('Unknown portal key')
        self._tap(sym,ctrl,shift)

    def close(self):
        self.portal.close()
