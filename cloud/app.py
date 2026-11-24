"""CodEz Cloud: mount at /codez-cloud on auxia.space; OAuth userinfo adapter."""
import hashlib
import base64
import html
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing, contextmanager
from http.cookies import SimpleCookie

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, subject TEXT UNIQUE NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices(digest TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, expires INTEGER NOT NULL, next_poll INTEGER NOT NULL, user_id TEXT REFERENCES users(id));
CREATE TABLE IF NOT EXISTS oauth_states(digest TEXT PRIMARY KEY, device TEXT NOT NULL REFERENCES devices(digest) ON DELETE CASCADE, verifier TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tokens(digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, team TEXT REFERENCES teams(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS members(team TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id), accepted INTEGER NOT NULL DEFAULT 0, role TEXT NOT NULL DEFAULT 'developer' CHECK(role IN ('admin','maintainer','developer','reviewer','viewer','guest')), PRIMARY KEY(team,user_id));
CREATE TABLE IF NOT EXISTS friends(id TEXT PRIMARY KEY, sender TEXT NOT NULL REFERENCES users(id), recipient TEXT NOT NULL REFERENCES users(id), accepted INTEGER NOT NULL DEFAULT 0, pair TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, url TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS workspace_owner ON workspaces(owner);
CREATE INDEX IF NOT EXISTS member_user ON members(user_id);
CREATE INDEX IF NOT EXISTS friend_sender ON friends(sender);
CREATE INDEX IF NOT EXISTS friend_recipient ON friends(recipient);
CREATE INDEX IF NOT EXISTS token_user ON tokens(user_id);
'''

TEAM_ROLES = ('admin','maintainer','developer','reviewer','viewer','guest')
WORKSPACE_WRITERS = ('owner','admin','maintainer','developer')
TEAM_MANAGERS = ('owner','admin')


class Failure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def random_id():
    return secrets.token_hex(12)


def https_url(value):
    try:
        u = urllib.parse.urlsplit(value)
        return u.scheme == 'https' and bool(u.hostname) and not u.username and not u.password and not any(ord(c) < 33 or ord(c) == 127 for c in value)
    except ValueError:
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class App:
    def __init__(self, db, base, authorize, token, userinfo, client_id, client_secret='', scope='openid profile'):
        if not all(https_url(x) for x in (base, authorize, token, userinfo)) or not client_id:
            raise ValueError('HTTPS OAuth endpoints and client ID required')
        if urllib.parse.urlsplit(base).query or urllib.parse.urlsplit(base).fragment or any(urllib.parse.urlsplit(x).fragment for x in (authorize, token, userinfo)):
            raise ValueError('Invalid OAuth endpoint URL')
        self.db, self.base, self.authorize, self.token, self.userinfo = db, base.rstrip('/'), authorize, token, userinfo
        self.client_id, self.client_secret, self.scope = client_id, client_secret, scope
        self.redirect = self.base + '/oauth/callback'
        self.prefix = urllib.parse.urlsplit(self.base).path
        self.cookie_path = self.prefix.rstrip("/") + "/"
        with closing(self.connect()) as conn:
            conn.executescript(SCHEMA)
            with self.transaction(conn):
                if 'role' not in {row['name'] for row in conn.execute('PRAGMA table_info(members)')}:
                    conn.execute("ALTER TABLE members ADD COLUMN role TEXT NOT NULL DEFAULT 'developer' CHECK(role IN ('admin','maintainer','developer','reviewer','viewer','guest'))")

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    @contextmanager
    def transaction(self, conn):
        conn.execute('BEGIN IMMEDIATE')
        try:
            yield
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    def json(self, value, status='200 OK'):
        return status, [('Content-Type', 'application/json')], json.dumps(value).encode()

    def page(self, heading, body, headers=()):
        content = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Auxia / CodEz</title><style> *{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#101017;color:#f5f2ff;font:16px system-ui}}main{{width:min(460px,92vw);padding:36px;border:1px solid #363343;border-radius:22px;background:#191820}}small{{letter-spacing:.16em;color:#bc9bff}}h1{{font-size:32px;letter-spacing:-.04em}}p{{color:#c2bdcc;line-height:1.6}}code{{display:block;font-size:24px;letter-spacing:.12em;margin:24px 0;padding:16px;background:#272333;border-radius:12px;text-align:center}}button{{width:100%;border:0;background:#c5a8ff;color:#1c1231;padding:14px;border-radius:10px;font:600 16px system-ui;cursor:pointer}}</style><main><small>AUXIA / CODEZ</small><h1>{html.escape(heading)}</h1>{body}</main></html>'''
        return '200 OK', [('Content-Type','text/html; charset=utf-8'), *headers], content.encode()

    def __call__(self, env, respond):
        path = env.get('PATH_INFO','')
        if self.prefix and path.startswith(self.prefix + '/'):
            path = path[len(self.prefix):]
        try:
            with closing(self.connect()) as conn:
                status, headers, body = self.route(conn, env, path)
        except Failure as e:
            status, headers, body = self.json({'error':e.code}, e.status)
        except (sqlite3.Error, OSError):
            status, headers, body = self.json({'error':'service_unavailable'}, '503 Service Unavailable')
        respond(status, headers + [('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),('Content-Length',str(len(body)))])
        return [body]

    def input(self, env):
        try:
            size = int(env.get('CONTENT_LENGTH') or '0')
            if not 0 <= size <= 8192: raise ValueError()
            raw = env['wsgi.input'].read(size)
            value = json.loads(raw or b'{}')
            if not isinstance(value, dict): raise ValueError()
            return value
        except (ValueError, UnicodeError):
            raise Failure('400 Bad Request','invalid_body')

    def query(self, env):
        try:
            return {k:v[0] for k,v in urllib.parse.parse_qs(env.get('QUERY_STRING',''),max_num_fields=16).items()}
        except ValueError:
            raise Failure('400 Bad Request','invalid_query')

    def route(self, conn, env, path):
        method = env['REQUEST_METHOD']
        if path == '/activate' and method == 'GET':
            code = self.query(env).get('code','')
            if not re.fullmatch('[A-F0-9]{20}',code): raise Failure('400 Bad Request','invalid_code')
            if not conn.execute('SELECT 1 FROM devices WHERE code=? AND expires>? AND user_id IS NULL',(code,int(time.time()))).fetchone(): raise Failure('410 Gone','expired_code')
            return self.page('Connect your device',f'<p>Check that this code matches the one displayed in your terminal.</p><code>{code}</code><form method="post" action="{html.escape(self.base)}/authorize"><input type="hidden" name="code" value="{code}"><button>Continue with Auxia</button></form>')
        if path == '/authorize' and method == 'POST':
            origin = urllib.parse.urlsplit(self.base)
            if env.get('HTTP_ORIGIN') != f'{origin.scheme}://{origin.netloc}': raise Failure('403 Forbidden','invalid_origin')
            try:
                size=int(env.get('CONTENT_LENGTH','0'))
                if not 0<size<=1024: raise ValueError()
                code=urllib.parse.parse_qs(env['wsgi.input'].read(size).decode(),max_num_fields=2).get('code',[''])[0]
            except (ValueError,UnicodeError): raise Failure('400 Bad Request','invalid_code')
            return self.begin_oauth(conn,code)
        if path == '/oauth/callback' and method == 'GET':
            return self.callback(conn,env)
        if path == '/v1/device/start' and method == 'POST':
            self.input(env)
            return self.start(conn)
        if path == '/v1/device/poll' and method == 'POST':
            return self.poll(conn,self.input(env).get('device_code'))
        if not path.startswith('/v1/'): raise Failure('404 Not Found','not_found')
        user, token = self.identity(conn,env)
        if path == '/v1/me' and method == 'GET': return self.json(dict(user))
        if path == '/v1/logout' and method == 'POST':
            conn.execute('DELETE FROM tokens WHERE digest=?',(token,))
            return self.json({'ok':True})
        parts=path[4:].split('/')
        if not parts or parts[0] not in ('workspaces','teams','friends','projects'): raise Failure('404 Not Found','not_found')
        kind=parts[0]
        if len(parts)==1 and method=='GET': return self.json({'items':self.list_items(conn,kind,user['id'])})
        if kind=='teams' and len(parts)==3 and parts[2]=='members' and method=='GET':
            return self.json({'items':self.team_members(conn,parts[1],user['id'])})
        if method=='POST':
            data=self.input(env)
            with self.transaction(conn):
                if len(parts)==1: self.create(conn,kind,user['id'],data)
                elif len(parts)==3: self.action(conn,kind,user['id'],parts[1],parts[2],data)
                else: raise Failure('404 Not Found','not_found')
            return self.json({'ok':True})
        raise Failure('405 Method Not Allowed','method_not_allowed')

    def start(self,conn):
        now=int(time.time());device=secrets.token_urlsafe(32);code=secrets.token_hex(10).upper()
        with self.transaction(conn):
            conn.execute('DELETE FROM devices WHERE expires<=?',(now,));conn.execute('DELETE FROM tokens WHERE expires<=?',(now,))
            if conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0]>=2000: raise Failure('429 Too Many Requests','try_later')
            conn.execute('INSERT INTO devices VALUES(?,?,?,?,NULL)',(digest(device),code,now+600,now+3))
        return self.json({'device_code':device,'user_code':code,'verification_uri':self.base+'/activate?code='+code,'interval':3,'expires_in':600})

    def poll(self,conn,device):
        if not isinstance(device,str) or not re.fullmatch('[A-Za-z0-9_-]{43}',device): raise Failure('400 Bad Request','invalid_device')
        now=int(time.time());token=None;pending=False
        with self.transaction(conn):
            row=conn.execute('SELECT * FROM devices WHERE digest=?',(digest(device),)).fetchone()
            if not row or row['expires']<=now: raise Failure('410 Gone','expired_code')
            if row['next_poll']>now: raise Failure('429 Too Many Requests','slow_down')
            if not row['user_id']:
                conn.execute('UPDATE devices SET next_poll=? WHERE digest=?',(now+3,row['digest']));pending=True
            else:
                token=secrets.token_urlsafe(32)
                conn.execute('DELETE FROM devices WHERE digest=?',(row['digest'],))
                conn.execute('INSERT INTO tokens VALUES(?,?,?)',(digest(token),row['user_id'],now+30*86400))
        if pending: return self.json({'error':'authorization_pending'},'400 Bad Request')
        return self.json({'access_token':token,'token_type':'Bearer','expires_in':30*86400})

    def begin_oauth(self,conn,code):
        now=int(time.time());state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
        with self.transaction(conn):
            row=conn.execute('SELECT * FROM devices WHERE code=? AND expires>? AND user_id IS NULL',(code,now)).fetchone()
            if not row: raise Failure('410 Gone','expired_code')
            conn.execute('DELETE FROM oauth_states WHERE device=?',(row['digest'],))
            conn.execute('INSERT INTO oauth_states VALUES(?,?,?,?)',(digest(state),row['digest'],verifier,row['expires']))
        params={'response_type':'code','client_id':self.client_id,'redirect_uri':self.redirect,'scope':self.scope,'state':state,'code_challenge_method':'S256','code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
        link=self.authorize+('&' if '?' in self.authorize else '?')+urllib.parse.urlencode(params)
        return '303 See Other',[('Location',link),('Set-Cookie',f'codez_state={state}; Path={self.cookie_path}; Secure; HttpOnly; SameSite=Lax; Max-Age=600')],b''

    def callback(self,conn,env):
        q=self.query(env);state=q.get('state','');cookie=SimpleCookie()
        try: cookie.load(env.get('HTTP_COOKIE',''))
        except Exception: raise Failure('400 Bad Request','invalid_state')
        if not state or not cookie.get('codez_state') or not secrets.compare_digest(state,cookie['codez_state'].value) or not q.get('code'): raise Failure('400 Bad Request','invalid_state')
        with self.transaction(conn):
            row=conn.execute('SELECT * FROM oauth_states WHERE digest=? AND expires>?',(digest(state),int(time.time()))).fetchone()
            if not row: raise Failure('410 Gone','expired_code')
            conn.execute('DELETE FROM oauth_states WHERE digest=?',(digest(state),))
        subject,name=self.exchange(q['code'],row['verifier'])
        with self.transaction(conn):
            device=conn.execute('SELECT * FROM devices WHERE digest=? AND expires>? AND user_id IS NULL',(row['device'],int(time.time()))).fetchone()
            if not device: raise Failure('410 Gone','expired_code')
            conn.execute('INSERT INTO users VALUES(?,?,?) ON CONFLICT(subject) DO UPDATE SET name=excluded.name',(random_id(),subject,name))
            user=conn.execute('SELECT id FROM users WHERE subject=?',(subject,)).fetchone()[0]
            conn.execute('UPDATE devices SET user_id=? WHERE digest=?',(user,row['device']))
        return self.page('Device connected','<p>Return to CodEz. Your Auxia account is now connected to this device.</p>',[('Set-Cookie',f'codez_state=; Path={self.cookie_path}; Secure; HttpOnly; SameSite=Lax; Max-Age=0')])

    def exchange(self,code,verifier):
        fields={'grant_type':'authorization_code','code':code,'redirect_uri':self.redirect,'client_id':self.client_id,'code_verifier':verifier}
        if self.client_secret: fields['client_secret']=self.client_secret
        opener=urllib.request.build_opener(NoRedirect())
        def fetch(request):
            with opener.open(request,timeout=10) as response:
                data=response.read(65537)
                if len(data)>65536: raise ValueError()
                return json.loads(data)
        try:
            value=fetch(urllib.request.Request(self.token,data=urllib.parse.urlencode(fields).encode(),headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'}))
            token=value['access_token']
            if not isinstance(token,str) or not token or any(c.isspace() for c in token): raise ValueError()
            profile=fetch(urllib.request.Request(self.userinfo,headers={'Authorization':'Bearer '+token,'Accept':'application/json'}))
            subject=profile['sub'];name=profile.get('preferred_username') or profile.get('name') or 'Auxia member'
            if not isinstance(subject,str) or not subject or len(subject)>512 or not isinstance(name,str): raise ValueError()
            name=' '.join(name.split())[:80] or 'Auxia member'
            return subject,name
        except (OSError,ValueError,KeyError,TypeError,AttributeError): raise Failure('502 Bad Gateway','identity_provider_failed')

    def identity(self,conn,env):
        raw=env.get('HTTP_AUTHORIZATION','')
        if not re.fullmatch('Bearer [A-Za-z0-9_-]{43}',raw): raise Failure('401 Unauthorized','invalid_session')
        token=digest(raw[7:]);user=conn.execute('SELECT u.id,u.name FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.digest=? AND t.expires>?',(token,int(time.time()))).fetchone()
        if not user: raise Failure('401 Unauthorized','invalid_session')
        return user,token

    def list_items(self,conn,kind,user):
        queries={
          'workspaces':("""SELECT w.id,w.name,COALESCE(t.name,'Private workspace') detail,
              CASE WHEN w.team IS NULL OR t.owner=? OR m.role IN ('admin','maintainer') OR (w.owner=? AND m.role='developer') THEN 'owner' ELSE 'member' END state,
              CASE WHEN w.team IS NULL OR t.owner=? THEN 'owner' ELSE m.role END role
              FROM workspaces w LEFT JOIN teams t ON w.team=t.id LEFT JOIN members m ON m.team=w.team AND m.user_id=? AND m.accepted=1
              WHERE (w.team IS NULL AND w.owner=?) OR t.owner=? OR m.user_id IS NOT NULL ORDER BY w.name LIMIT 200""",(user,)*6),
          'teams':("""SELECT t.id,t.name,CASE WHEN t.owner=? THEN 'Owner' ELSE 'Team' END detail,
              CASE WHEN t.owner=? THEN 'owner' WHEN m.accepted=1 THEN 'member' ELSE 'invited' END state,
              CASE WHEN t.owner=? THEN 'owner' ELSE m.role END role
              FROM teams t LEFT JOIN members m ON m.team=t.id AND m.user_id=? WHERE t.owner=? OR m.user_id=? ORDER BY t.name LIMIT 200""",(user,)*6),
          'friends':("SELECT f.id,u.name,u.id detail,CASE WHEN f.accepted=1 THEN 'friend' WHEN f.sender=? THEN 'outgoing' ELSE 'incoming' END state FROM friends f JOIN users u ON u.id=CASE WHEN f.sender=? THEN f.recipient ELSE f.sender END WHERE f.sender=? OR f.recipient=? ORDER BY u.name LIMIT 200",(user,)*4),
          'projects':("SELECT p.id,p.name,u.name detail,CASE WHEN p.owner=? THEN 'owner' ELSE 'public' END state,p.url FROM projects p JOIN users u ON u.id=p.owner ORDER BY p.name LIMIT 200",(user,)),
        }
        sql,args=queries[kind];return [dict(x) for x in conn.execute(sql,args)]

    def team_role(self,conn,team,user):
        row=conn.execute("""SELECT CASE WHEN t.owner=? THEN 'owner' ELSE m.role END role
          FROM teams t LEFT JOIN members m ON m.team=t.id AND m.user_id=? AND m.accepted=1
          WHERE t.id=? AND (t.owner=? OR m.user_id IS NOT NULL)""",(user,user,team,user)).fetchone()
        return row['role'] if row else None

    def team_members(self,conn,team,user):
        role=self.team_role(conn,team,user)
        if role is None or role=='guest': raise Failure('404 Not Found','not_found')
        owner=conn.execute('SELECT owner FROM teams WHERE id=?',(team,)).fetchone()
        items=[dict(x) for x in conn.execute("SELECT id,name,'Owner' detail,'owner' state,'owner' role FROM users WHERE id=?",(owner['owner'],))]
        items.extend(dict(x) for x in conn.execute("SELECT u.id,u.name,u.id detail,CASE WHEN m.accepted=1 THEN 'member' ELSE 'invited' END state,m.role FROM members m JOIN users u ON u.id=m.user_id WHERE m.team=? AND (m.accepted=1 OR ?) ORDER BY u.name LIMIT 200",(team,role in TEAM_MANAGERS)))
        return items

    def name(self,data):
        name=data.get('name')
        if not isinstance(name,str) or not 1<=len(name.strip())<=100 or any(ord(c)<32 or ord(c)==127 for c in name): raise Failure('400 Bad Request','invalid_name')
        return name.strip()

    def target(self,conn,user,data):
        target=data.get('user_id')
        if not isinstance(target,str) or target==user or not conn.execute('SELECT 1 FROM users WHERE id=?',(target,)).fetchone(): raise Failure('400 Bad Request','invalid_user')
        return target

    def create(self,conn,kind,user,data):
        if kind=='friends':
            other=self.target(conn,user,data)
            if conn.execute('SELECT COUNT(*) FROM friends WHERE sender=? OR recipient=?',(user,user)).fetchone()[0]>=200: raise Failure('409 Conflict','limit_reached')
            pair=':'.join(sorted((user,other)))
            if conn.execute('SELECT 1 FROM friends WHERE pair=?',(pair,)).fetchone(): raise Failure('409 Conflict','already_exists')
            conn.execute('INSERT INTO friends VALUES(?,?,?,0,?)',(random_id(),user,other,pair));return
        if conn.execute(f'SELECT COUNT(*) FROM {kind} WHERE owner=?',(user,)).fetchone()[0]>=200: raise Failure('409 Conflict','limit_reached')
        name=self.name(data)
        if kind=='projects':
            url=data.get('url')
            if not isinstance(url,str) or len(url)>1000 or not https_url(url) or urllib.parse.urlsplit(url).query or urllib.parse.urlsplit(url).fragment: raise Failure('400 Bad Request','invalid_url')
            conn.execute('INSERT INTO projects VALUES(?,?,?,?)',(random_id(),user,name,url))
        elif kind=='workspaces':
            team=data.get('team_id') or None
            if team is not None and (not isinstance(team,str) or self.team_role(conn,team,user) not in WORKSPACE_WRITERS): raise Failure('404 Not Found','not_found')
            conn.execute('INSERT INTO workspaces VALUES(?,?,?,?)',(random_id(),user,name,team))
        else: conn.execute('INSERT INTO teams VALUES(?,?,?)',(random_id(),user,name))

    def action(self,conn,kind,user,item,action,data):
        if not re.fullmatch('[a-f0-9]{24}',item): raise Failure('404 Not Found','not_found')
        if kind=='friends':
            if action=='accept': cur=conn.execute('UPDATE friends SET accepted=1 WHERE id=? AND recipient=? AND accepted=0',(item,user))
            elif action=='delete': cur=conn.execute('DELETE FROM friends WHERE id=? AND (sender=? OR recipient=?)',(item,user,user))
            else: raise Failure('400 Bad Request','invalid_action')
        elif kind=='teams' and action=='invite':
            if self.team_role(conn,item,user) not in TEAM_MANAGERS: raise Failure('404 Not Found','not_found')
            other=self.target(conn,user,data)
            if conn.execute('SELECT 1 FROM teams WHERE id=? AND owner=?',(item,other)).fetchone(): raise Failure('409 Conflict','already_exists')
            if conn.execute('SELECT COUNT(*) FROM members WHERE team=?',(item,)).fetchone()[0]>=200: raise Failure('409 Conflict','limit_reached')
            if conn.execute('SELECT 1 FROM members WHERE team=? AND user_id=?',(item,other)).fetchone(): raise Failure('409 Conflict','already_exists')
            conn.execute("INSERT INTO members(team,user_id,accepted,role) VALUES(?,?,0,'developer')",(item,other));return
        elif kind=='teams' and action=='accept': cur=conn.execute('UPDATE members SET accepted=1 WHERE team=? AND user_id=? AND accepted=0',(item,user))
        elif kind=='teams' and action=='leave': cur=conn.execute('DELETE FROM members WHERE team=? AND user_id=?',(item,user))
        elif kind=='teams' and action=='role':
            if self.team_role(conn,item,user)!='owner': raise Failure('404 Not Found','not_found')
            role=data.get('role');other=self.target(conn,user,data)
            if role not in TEAM_ROLES: raise Failure('400 Bad Request','invalid_role')
            cur=conn.execute('UPDATE members SET role=? WHERE team=? AND user_id=?',(role,item,other))
        elif kind=='teams' and action=='remove_member':
            role=self.team_role(conn,item,user);other=self.target(conn,user,data)
            if role not in TEAM_MANAGERS: raise Failure('404 Not Found','not_found')
            cur=conn.execute("DELETE FROM members WHERE team=? AND user_id=? AND (?='owner' OR role!='admin')",(item,other,role))
        elif kind=='workspaces' and action=='delete':
            row=conn.execute('SELECT owner,team FROM workspaces WHERE id=?',(item,)).fetchone()
            if not row: raise Failure('404 Not Found','not_found')
            role=self.team_role(conn,row['team'],user) if row['team'] else None
            if not ((row['team'] is None and row['owner']==user) or role in ('owner','admin','maintainer') or (role=='developer' and row['owner']==user)):
                raise Failure('404 Not Found','not_found')
            cur=conn.execute('DELETE FROM workspaces WHERE id=?',(item,))
        elif kind=='teams' and action=='delete':
            if not conn.execute('SELECT 1 FROM teams WHERE id=? AND owner=?',(item,user)).fetchone(): raise Failure('404 Not Found','not_found')
            if conn.execute('SELECT 1 FROM workspaces WHERE team=?',(item,)).fetchone(): raise Failure('409 Conflict','remove_team_workspaces_first')
            cur=conn.execute('DELETE FROM teams WHERE id=? AND owner=?',(item,user))
        elif kind=='projects' and action=='delete': cur=conn.execute('DELETE FROM projects WHERE id=? AND owner=?',(item,user))
        else: raise Failure('400 Bad Request','invalid_action')
        if cur.rowcount!=1: raise Failure('404 Not Found','not_found')


def create_app():
    os.umask(0o077)
    return App(os.environ['CODEZ_CLOUD_DB'],os.getenv('CODEZ_CLOUD_BASE','https://auxia.space/codez-cloud'),os.getenv('AUXIA_OAUTH_AUTHORIZE','https://auxia.space/api/login'),os.environ['AUXIA_OAUTH_TOKEN'],os.environ['AUXIA_OAUTH_USERINFO'],os.environ['AUXIA_OAUTH_CLIENT_ID'],os.getenv('AUXIA_OAUTH_CLIENT_SECRET',''),os.getenv('AUXIA_OAUTH_SCOPE','openid profile'))


if __name__=='__main__':
    from wsgiref.simple_server import make_server, WSGIRequestHandler
    class PrivateHandler(WSGIRequestHandler):
        def log_request(self, code='-', size='-'):
            self.log_message('%s %s', self.command, code)
    with make_server('127.0.0.1',8088,create_app(), handler_class=PrivateHandler) as server:
        server.serve_forever()
