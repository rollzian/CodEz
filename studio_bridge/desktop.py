import io
import os
import time
from dataclasses import dataclass
from uuid import uuid4
from .protocol import BridgeError, Tool, Registry, schema, string, integer, image_result

MAX_PIXELS = 16_777_216


@dataclass(frozen=True)
class Frame:
    ident: str
    geometry: tuple
    width: int
    height: int
    captured: float

    def point(self, x, y):
        if not 0 <= x < self.width or not 0 <= y < self.height:
            raise BridgeError('Point outside captured window')
        gx, gy, w, h = self.geometry
        return min(w-1, x*w//self.width), min(h-1,y*h//self.height)


class X11:
    def __init__(self, cfg):
        # XWayland does not provide unrestricted Wayland capture/input; fail closed.
        if os.environ.get('XDG_SESSION_TYPE','').lower() == 'wayland' or os.environ.get('WAYLAND_DISPLAY'):
            raise BridgeError('Use the XDG portal backend for Wayland')
        if not os.environ.get('DISPLAY'):
            raise BridgeError('No X11 DISPLAY configured')
        try:
            from Xlib import display, X, XK
            from Xlib.ext import xtest
            from PIL import Image
        except ImportError as e:
            raise BridgeError('Install python-xlib and Pillow for X11 desktop control') from e
        self.X, self.XK, self.xtest, self.Image = X,XK,xtest,Image
        try:
            self.d = display.Display()
        except Exception as e:
            raise BridgeError('Unable to open the authorized X11 display') from e
        self.root = self.d.screen().root
        self.cfg = cfg
        self.ident = None
        self._identity = None
        try:
            val = cfg.get('window_id')
            if val is not None:
                if isinstance(val,str):
                    self.ident = int(val,0)
                elif type(val) is int:
                    self.ident = val
                else:
                    raise ValueError('window id')
                if not 1 <= self.ident < 2**32 or self.ident == self.root.id:
                    raise ValueError('window id')
            if not self.d.has_extension('XTEST'):
                raise BridgeError('X11 XTEST extension unavailable')
        except ValueError as e:
            self.close()
            raise BridgeError('Invalid target X11 window id') from e
        except Exception:
            self.close()
            raise

    def atom(self, name):
        return self.d.intern_atom(name,only_if_exists=True)

    def prop(self, w, name):
        atom = self.atom(name)
        if not atom:
            return None
        p = w.get_full_property(atom,self.X.AnyPropertyType)
        return p.value if p else None

    def title(self,w):
        t = self.prop(w,'_NET_WM_NAME')
        if isinstance(t,bytes):
            return t.decode('utf8',errors='replace')[:256]
        name = w.get_wm_name()
        return str(name or '')[:256]

    def windows(self):
        ids = self.prop(self.root,'_NET_CLIENT_LIST_STACKING')
        if ids is None:
            ids = [w.id for w in self.root.query_tree().children]
        out = []
        for ident in list(ids)[-200:]:
            try:
                w = self.d.create_resource_object('window',int(ident))
                if w.get_attributes().map_state != self.X.IsViewable:
                    continue
                title = self.title(w)
                if title:
                    out.append({'id':hex(w.id),'title':title})
            except Exception:
                # Windows can disappear during enumeration.
                continue
        return out

    def _ancestor(self, w):
        for _ in range(32):
            parent = w.query_tree().parent
            if parent.id == self.root.id:
                return w.id
            if parent.id == w.id:
                break
            w = parent
        raise BridgeError('Cannot determine target window ancestry')

    def target(self, require_focus=True):
        if self.ident is None:
            raise BridgeError('Select a window_id in the local configuration first')
        try:
            w = self.d.create_resource_object('window',self.ident)
            if w.get_attributes().map_state != self.X.IsViewable:
                raise BridgeError('Target window is not visible')
            title = self.title(w)
            if self.cfg.get('title_contains') and self.cfg['title_contains'] not in title:
                raise BridgeError('Target title does not match the approved window')
            pid = self.prop(w,'_NET_WM_PID')
            identity = (tuple(pid) if pid is not None else (),w.get_wm_class())
            if self._identity is not None and identity != self._identity:
                raise BridgeError('Target window identity changed; restart after approval')
            self._identity = identity
            if require_focus:
                active = self.prop(self.root,'_NET_ACTIVE_WINDOW')
                if active is not None and len(active) and int(active[0]) not in (0,self.ident):
                    raise BridgeError('Approved window is not active')
                focus = self.d.get_input_focus().focus
                # Input focus may be a child of the approved window.
                for _ in range(32):
                    if getattr(focus,'id',None) == self.ident:
                        break
                    if not hasattr(focus,'query_tree') or focus.id == self.root.id:
                        raise BridgeError('Input focus is outside the approved window')
                    focus = focus.query_tree().parent
                else:
                    raise BridgeError('Cannot verify input focus')
            return w
        except BridgeError:
            raise
        except Exception as e:
            raise BridgeError('Approved window is unavailable') from e

    def geometry(self,w):
        g = w.get_geometry()
        coords = self.root.translate_coords(w,0,0)
        x,y = coords.x, coords.y
        sw,sh = self.root.get_geometry().width,self.root.get_geometry().height
        if x<0 or y<0 or x+g.width>sw or y+g.height>sh or g.width*g.height>MAX_PIXELS or g.width<1 or g.height<1:
            raise BridgeError('Target must be fully on-screen and under the capture size limit')
        return x,y,g.width,g.height

    def capture(self):
        w = self.target()
        geo = self.geometry(w)
        _,_,width,height = geo
        reply = w.get_image(0,0,width,height,self.X.ZPixmap,0xffffffff)
        if reply is None:
            raise BridgeError('X11 window capture failed')
        fmt = next((f for f in self.d.display.info.pixmap_formats if f.depth==reply.depth),None)
        # The common little-endian 24-bit TrueColor X11 layout. Refuse unusual visuals rather than corrupt coordinates/colors.
        if fmt is None or fmt.bits_per_pixel!=32 or self.d.display.info.image_byte_order!=self.X.LSBFirst:
            raise BridgeError('Unsupported X11 pixel format')
        visual_id = reply.visual
        visuals = [v for d in self.d.screen().allowed_depths for v in d.visuals if v.visual_id==visual_id]
        if not visuals or (visuals[0].red_mask,visuals[0].green_mask,visuals[0].blue_mask)!=(0xff0000,0xff00,0xff):
            raise BridgeError('Unsupported X11 color masks')
        stride = ((width*fmt.bits_per_pixel + fmt.scanline_pad-1)//fmt.scanline_pad)*(fmt.scanline_pad//8)
        image = self.Image.frombytes('RGB',(width,height),reply.data,'raw','BGRX',stride,1)
        return image,geo

    def focus(self):
        w = self.target(False)
        from Xlib.protocol import event
        if self.atom('_NET_ACTIVE_WINDOW'):
            ev = event.ClientMessage(window=w,client_type=self.atom('_NET_ACTIVE_WINDOW'),data=(32,[2,0,0,0,0]))
            self.root.send_event(ev,event_mask=self.X.SubstructureRedirectMask|self.X.SubstructureNotifyMask)
        else:
            w.set_input_focus(self.X.RevertToParent,self.X.CurrentTime)
        self.d.sync()
        return {'requested':True,'window':hex(w.id)}

    def _pointer(self,w,x,y):
        geo = self.geometry(w)
        gx,gy,width,height = geo
        if not 0<=x<width or not 0<=y<height:
            raise BridgeError('Point outside target window')
        self.xtest.fake_input(self.d,self.X.MotionNotify,x=gx+x,y=gy+y,root=self.root.id)
        self.d.sync()
        pointer = self.root.query_pointer()
        if getattr(pointer.child,'id',0)!=self._ancestor(w):
            raise BridgeError('Another window overlaps the target point')
        self.target()

    def click(self,w,x,y,button,count):
        for _ in range(count):
            self._pointer(w,x,y)
            self.xtest.fake_input(self.d,self.X.ButtonPress,button)
            self.xtest.fake_input(self.d,self.X.ButtonRelease,button)
        self.d.sync()

    def move(self,w,x,y):
        self._pointer(w,x,y)

    def drag(self,w,x,y,to_x,to_y):
        self._pointer(w,x,y)
        self.xtest.fake_input(self.d,self.X.ButtonPress,1)
        try:
            for i in range(1,9):
                self._pointer(w,x+(to_x-x)*i//8,y+(to_y-y)*i//8)
        finally:
            self.xtest.fake_input(self.d,self.X.ButtonRelease,1)
            self.d.sync()

    def scroll(self,w,x,y,steps):
        self._pointer(w,x,y)
        b = 4 if steps>0 else 5
        for _ in range(abs(steps)):
            self.xtest.fake_input(self.d,self.X.ButtonPress,b)
            self.xtest.fake_input(self.d,self.X.ButtonRelease,b)
        self.d.sync()

    def _mapping(self,sym):
        # X keyboard map column 0/1 correspond to base/Shift. Never rewrite the system keymap.
        options = self.d.keysym_to_keycodes(sym)
        for code,index in options:
            if code and index in (0,1):
                return code,index==1
        raise BridgeError('Key is not available in the current keyboard layout')

    def _tap(self,code,shift=False,ctrl=False):
        modifiers=[]
        try:
            for on,name in ((ctrl,'Control_L'),(shift,'Shift_L')):
                if on:
                    m = self.d.keysym_to_keycode(self.XK.string_to_keysym(name))
                    if not m:
                        raise BridgeError('Modifier unavailable')
                    self.xtest.fake_input(self.d,self.X.KeyPress,m)
                    modifiers.append(m)
            self.xtest.fake_input(self.d,self.X.KeyPress,code)
            self.xtest.fake_input(self.d,self.X.KeyRelease,code)
        finally:
            for m in reversed(modifiers):
                self.xtest.fake_input(self.d,self.X.KeyRelease,m)
            self.d.sync()

    def type_text(self,text):
        # Validate the entire string before the first event. Unicode layout support is not claimed.
        if any(not (32<=ord(c)<=126 or c in '\n\t') for c in text):
            raise BridgeError('X11 text entry currently supports ASCII, tab and newline')
        seq = [self._mapping(self.XK.string_to_keysym('Return' if c=='\n' else 'Tab') if c in '\n\t' else ord(c)) for c in text]
        for code,shift in seq:
            self.target()
            self._tap(code,shift)

    def key(self,key,ctrl,shift):
        aliases = {'Enter':'Return','Escape':'Escape','Backspace':'BackSpace','Space':'space'}
        key = aliases.get(key,key)
        if len(key)==1 and key.isascii() and key.isalnum():
            sym = ord(key.lower())
        else:
            sym = self.XK.string_to_keysym(key)
        if not sym:
            raise BridgeError('Unknown key')
        code, needs_shift = self._mapping(sym)
        self.target()
        self._tap(code,shift or needs_shift,ctrl)

    def close(self):
        self.d.close()


class Desktop:
    def __init__(self,cfg,backend=None):
        self.cfg=cfg
        self.backend=backend
        self.frame=None

    def driver(self):
        if self.backend is None:
            import sys
            if sys.platform.startswith('linux'):
                if is_wayland():
                    from .desktop_portal import Wayland
                    self.backend=Wayland(self.cfg)
                else:
                    self.backend=X11(self.cfg)
            elif sys.platform=='win32':
                from .desktop_win import Windows
                self.backend=Windows(self.cfg)
            else:
                raise BridgeError('Native desktop backend is implemented for Linux X11/Wayland and Windows')
        return self.backend

    def windows(self):
        return self.driver().windows()

    def focus(self):
        self.frame=None
        return self.driver().focus()

    def screenshot(self):
        image,geo=self.driver().capture()
        image.thumbnail((1600,1000))
        buf=io.BytesIO()
        image.save(buf,format='JPEG',quality=85)
        self.frame=Frame(uuid4().hex,geo,image.width,image.height,time.monotonic())
        return image_result(buf.getvalue(),'image/jpeg',{'frame_id':self.frame.ident,'width':image.width,'height':image.height,'source_width':geo[2],'source_height':geo[3],'expires_seconds':120})

    def _check(self,frame_id):
        f=self.frame
        if f is None or f.ident!=frame_id or time.monotonic()-f.captured>120:
            raise BridgeError('Frame missing, stale or already used; capture again')
        self.frame=None  # consume the frame even if the target check fails
        d=self.driver()
        w=d.target()
        if hasattr(d,'check_frame'):
            d.check_frame()
        if d.geometry(w)!=f.geometry:
            self.frame=None
            raise BridgeError('Window moved or resized; capture again')
        return d,w,f

    def click(self,frame_id,x,y,button='left',count=1):
        d,w,f=self._check(frame_id)
        d.click(w,*f.point(x,y),{'left':1,'middle':2,'right':3}[button],count)
        return {'clicked':True}

    def move(self,frame_id,x,y):
        d,w,f=self._check(frame_id)
        d.move(w,*f.point(x,y))
        return {'moved':True}

    def drag(self,frame_id,x,y,to_x,to_y):
        d,w,f=self._check(frame_id)
        d.drag(w,*f.point(x,y),*f.point(to_x,to_y))
        return {'dragged':True}

    def scroll(self,frame_id,x,y,steps):
        d,w,f=self._check(frame_id)
        d.scroll(w,*f.point(x,y),steps)
        return {'scrolled':steps}

    def type_text(self,frame_id,text):
        d,_,_=self._check(frame_id)
        d.type_text(text)
        return {'typed_characters':len(text)}

    def key(self,frame_id,key,ctrl=False,shift=False):
        d,_,_=self._check(frame_id)
        d.key(key,ctrl,shift)
        return {'pressed':key}

    def close(self):
        if self.backend:
            self.backend.close()
            self.backend=None
        self.frame=None


KEYS=['Enter','Escape','Tab','Backspace','Delete','Home','End','Left','Right','Up','Down','Page_Up','Page_Down','Space']+list('abcdefghijklmnopqrstuvwxyz0123456789')+[f'F{i}' for i in range(1,13)]


def is_wayland():
    import sys
    return sys.platform.startswith('linux') and (os.environ.get('XDG_SESSION_TYPE','').lower()=='wayland' or bool(os.environ.get('WAYLAND_DISPLAY')))


def registry(cfg, backend=None, mode='read-only'):
    portal_mode=is_wayland() and backend is None
    if portal_mode and mode!='approved':
        cfg={**cfg,'allow_portal_input':False,'allow_global_keyboard':False}
    d=Desktop(cfg,backend)
    frame={'frame_id':string(32)}
    point={**frame,'x':integer(0,1599),'y':integer(0,999)}
    xy=('frame_id','x','y')
    tools=[
        Tool('windows','List visible windows to help the operator select a target.',schema(),d.windows,True),
        Tool('focus','Request focus for the operator-approved window only.',schema(),d.focus),
        Tool('screenshot','Capture only the approved active window; returns image and one-use frame_id.',schema(),d.screenshot,True),
        Tool('click','Click within a fresh approved window screenshot.',schema({**point,'button':string(8,enum=['left','middle','right']),'count':integer(1,2)},xy),d.click),
        Tool('move','Move pointer within the approved window.',schema(point,xy),d.move),
        Tool('drag','Drag inside the approved window only.',schema({**point,'to_x':integer(0,1599),'to_y':integer(0,999)},(*xy,'to_x','to_y')),d.drag),
        Tool('scroll','Scroll at a point within the approved window.',schema({**point,'steps':integer(-10,10)},(*xy,'steps')),d.scroll),
        Tool('type','Type text into the approved focused window (ASCII on X11, Unicode on Windows); no clipboard access.',schema({**frame,'text':string(512)},('frame_id','text')),d.type_text),
        Tool('key','Send a supported key with optional Control and Shift modifiers.',schema({**frame,'key':string(12,enum=KEYS),'ctrl':{'type':'boolean'},'shift':{'type':'boolean'}},('frame_id','key')),d.key),
    ]
    if portal_mode:
        allowed={'screenshot'}
        if cfg.get('allow_portal_input') is True:
            allowed.update(('click','move','drag','scroll'))
        if cfg.get('allow_global_keyboard') is True:
            allowed.update(('type','key'))
        tools=[t for t in tools if t.name in allowed]
        scope=cfg.get('portal_scope','window')
        tools=[Tool(t.name, 'Capture the portal-approved '+scope+'; returns image and one-use frame_id.' if t.name=='screenshot' else 'Send input via the portal to the shared desktop (not isolated to a window). '+t.description,t.input_schema,t.fn,t.read_only) for t in tools]
    r=Registry(tools)
    r.close=d.close
    return r
