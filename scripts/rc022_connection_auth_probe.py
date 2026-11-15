"""Pair signed browser/API exchanges and protocol-scoped cookie verification."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
NOW=1800000000000


class Response:
    def __init__(self):self.state=dict(status=None,headers={},body='')
    def write_status(self,value):self.state['status']=value
    def write_header(self,key,value):self.state['headers'][key]=value
    def write_body(self,value):self.state['body']+=value.decode('utf-8')


async def observe():
    from dsh.cordis import Context
    from dsh.host.connection.auth_current import CurrentBrowserAuth,encode_cookie
    from dsh.host.connection.browser_auth import cookie_name
    rows=[];owner=Context()
    with patch('dsh.host.connection.auth_current.time.time',return_value=NOW/1000):
        auth=CurrentBrowserAuth(owner,bytes(range(32)),1)
        for secure in (False,True):
            host='LOCALHOST:443' if secure else 'LOCALHOST:80';published=[];cookies={}
            for kind in ('browser','api','answer'):
                request=dict(method='GET',headers=dict(host=host),raw_url=('/?token=' if kind=='browser' else '/connect?token=')+auth.launch_token+('&interactions=answer' if kind=='answer' else ''))
                response=Response()
                if kind=='browser':auth.authorize_index(request,response,secure)
                else:auth.authorize_connect(request,response,secure,lambda interactions:published.append(interactions) or 'operator-id')
                cookie=response.state['headers']['set-cookie'].split(';')[0];cookies[kind]=cookie
                facts=[]
                for mode in (False,True):
                    req=dict(headers=dict(host=host,cookie=cookie));facts.append(dict(secure=mode,browser=auth.is_authenticated(req,mode),api=auth.authenticate_api(req,mode)))
                rows.append(dict(name=kind,secure=secure,response=response.state,facts=facts))
            for query in ('bad','duplicate','none','invalid-interaction','duplicate-interaction','wrong-path','post','head','cookie-cleanup','api-index'):
                raw='/connect?token='+auth.launch_token
                if query=='bad':raw='/connect?token=bad'
                if query=='duplicate':raw+='&token='+auth.launch_token
                if query=='none':raw='/connect'
                if query=='invalid-interaction':raw+='&interactions=other'
                if query=='duplicate-interaction':raw+='&interactions=none&interactions=answer'
                if query=='wrong-path':raw=raw.replace('/connect','/nested/connect')
                if query=='cookie-cleanup':raw='/?token=bad'
                if query=='api-index':raw='/'
                request=dict(method='POST' if query=='post' else 'HEAD' if query=='head' else 'GET',headers=dict(host=host,cookie=cookies['api'] if query=='api-index' else cookies['browser']),raw_url=raw)
                response=Response()
                if query in ('cookie-cleanup','api-index'):allowed=auth.authorize_index(request,response,secure)
                else:auth.authorize_connect(request,response,secure,lambda interactions:published.append(interactions) or 'operator-id');allowed=None
                rows.append(dict(name=query,secure=secure,response=response.state,allowed=allowed))
            rows.append(dict(name='published',secure=secure,values=published))
        for name,changes in [('valid',{}),('expired',dict(expiresAt=NOW)),('future',dict(issuedAt=NOW+1)),('reversed',dict(expiresAt=NOW-1)),('too-long',dict(expiresAt=NOW+86400001)),('wrong-authority',dict(authority='evil')),('empty-id',dict(id='')),('bad-id',dict(id=4)),('bad-version',dict(version=3)),('fractional',dict(issuedAt=NOW-0.5)),('boolean',dict(issuedAt=True)),('extra',dict(extra='ignored'))]:
            payload=dict(version=2,authority='localhost',id='operator-id',issuedAt=NOW-1,expiresAt=NOW+10);payload.update(changes)
            cookie=cookie_name('localhost')+'='+encode_cookie(payload,auth.secret)
            request=dict(headers=dict(host='localhost',cookie=cookie))
            rows.append(dict(name=name,browser=auth.is_authenticated(request),api=auth.authenticate_api(request)))
        for base in ('http://localhost/mount/?x=1#hash','https://localhost/path?token=old&x=a+b&token=second'):
            rows.append(dict(name='url',value=auth.authenticated_url(base).replace(auth.launch_token,'TOKEN')))
    await owner.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_connection_auth.mts','Actual upstream BrowserAuth signed browser/API exchanges with deterministic clock/secret; protocol audience, Secure cookie, interactions/query validation, version/time/id/authority verification, URL preservation.',[Path(__file__).resolve(),ROOT/'dsh/host/connection/auth_current.py'])
