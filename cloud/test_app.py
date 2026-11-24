import io
import json
import tempfile
import unittest
import urllib.parse
from contextlib import closing
from unittest.mock import patch
from app import App, digest


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = App(self.tmp.name + '/db.sqlite', 'https://auxia.space/codez-cloud', 'https://identity.example/authorize', 'https://identity.example/token', 'https://identity.example/userinfo', 'test-client')

    def call(self, method, path, data=None, token=None, cookie=None, origin=None, form=False):
        path, _, query = path.partition('?')
        raw = urllib.parse.urlencode(data).encode() if form else json.dumps(data or {}).encode()
        env = {'REQUEST_METHOD':method,'PATH_INFO':path,'QUERY_STRING':query,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw)}
        if token: env['HTTP_AUTHORIZATION'] = 'Bearer ' + token
        if cookie: env['HTTP_COOKIE'] = cookie
        if origin: env['HTTP_ORIGIN'] = origin
        result = []
        body = b''.join(self.app(env, lambda status,headers: result.extend([status,dict(headers)])))
        status, headers = result
        return int(status.split()[0]),headers,json.loads(body) if headers.get('Content-Type')=='application/json' else body.decode()

    def login(self, subject, name):
        status,_,d=self.call('POST','/v1/device/start');self.assertEqual(status,200)
        code=d['user_code'];dev=d['device_code']
        self.assertEqual(self.call('GET','/activate?code='+code)[0],200)
        self.assertEqual(self.call('POST','/authorize',{'code':code},origin='https://evil.example',form=True)[0],403)
        status,headers,_=self.call('POST','/authorize',{'code':code},origin='https://auxia.space',form=True);self.assertEqual(status,303)
        q=urllib.parse.parse_qs(urllib.parse.urlsplit(headers['Location']).query);state=q['state'][0];cookie=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(q['code_challenge_method'],['S256']);self.assertEqual(q['client_id'],['test-client'])
        self.assertEqual(self.call('GET','/oauth/callback?state='+state+'&code=grant',cookie='codez_state=bad')[0],400)
        with patch.object(self.app,'exchange',return_value=(subject,name)) as exchange:
            self.assertEqual(self.call('GET','/oauth/callback?state='+state+'&code=grant',cookie=cookie)[0],200)
            self.assertEqual(exchange.call_count,1)
            self.assertEqual(self.call('GET','/oauth/callback?state='+state+'&code=grant',cookie=cookie)[0],410)
        with closing(self.app.connect()) as conn: conn.execute('UPDATE devices SET next_poll=0 WHERE digest=?',(digest(dev),))
        status,_,result=self.call('POST','/v1/device/poll',{'device_code':dev});self.assertEqual(status,200)
        token=result['access_token'];self.assertEqual(self.call('POST','/v1/device/poll',{'device_code':dev})[0],410)
        _,_,profile=self.call('GET','/v1/me',token=token);return token,profile

    def test_permissions_and_collaboration(self):
        a,alice=self.login('alice','Alice');b,bob=self.login('bob','Bob')
        self.assertEqual(self.call('GET','/v1/workspaces')[0],401)
        self.assertEqual(self.call('POST','/v1/workspaces',{'name':'Private'},a)[0],200)
        _,_,res=self.call('GET','/v1/workspaces',token=a);wid=res['items'][0]['id']
        self.assertEqual(self.call('GET','/v1/workspaces',token=b)[2]['items'],[])
        self.assertEqual(self.call('POST',f'/v1/workspaces/{wid}/delete',{},b)[0],404)
        self.assertEqual(self.call('POST','/v1/teams',{'name':'Core'},a)[0],200)
        tid=self.call('GET','/v1/teams',token=a)[2]['items'][0]['id']
        self.assertEqual(self.call('POST',f'/v1/teams/{tid}/invite',{'user_id':alice['id']},b)[0],404)
        self.assertEqual(self.call('POST',f'/v1/teams/{tid}/invite',{'user_id':bob['id']},a)[0],200)
        self.assertEqual(self.call('GET','/v1/teams',token=b)[2]['items'][0]['state'],'invited')
        self.assertEqual(self.call('POST','/v1/workspaces',{'name':'Shared','team_id':tid},b)[0],404)
        self.assertEqual(self.call('GET',f'/v1/teams/{tid}/members',token=b)[0],404)
        self.assertEqual(self.call('POST',f'/v1/teams/{tid}/accept',{},b)[0],200)
        self.assertEqual(self.call('GET','/v1/teams',token=b)[2]['items'][0]['state'],'member')
        self.assertEqual(self.call('POST','/v1/workspaces',{'name':'Shared','team_id':tid},b)[0],200)
        self.assertEqual({x['name'] for x in self.call('GET','/v1/workspaces',token=a)[2]['items']},{'Private','Shared'})
        self.assertEqual([x['name'] for x in self.call('GET','/v1/workspaces',token=b)[2]['items']],['Shared'])
        self.assertEqual(len(self.call('GET',f'/v1/teams/{tid}/members',token=b)[2]['items']),2)
        self.assertEqual(self.call('POST',f'/v1/teams/{tid}/delete',{},a)[0],409)
        self.assertEqual(self.call('POST','/v1/friends',{'user_id':bob['id']},a)[0],200)
        fid=self.call('GET','/v1/friends',token=b)[2]['items'][0]['id']
        self.assertEqual(self.call('POST',f'/v1/friends/{fid}/accept',{},a)[0],404)
        self.assertEqual(self.call('POST',f'/v1/friends/{fid}/accept',{},b)[0],200)
        self.assertEqual(self.call('GET','/v1/friends',token=a)[2]['items'][0]['state'],'friend')
        self.assertEqual(self.call('POST','/v1/projects',{'name':'Open','url':'file:///etc/passwd'},a)[0],400)
        self.assertEqual(self.call('POST','/v1/projects',{'name':'Open','url':'https://github.com/example/demo'},a)[0],200)
        project=self.call('GET','/v1/projects',token=b)[2]['items'][0]
        self.assertEqual(project['state'],'public')
        self.assertEqual(self.call('POST',f'/v1/projects/{project["id"]}/delete',{},b)[0],404)
        self.assertEqual(self.call('POST','/v1/logout',{},a)[0],200)
        self.assertEqual(self.call('GET','/v1/me',token=a)[0],401)

    def test_pending_rate_limit_and_expiry(self):
        d=self.call('POST','/v1/device/start')[2];secret=d['device_code']
        self.assertEqual(self.call('POST','/v1/device/poll',{'device_code':secret})[2]['error'],'slow_down')
        with closing(self.app.connect()) as conn: conn.execute('UPDATE devices SET next_poll=0')
        self.assertEqual(self.call('POST','/v1/device/poll',{'device_code':secret})[2]['error'],'authorization_pending')
        self.assertEqual(self.call('POST','/v1/device/poll',{'device_code':secret})[2]['error'],'slow_down')
        with closing(self.app.connect()) as conn: conn.execute('UPDATE devices SET expires=0')
        self.assertEqual(self.call('POST','/v1/device/poll',{'device_code':secret})[0],410)


if __name__=='__main__': unittest.main()
