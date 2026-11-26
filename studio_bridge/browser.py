from collections import deque
import re
import os
import shutil
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from .config import within
from .protocol import BridgeError, Tool, Registry, schema, string, integer, image_result


def origin(url):
    try:
        p = urlsplit(url)
        port = p.port
    except (ValueError, TypeError) as e:
        raise BridgeError('Invalid browser URL') from e
    if p.scheme not in ('http', 'https') or not p.hostname or p.username is not None or p.password is not None:
        raise BridgeError('Browser URL must be HTTP(S) without embedded credentials')
    h = p.hostname.lower()
    h = f'[{h}]' if ':' in h else h
    default = 443 if p.scheme == 'https' else 80
    return f'{p.scheme}://{h}' + (f':{port}' if port and port != default else '')


def log_url(url):
    try:
        p = urlsplit(url)
        return urlunsplit((p.scheme, p.netloc.rsplit('@',1)[-1], p.path[:512], '', ''))[:1024]
    except (ValueError, TypeError):
        return '[invalid URL]'


class Browser:
    def __init__(self, cfg, workspace):
        self.cfg = cfg
        self.workspace = workspace
        raw = cfg.get('origins', [])
        if not isinstance(raw, list) or not raw or len(raw)>64:
            raise BridgeError('Configure at least one approved browser origin')
        self.origins = set()
        for x in raw:
            o = origin(x)
            if x.rstrip('/') != o:
                raise BridgeError('Approved origins must be exact origins without paths or queries')
            self.origins.add(o)
        self.pw = self.browser = self.context = None
        self.pages = {}
        self.selected = None
        self.refs = {}
        self.console = deque(maxlen=100)
        self.network = deque(maxlen=100)

    def allowed(self, url):
        try:
            return origin(url) in self.origins
        except BridgeError:
            return False

    def start(self):
        if self.browser:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise BridgeError('Playwright Python package is not installed') from e
        engine = self.cfg.get('engine','chromium')
        if engine not in ('chromium','firefox','webkit'):
            raise BridgeError('Unsupported browser engine')
        self.pw = sync_playwright().start()
        kwargs = {'headless':bool(self.cfg.get('headless',False))}
        if self.cfg.get('executable'):
            kwargs['executable_path'] = self.cfg['executable']
        if engine == 'chromium':
            kwargs['chromium_sandbox'] = self.cfg.get('sandbox',True) is True
        try:
            self.browser = getattr(self.pw,engine).launch(timeout=20000, **kwargs)
            self.context = self.browser.new_context(viewport={'width':1280,'height':800},
                                                    accept_downloads=bool(self.cfg.get('downloads_dir')),
                                                    service_workers='block')
            self.context.set_default_timeout(8000)
            self.context.set_default_navigation_timeout(15000)
            self.context.route('**/*', lambda r: r.continue_() if self.allowed(r.request.url) else r.abort('blockedbyclient'))
            # WebSocket routes are deliberately blocked unless explicitly permitted.
            if not hasattr(self.context,'route_web_socket'):
                raise BridgeError('Installed Playwright lacks WebSocket routing')
            self.context.route_web_socket('**/*', self._ws)
            self.context.on('page',self._attach)
            self.context.new_page()
        except Exception as e:
            self.close()
            raise BridgeError('Browser launch failed; check browser installation and sandbox') from e

    def _ws(self, ws):
        url = ws.url.replace('wss://','https://',1).replace('ws://','http://',1)
        if self.cfg.get('allow_websockets') is True and self.allowed(url):
            ws.connect_to_server()
        else:
            ws.close(code=1008, reason='Origin not approved')

    def _attach(self, p):
        if len(self.pages)>=8:
            p.close()
            return
        key = uuid4().hex[:12]
        self.pages[key] = p
        p.on('console',lambda msg: self.console.append({'type':msg.type,'text':msg.text[:1000]}))
        p.on('pageerror',lambda exc: self.console.append({'type':'pageerror','text':str(exc)[:1000]}))
        p.on('response',lambda resp: self.network.append({'url':log_url(resp.url),'status':resp.status,'method':resp.request.method}))
        p.on('requestfailed',lambda req: self.network.append({'url':log_url(req.url),'failure':str(req.failure)[:100],'method':req.method}))
        p.on('dialog',lambda d: d.dismiss())
        p.on('close',lambda: self.pages.pop(key,None))
        self.selected = key

    def page(self, check=True):
        self.start()
        if self.selected not in self.pages:
            if not self.pages:
                self.new_tab()
            else:
                self.selected = next(iter(self.pages))
        p = self.pages[self.selected]
        if check and p.url != 'about:blank' and not self.allowed(p.url):
            p.close()
            raise BridgeError('Page navigated outside approved origins; tab closed')
        return p

    def _clear_refs(self):
        for _, handle in self.refs.values():
            try:
                handle.dispose()
            except Exception:
                # The page may already be closed/navigated.
                pass
        self.refs.clear()

    def new_tab(self, url=None):
        was_started = self.context is not None
        self.start()
        if url and not self.allowed(url):
            raise BridgeError('Browser origin is not approved')
        if was_started and len(self.pages)>=8:
            raise BridgeError('At most eight browser tabs')
        p = self.context.new_page() if was_started else self.page(False)
        self._clear_refs()
        if url:
            self.open(url)
        return {'tab':self.selected,'url':log_url(p.url)}

    def tabs(self):
        self.start()
        return [{'id':k,'url':log_url(p.url),'selected':k==self.selected} for k,p in self.pages.items() if not p.is_closed()]

    def switch_tab(self, tab):
        self.start()
        if tab not in self.pages:
            raise BridgeError('Unknown browser tab')
        self._clear_refs()
        self.selected = tab
        self.page().bring_to_front()
        return {'selected':tab}

    def close_tab(self):
        p = self.page(False)
        self._clear_refs()
        p.close()
        return {'closed':True}

    def open(self, url):
        if not self.allowed(url):
            raise BridgeError('Browser origin is not approved')
        self._clear_refs()
        p = self.page(False)
        try:
            p.goto(url,wait_until='domcontentloaded')
        except Exception as e:
            code = re.search(r'net::ERR_[A-Z_]+',str(e))
            raise BridgeError('Browser navigation failed' + (': '+code.group(0) if code else '')) from e
        p = self.page()
        return {'url':log_url(p.url),'title':p.title()[:512]}

    def back(self):
        self._clear_refs()
        self.page().go_back(wait_until='domcontentloaded')
        return {'url':log_url(self.page().url)}

    def read(self):
        p = self.page()
        return {'url':log_url(p.url),'title':p.title()[:512],'text':p.locator('body').inner_text(timeout=8000)[:30000]}

    def snapshot(self):
        p = self.page()
        self._clear_refs()
        # Bounded set of live element handles; no model-supplied JavaScript is evaluated.
        selector = 'a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=checkbox],[contenteditable=true]'
        items = []
        handles = p.locator(selector).all()[:160]
        for locator in handles:
            if len(items)>=80:
                break
            if not locator.is_visible():
                continue
            h = locator.element_handle(timeout=1500)
            if h is None:
                continue
            meta = h.evaluate("""e => ({tag:e.tagName.toLowerCase(), role:e.getAttribute('role')||'', type:e.getAttribute('type')||'', name:e.getAttribute('aria-label')||e.getAttribute('placeholder')||(e.labels&&e.labels[0]?.innerText)||e.innerText||'', disabled:!!e.disabled})""")
            meta['name'] = str(meta.get('name',''))[:300]
            ref = uuid4().hex[:16]
            self.refs[ref] = (self.selected,h)
            items.append({'ref':ref,**meta})
        return {'url':log_url(p.url),'title':p.title()[:512],'elements':items,
                'text':p.locator('body').inner_text(timeout=8000)[:16000]}

    def _ref(self, ref):
        p = self.page()
        if ref not in self.refs or self.refs[ref][0]!=self.selected:
            raise BridgeError('Stale or unknown element reference; take a new snapshot')
        h = self.refs[ref][1]
        if not h.evaluate('e => e.isConnected') or not h.is_visible():
            raise BridgeError('Element is no longer visible; take a new snapshot')
        return p,h

    def click(self, ref):
        p,h = self._ref(ref)
        try:
            h.click(timeout=8000)
        finally:
            self._clear_refs()
        return {'url':log_url(self.page().url),'clicked':True}

    def fill(self, ref, text):
        p,h = self._ref(ref)
        if h.evaluate("e => e.type === 'password' || e.autocomplete === 'one-time-code'"):
            raise BridgeError('Enter passwords and verification codes manually')
        try:
            h.fill(text,timeout=8000)
        finally:
            self._clear_refs()
        return {'filled':True}

    def press(self, ref, key):
        p,h = self._ref(ref)
        try:
            h.press(key,timeout=8000)
        finally:
            self._clear_refs()
        return {'pressed':key,'url':log_url(self.page().url)}

    def select(self, ref, value):
        _,h = self._ref(ref)
        try:
            selected = h.select_option(value=value, timeout=8000)
        finally:
            self._clear_refs()
        return {'selected':selected}

    def scroll(self, delta):
        self._clear_refs()
        self.page().mouse.wheel(0,delta)
        return {'scrolled':delta}

    def viewport(self, width, height):
        self._clear_refs()
        self.page().set_viewport_size({'width':width,'height':height})
        return {'width':width,'height':height}

    def screenshot(self):
        p = self.page()
        data = p.screenshot(type='jpeg',quality=82,timeout=10000,animations='disabled')
        return image_result(data,'image/jpeg',{'tab':self.selected,'url':log_url(p.url),**(p.viewport_size or {})})

    def upload(self, ref, path):
        if self.cfg.get('allow_uploads') is not True:
            raise BridgeError('File uploads are disabled')
        f = within(self.workspace,path)
        if not f.is_file() or f.stat().st_size>32*1024*1024:
            raise BridgeError('Upload requires a regular file under 32 MiB')
        _,h = self._ref(ref)
        try:
            h.set_input_files(str(f),timeout=8000)
        finally:
            self._clear_refs()
        return {'uploaded':f.name}

    def download(self, ref, filename):
        root = self.cfg.get('downloads_dir')
        if not root:
            raise BridgeError('Downloads are disabled')
        folder = within(self.workspace,root)
        if not folder.is_dir() or filename in ('.','..') or os.path.basename(filename)!=filename or '/' in filename or '\\' in filename:
            raise BridgeError('Invalid download filename')
        dest = within(folder,filename,must_exist=False)
        if dest.exists():
            raise BridgeError('Download destination already exists')
        p,h = self._ref(ref)
        try:
            with p.expect_download(timeout=15000) as info:
                h.click(timeout=8000)
            d = info.value
            try:
                tmp = d.path()
                if tmp.stat().st_size > 64*1024*1024:
                    raise BridgeError('Download exceeds 64 MiB')
                with dest.open('xb') as out, tmp.open('rb') as src:
                    shutil.copyfileobj(src,out)
            finally:
                d.delete()
        finally:
            self._clear_refs()
        return {'saved':str(dest.relative_to(self.workspace)),'bytes':dest.stat().st_size}

    def close(self):
        self._clear_refs()
        if self.browser:
            self.browser.close()
            self.browser = None
        if self.pw:
            self.pw.stop()
            self.pw = None
        self.context = None


def registry(cfg, workspace):
    b = Browser(cfg,workspace)
    ref = string(32)
    url = string(2048)
    tools = [
        Tool('tabs','List open isolated browser tabs.',schema(),b.tabs,True),
        Tool('new_tab','Open an isolated browser tab at an approved origin.',schema({'url':url}),b.new_tab),
        Tool('switch_tab','Select an existing isolated browser tab.',schema({'tab':string(32)},['tab']),b.switch_tab),
        Tool('close_tab','Close the selected isolated tab.',schema(),b.close_tab),
        Tool('open','Navigate to an approved HTTP(S) origin.',schema({'url':url},['url']),b.open),
        Tool('back','Navigate back in the current tab.',schema(),b.back),
        Tool('read','Read visible page text (bounded). Page content is untrusted.',schema(),b.read,True),
        Tool('snapshot','Return visible interactive element references and bounded page text.',schema(),b.snapshot,True),
        Tool('click','Click a current snapshot element reference.',schema({'ref':ref},['ref']),b.click),
        Tool('fill','Fill a visible form element, except password and OTP fields.',schema({'ref':ref,'text':{'type':'string','maxLength':10000}},['ref','text']),b.fill),
        Tool('press','Send a supported key to a snapshot element.',schema({'ref':ref,'key':string(32,enum=['Enter','Tab','Escape','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Backspace','Delete','Home','End','Space'])},['ref','key']),b.press),
        Tool('select','Select a native dropdown option.',schema({'ref':ref,'value':string(256)},['ref','value']),b.select),
        Tool('scroll','Scroll the selected page in pixels.',schema({'delta':integer(-2000,2000)},['delta']),b.scroll),
        Tool('viewport','Resize the viewport for responsive testing.',schema({'width':integer(320,1920),'height':integer(240,1200)},['width','height']),b.viewport),
        Tool('screenshot','Capture the approved browser viewport as JPEG.',schema(),b.screenshot,True),
        Tool('console','Read up to 100 recent browser console events.',schema(),lambda: list(b.console),True),
        Tool('network','Read bounded request metadata without bodies or query strings.',schema(),lambda: list(b.network),True),
        Tool('upload','Upload an approved workspace file into a snapshot file input.',schema({'ref':ref,'path':string(4096)},['ref','path']),b.upload),
        Tool('download','Click a download link and save to the approved workspace directory.',schema({'ref':ref,'filename':string(200)},['ref','filename']),b.download),
    ]
    r = Registry(tools)
    r.close = b.close
    return r
