"""Windows client-area capture and native SendInput. Loaded only on Windows."""
import ctypes as C
from ctypes import wintypes as W
from .protocol import BridgeError
from .desktop import MAX_PIXELS


class BITMAPINFOHEADER(C.Structure):
    _fields_=[('biSize',W.DWORD),('biWidth',W.LONG),('biHeight',W.LONG),('biPlanes',W.WORD),
              ('biBitCount',W.WORD),('biCompression',W.DWORD),('biSizeImage',W.DWORD),
              ('biXPelsPerMeter',W.LONG),('biYPelsPerMeter',W.LONG),('biClrUsed',W.DWORD),('biClrImportant',W.DWORD)]


class BITMAPINFO(C.Structure):
    _fields_=[('bmiHeader',BITMAPINFOHEADER),('bmiColors',W.DWORD*1)]


class MOUSEINPUT(C.Structure):
    _fields_=[('dx',W.LONG),('dy',W.LONG),('mouseData',W.DWORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',W.WPARAM)]


class KEYBDINPUT(C.Structure):
    _fields_=[('wVk',W.WORD),('wScan',W.WORD),('dwFlags',W.DWORD),('time',W.DWORD),('dwExtraInfo',W.WPARAM)]


class HARDWAREINPUT(C.Structure):
    _fields_=[('uMsg',W.DWORD),('wParamL',W.WORD),('wParamH',W.WORD)]


class INPUT_UNION(C.Union):
    _fields_=[('mi',MOUSEINPUT),('ki',KEYBDINPUT),('hi',HARDWAREINPUT)]


class INPUT(C.Structure):
    _fields_=[('type',W.DWORD),('u',INPUT_UNION)]


def bind(lib,name,args,restype):
    f=getattr(lib,name)
    f.argtypes=args
    f.restype=restype
    return f


class Windows:
    def __init__(self,cfg):
        from PIL import Image
        self.Image=Image
        self.u=C.WinDLL('user32',use_last_error=True)
        self.g=C.WinDLL('gdi32',use_last_error=True)
        self.cfg=cfg
        self.ident=None
        self.identity=None
        self._bind()
        try:
            self.u.SetProcessDpiAwarenessContext.argtypes=[C.c_void_p]
            self.u.SetProcessDpiAwarenessContext.restype=W.BOOL
            self.u.SetProcessDpiAwarenessContext(C.c_void_p(-4))
            current=bind(self.u,'GetThreadDpiAwarenessContext',[],C.c_void_p)()
            awareness=bind(self.u,'GetAwarenessFromDpiAwarenessContext',[C.c_void_p],C.c_int)(current)
            if awareness!=2:
                raise BridgeError('Per-monitor DPI awareness required for reliable window coordinates')
        except AttributeError as e:
            raise BridgeError('Windows 10/11 per-monitor DPI API required') from e
        raw=cfg.get('window_id')
        if raw is not None:
            try:
                if not isinstance(raw,str) and type(raw) is not int:
                    raise ValueError('invalid handle')
                self.ident=int(raw,0) if isinstance(raw,str) else raw
                if not 0<self.ident<2**(C.sizeof(C.c_void_p)*8):
                    raise ValueError('invalid handle')
            except ValueError as e:
                raise BridgeError('Invalid Windows HWND') from e

    def _bind(self):
        hwnd=W.HWND; dc=W.HDC; handle=W.HANDLE
        u=self.u;g=self.g
        self.IsWindow=bind(u,'IsWindow',[hwnd],W.BOOL)
        self.IsWindowVisible=bind(u,'IsWindowVisible',[hwnd],W.BOOL)
        self.IsIconic=bind(u,'IsIconic',[hwnd],W.BOOL)
        self.GetWindowText=bind(u,'GetWindowTextW',[hwnd,W.LPWSTR,C.c_int],C.c_int)
        self.GetClassName=bind(u,'GetClassNameW',[hwnd,W.LPWSTR,C.c_int],C.c_int)
        self.GetWindowThreadProcessId=bind(u,'GetWindowThreadProcessId',[hwnd,C.POINTER(W.DWORD)],W.DWORD)
        self.GetForegroundWindow=bind(u,'GetForegroundWindow',[],hwnd)
        self.SetForegroundWindow=bind(u,'SetForegroundWindow',[hwnd],W.BOOL)
        self.GetClientRect=bind(u,'GetClientRect',[hwnd,C.POINTER(W.RECT)],W.BOOL)
        self.ClientToScreen=bind(u,'ClientToScreen',[hwnd,C.POINTER(W.POINT)],W.BOOL)
        self.GetSystemMetrics=bind(u,'GetSystemMetrics',[C.c_int],C.c_int)
        self.WindowFromPoint=bind(u,'WindowFromPoint',[W.POINT],hwnd)
        self.GetAncestor=bind(u,'GetAncestor',[hwnd,W.UINT],hwnd)
        self.SetCursorPos=bind(u,'SetCursorPos',[C.c_int,C.c_int],W.BOOL)
        self.SendInput=bind(u,'SendInput',[W.UINT,C.POINTER(INPUT),C.c_int],W.UINT)
        self.GetDC=bind(u,'GetDC',[hwnd],dc)
        self.ReleaseDC=bind(u,'ReleaseDC',[hwnd,dc],C.c_int)
        self.PrintWindow=bind(u,'PrintWindow',[hwnd,dc,W.UINT],W.BOOL)
        self.CreateCompatibleDC=bind(g,'CreateCompatibleDC',[dc],dc)
        self.CreateCompatibleBitmap=bind(g,'CreateCompatibleBitmap',[dc,C.c_int,C.c_int],handle)
        self.SelectObject=bind(g,'SelectObject',[dc,handle],handle)
        self.DeleteObject=bind(g,'DeleteObject',[handle],W.BOOL)
        self.DeleteDC=bind(g,'DeleteDC',[dc],W.BOOL)
        self.GetDIBits=bind(g,'GetDIBits',[dc,handle,W.UINT,W.UINT,C.c_void_p,C.POINTER(BITMAPINFO),W.UINT],C.c_int)
        self.WNDENUMPROC=C.WINFUNCTYPE(W.BOOL,hwnd,W.LPARAM)
        self.EnumWindows=bind(u,'EnumWindows',[self.WNDENUMPROC,W.LPARAM],W.BOOL)

    def title(self,w):
        text=C.create_unicode_buffer(257)
        self.GetWindowText(w,text,len(text))
        return text.value

    def windows(self):
        out=[]
        @self.WNDENUMPROC
        def visit(hwnd,_):
            if len(out)>=200:
                return False
            if self.IsWindowVisible(hwnd) and not self.IsIconic(hwnd):
                title=self.title(hwnd)
                if title:
                    out.append({'id':hex(hwnd),'title':title})
            return True
        self.EnumWindows(visit,0)
        return out

    def target(self,require_focus=True):
        w=self.ident
        if w is None or not self.IsWindow(w) or not self.IsWindowVisible(w) or self.IsIconic(w) or self.GetAncestor(w,2)!=w:
            raise BridgeError('Select a visible top-level Windows window in local configuration')
        if self.cfg.get('title_contains') and self.cfg['title_contains'] not in self.title(w):
            raise BridgeError('Target title does not match the approved window')
        pid=W.DWORD();name=C.create_unicode_buffer(256)
        self.GetWindowThreadProcessId(w,C.byref(pid))
        self.GetClassName(w,name,len(name))
        current=(pid.value,name.value)
        if self.identity is not None and self.identity!=current:
            raise BridgeError('Target window identity changed; restart after approval')
        self.identity=current
        if require_focus and self.GetForegroundWindow()!=w:
            raise BridgeError('Approved window is not foreground')
        return w

    def geometry(self,w):
        rect=W.RECT();point=W.POINT(0,0)
        if not self.GetClientRect(w,C.byref(rect)) or not self.ClientToScreen(w,C.byref(point)):
            raise BridgeError('Cannot read client-area geometry')
        x,y=point.x,point.y; width=rect.right-rect.left;height=rect.bottom-rect.top
        sx,sy,sw,sh=(self.GetSystemMetrics(i) for i in (76,77,78,79))
        if width<1 or height<1 or width*height>MAX_PIXELS or x<sx or y<sy or x+width>sx+sw or y+height>sy+sh:
            raise BridgeError('Target client area must be fully on-screen and under capture size limit')
        return x,y,width,height

    def capture(self):
        w=self.target();geo=self.geometry(w);_,_,width,height=geo
        dc=self.GetDC(w)
        if not dc:
            raise BridgeError('Cannot allocate capture DC')
        mem=bmp=old=None
        try:
            mem=self.CreateCompatibleDC(dc)
            bmp=self.CreateCompatibleBitmap(dc,width,height)
            if not mem or not bmp:
                raise BridgeError('Cannot allocate capture bitmap')
            old=self.SelectObject(mem,bmp)
            if not old or old==C.c_void_p(-1).value:
                old=None
                raise BridgeError('Cannot select capture bitmap')
            # PW_CLIENTONLY | PW_RENDERFULLCONTENT. Capture the chosen app, not the full display.
            if not self.PrintWindow(w,mem,3):
                raise BridgeError('PrintWindow unavailable for this application')
            self.SelectObject(mem,old);old=None
            info=BITMAPINFO();info.bmiHeader=BITMAPINFOHEADER(C.sizeof(BITMAPINFOHEADER),width,-height,1,32,0,width*height*4,0,0,0,0)
            raw=C.create_string_buffer(width*height*4)
            if self.GetDIBits(mem,bmp,0,height,raw,C.byref(info),0)!=height:
                raise BridgeError('Incomplete Windows client-area capture')
            if self.geometry(self.target())!=geo:
                raise BridgeError('Window moved during capture')
            return self.Image.frombytes('RGB',(width,height),raw.raw,'raw','BGRX'),geo
        finally:
            if old and mem:self.SelectObject(mem,old)
            if bmp:self.DeleteObject(bmp)
            if mem:self.DeleteDC(mem)
            self.ReleaseDC(w,dc)

    def focus(self):
        w=self.target(False)
        self.SetForegroundWindow(w)
        return {'requested':True,'foreground':self.GetForegroundWindow()==w,'window':hex(w)}

    def _send(self,value):
        if self.SendInput(1,C.byref(value),C.sizeof(INPUT))!=1:
            raise BridgeError('Windows rejected input (possibly UIPI); no elevation attempted')

    def _mouse(self,flags,data=0):
        item=INPUT();item.type=0;item.u.mi=MOUSEINPUT(0,0,data&0xffffffff,flags,0,0);self._send(item)

    def _keyboard(self,vk,scan=0,flags=0):
        item=INPUT();item.type=1;item.u.ki=KEYBDINPUT(vk,scan,flags,0,0);self._send(item)

    def _pointer(self,w,x,y):
        gx,gy,width,height=self.geometry(self.target())
        if not 0<=x<width or not 0<=y<height:
            raise BridgeError('Point outside approved client area')
        point=W.POINT(gx+x,gy+y)
        under=self.WindowFromPoint(point)
        if not under or self.GetAncestor(under,2)!=w:
            raise BridgeError('Another window overlaps target point')
        if not self.SetCursorPos(point.x,point.y):
            raise BridgeError('Cannot move cursor')
        self.target()

    def click(self,w,x,y,button,count):
        down,up={1:(2,4),2:(32,64),3:(8,16)}[button]
        for _ in range(count):
            self._pointer(w,x,y)
            self._mouse(down)
            self._mouse(up)

    def move(self,w,x,y):self._pointer(w,x,y)

    def drag(self,w,x,y,to_x,to_y):
        self._pointer(w,x,y);self._mouse(2)
        try:
            for i in range(1,9):self._pointer(w,x+(to_x-x)*i//8,y+(to_y-y)*i//8)
        finally:self._mouse(4)

    def scroll(self,w,x,y,steps):
        self._pointer(w,x,y);self._mouse(0x0800,steps*120)

    def _tap(self,vk,shift=False,ctrl=False):
        modifiers=[]
        try:
            for on,k in ((ctrl,0x11),(shift,0x10)):
                if on:self._keyboard(k);modifiers.append(k)
            self._keyboard(vk);self._keyboard(vk,flags=2)
        finally:
            for k in reversed(modifiers):self._keyboard(k,flags=2)

    def type_text(self,text):
        if any(ord(c)<32 and c not in '\t\n' for c in text):
            raise BridgeError('Control characters are not permitted')
        for c in text:
            self.target()
            if c in '\t\n':self._tap(9 if c=='\t' else 13);continue
            raw=c.encode('utf-16-le')
            for i in range(0,len(raw),2):
                unit=int.from_bytes(raw[i:i+2],'little')
                self._keyboard(0,unit,4);self._keyboard(0,unit,6)

    def key(self,key,ctrl,shift):
        keys={'Enter':13,'Escape':27,'Tab':9,'Backspace':8,'Delete':46,'Home':36,'End':35,'Left':37,'Up':38,'Right':39,'Down':40,'Page_Up':33,'Page_Down':34,'Space':32}
        keys.update({f'F{i}':0x6f+i for i in range(1,13)})
        vk=keys.get(key)
        if vk is None and len(key)==1 and key.isascii() and key.isalnum():vk=ord(key.upper())
        if vk is None:raise BridgeError('Unknown key')
        self.target();self._tap(vk,shift,ctrl)

    def close(self):pass
