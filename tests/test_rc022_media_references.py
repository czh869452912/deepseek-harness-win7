import asyncio
from types import SimpleNamespace as NS
from urllib.parse import urlencode

import pytest

from dsh.api.session_media_authorized import AuthorizedSessionMediaReferences, serve_file
from dsh.cordis import Context
from dsh.core.abort import NEVER_ABORTED, AbortController
from dsh.fs.fs_local import LocalFileSystem


@pytest.mark.asyncio
async def test_versioned_media_route_and_provider_error_boundaries():
    from scripts.rc022_media_references_probe import observe
    rows = {row['name']: row for row in await observe()}
    assert all(row['withdrawn'] for row in rows.values())
    for name in ('unversioned','stale','unversioned-head','encoded'):
        assert rows[name]['value']['status'] == 302
        assert [call['method'] for call in rows[name]['calls']] == ['resolve','stat']
        assert rows[name]['value']['headers']['cache-control'] == 'private, no-store'
    assert rows['encoded']['value']['headers']['location'] == '?path=C%3A%2F%E8%B5%84%E6%96%99%2Fspace+%2B%7E*%23.svg&v=v+%26%7E*%E4%B8%AD%E6%96%87'
    for name in ('versioned','ignored-range'):
        value = rows[name]['value']; assert value['status'] == 200 and value['hex'] == '000102ff'
        assert value['headers']['cache-control'] == 'private, max-age=31536000, immutable'
    assert 'content-length' not in rows['size-unknown']['value']['headers']
    assert rows['versioned-head']['value']['hex'] == ''
    assert rows['unknown-mime']['value']['headers']['content-type'] == 'application/octet-stream'
    assert rows['error-unexpected']['value'] == dict(error='unexpected provider failure')


@pytest.mark.asyncio
async def test_real_connection_authentication_version_redirect_change_and_unload(tmp_path):
    from dsh.host.connection.plugin_current import AuthorizedConnectionPlugin
    from dsh.host.webserver.webserver import WebServerService
    ctx = Context(); records = {}; clients = []
    def modify(key, mutate):
        value = mutate(records.get(key))
        if value is not None: records[key] = value
        return records.get(key)
    ctx.set_service('credentials', NS(modify_record=modify))
    server = WebServerService(ctx,host='127.0.0.1',port=0)
    try:
        default = tmp_path/'default'; default.mkdir()
        await ctx.plugin(LocalFileSystem, dict(cwd=str(default)))
        ctx.set_service('attachments', NS(imageLimits=dict(maxImageBytes=4,maxMessageImageBytes=4)))
        await ctx.plugin(AuthorizedConnectionPlugin); ctx.set_service('webServer', server)
        for _ in range(100):
            if server.match('/connect') is not None: break
            await asyncio.sleep(0)
        await server.start(); provider = await ctx.plugin(AuthorizedSessionMediaReferences)
        path = tmp_path/'file ~+.html'
        path.write_bytes(b'<p/>'); fs = ctx.fs; reads = []; original = fs.readBytes
        async def read(*args): reads.append(True); return await original(*args)
        fs.readBytes = read
        async def exchange(url, method='GET', cookie=None):
            reader, writer = await asyncio.open_connection('127.0.0.1', server.listened_port); clients.append(writer)
            try:
                text = method+' '+url+' HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n'
                if cookie: text += 'Cookie: '+cookie+'\r\n'
                writer.write((text+'\r\n').encode('ascii')); await writer.drain(); raw = await asyncio.wait_for(reader.read(), 3)
                head, body = raw.split(b'\r\n\r\n',1); lines=head.decode().split('\r\n')
                return int(lines[0].split()[1]), {key.lower():value.strip() for key,value in (line.split(':',1) for line in lines[1:])}, body
            finally: writer.close(); await writer.wait_closed(); clients.remove(writer)
        url = '/api/file?'+urlencode(dict(path=str(path)))
        denied = await exchange(url); assert denied[0] == 401 and not reads
        login = await exchange('/connect?token='+ctx.connection.browser_auth.launch_token)
        cookie = login[1]['set-cookie'].split(';')[0]
        redirect = await exchange(url,cookie=cookie); assert redirect[0] == 302 and not reads
        location = redirect[1]['location']; assert location.startswith('?path=')
        head = await exchange('/api/file'+location,'HEAD',cookie)
        assert head[0] == 200 and head[1]['content-length'] == '4' and head[2] == b'' and not reads
        get = await exchange('/api/file'+location,cookie=cookie)
        assert get[0] == 200 and get[2] == b'<p/>' and len(reads)==1
        assert get[1]['content-type']=='text/html' and get[1]['content-security-policy']=="sandbox; default-src 'none'"
        path.write_bytes(b'new')
        stale = await exchange('/api/file'+location,cookie=cookie)
        assert stale[0] == 302 and stale[1]['location']!=location and len(reads)==1
        assert (await exchange('/api/file'+stale[1]['location'],cookie=cookie))[2] == b'new'
        path.write_bytes(b'large')
        over = await exchange(url,cookie=cookie); assert over[0] == 413 and len(reads)==2
        await provider.dispose(); assert (await exchange(url,cookie=cookie))[0] == 404
    finally:
        for writer in clients: writer.close()
        await server.stop(); await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_fs_growth_after_stat_and_cancel_do_not_cache_errors(tmp_path):
    ctx = Context()
    try:
        await ctx.plugin(LocalFileSystem, dict(cwd=str(tmp_path))); path=tmp_path/'grow.png'; path.write_bytes(b'1234'); fs=ctx.fs
        info = await fs.stat(await fs.resolve(str(path)))
        request = dict(url='https://host/api/file?'+urlencode(dict(path=str(path),v=info.version)),method='GET',signal=NEVER_ABORTED)
        def grow(_): path.write_bytes(b'12345')
        fs.internals.inspectReadBytesAfterStat = grow
        result = await serve_file(request,fs,4)
        assert result['status']==413 and result['body']=='FS_TOO_LARGE' and result['headers']['cache-control']=='private, no-store'
        abort=AbortController();abort.abort();request['signal']=abort.signal
        result = await serve_file(request,fs,4)
        assert result['status']==499 and result['headers']['cache-control']=='private, no-store'
    finally: await ctx.fiber.dispose()
