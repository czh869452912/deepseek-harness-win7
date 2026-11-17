"""Unchanged optional Source Discover bundle against the candidate Python host."""
import asyncio
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import threading
from urllib.parse import parse_qs, quote, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_application_probe as application
from scripts.rc022_schedule_browser_probe import before

FIXTURE = None
COLD_FROM = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        parsed = urlsplit(self.path)
        target = parse_qs(parsed.query).get('url', [''])[0]
        if parsed.path == '/index.json':
            body = json.dumps(dict(format=1, title='Browser Market', plugins=[dict(name=name, title=title,
                description=description, versions=[dict(version='1.0.0', publishTimestamp=1700000000,
                engines=dict(dsh='*'), source=dict(type='npm'))]) for name, title, description in [
                    ('browser-market-fixture', 'Browser Market Fixture', 'A searchable browser qualification plugin'),
                    ('browser-market-other', 'Browser Other Fixture', 'Another fixture entry')]])).encode('utf-8')
        elif target.endswith('/README.md'):
            body = b'# Browser detail evidence\n\nOriginal Markdown and an adjacent image.\n\n![Market image](img/evidence.png)\n'
        elif target.endswith('/img/evidence.png'):
            import base64
            body = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')
        else:
            self.send_response(404); self.send_header('Content-Length', '0'); self.end_headers(); return
        self.send_response(200); self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Type', 'application/json' if parsed.path == '/index.json' else 'application/octet-stream')
        self.end_headers(); self.wfile.write(body)


async def after(ctx, result, output):
    from dsh.core.abort import NEVER_ABORTED
    result['marketStrict'] = {endpoint:ctx.typert.local.get(endpoint) is not None for endpoint in
        ['pluginMarket/listIndexes', 'pluginMarket/search', 'pluginMarket/setIndexes', 'pluginMarket/readEntryDetail']}
    result['marketPreflight'] = await ctx.typertGateway.dispatch_rpc('pluginMarket/listIndexes', dict(args={}), NEVER_ABORTED, ctx.connection.browserPeer)
    config = output/'browser-config.json'
    if COLD_FROM is not None:
        result['coldRestart'] = dict(sourceRun=COLD_FROM.name, processId=os.getpid(),
            indexesBefore=ctx.pluginMarket.listIndexes())
        assert result['coldRestart']['indexesBefore'] == [dict(url=FIXTURE+'/index.json')]
    config.write_text(json.dumps(dict(url=ctx.connection.authenticatedUrl(ctx.webServer.getOrigin()), index=FIXTURE+'/index.json', cold=COLD_FROM is not None)), encoding='utf-8')
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    node = ROOT/'.goose/out/rc022-prep-20261114-01/toolchain/node-v24.9.0-win-x64/node.exe'
    command = [str(node), str(ROOT/'scripts/oracles/rc022_market_browser.mjs'), str(source), str(output)]
    result['browserScriptSha256'] = hashlib.sha256(Path(command[1]).read_bytes()).hexdigest()
    (output/'browser-command.json').write_text(json.dumps(command), encoding='utf-8')
    def chain(coro, seen=None):
        seen = set() if seen is None else seen
        if coro is None or id(coro) in seen or len(seen) > 16: return []
        seen.add(id(coro))
        frame = getattr(coro, 'cr_frame', getattr(coro, 'gi_frame', None))
        rows = []
        if frame is not None:
            row = dict(file=frame.f_code.co_filename, line=frame.f_lineno, name=frame.f_code.co_name)
            for name in ('endpoint', 'pathname'):
                if isinstance(frame.f_locals.get(name), str): row[name] = frame.f_locals[name]
            request = frame.f_locals.get('request')
            if isinstance(request, dict): row['path'] = request.get('path')
            rows.append(row)
            if frame.f_code.co_name == 'resume_coroutine': rows += chain(frame.f_locals.get('listener'), seen)
        return rows+chain(getattr(coro, 'cr_await', getattr(coro, 'gi_yieldfrom', None)), seen)
    async def monitor():
        while True:
            await asyncio.sleep(5)
            rows = [dict(id=id(task), chain=chain(task.get_coro()), waiter=repr(getattr(task, '_fut_waiter', None))) for task in asyncio.all_tasks()]
            rows = [row for row in rows if any(any(key in frame['file'] for key in ('market_', 'plugin_market', 'webserver', 'typert', 'http_bridge', 'rpc_')) for frame in row['chain'])]
            with (output/'market-task-observations.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(rows)+'\n')
    monitoring = asyncio.create_task(monitor())
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        log = await asyncio.wait_for(process.communicate(), 150)
    except BaseException:
        if process.returncode is None: process.kill()
        await process.communicate(); raise
    finally:
        monitoring.cancel(); await asyncio.gather(monitoring, return_exceptions=True)
        config.unlink()
    (output/'browser.log').write_bytes(log[0])
    result['browser'] = json.loads((output/'browser-observations.json').read_text(encoding='utf-8'))
    result['marketSourcesAfter'] = ctx.pluginMarket.listIndexes()
    if not result['browser']['passed']:
        try:
            value = await asyncio.wait_for(ctx.pluginMarket.search(FIXTURE+'/index.json', dict(sort=dict(kind='index'), offset=0, limit=100)), 5)
            result['searchAfterFailure'] = dict(total=value['total'], names=[entry['name'] for entry in value['entries']])
        except Exception as error:
            result['searchAfterFailure'] = dict(error=str(error), type=type(error).__name__)
    assert process.returncode == 0 and result['browser']['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--cold-from', type=Path)
    options, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0]]+remaining
    port = 0
    if options.cold_from is not None:
        COLD_FROM = options.cold_from.resolve()
        assert COLD_FROM.parent == ROOT/'.goose/out'
        assert json.loads((COLD_FROM/'command.json').read_text(encoding='utf-8'))['exit_code'] == 0
        previous = json.loads((COLD_FROM/'comparison/observations.json').read_text(encoding='utf-8'))
        assert previous['browser']['passed']
        index = urlsplit(previous['marketSourcesAfter'][0]['url'])
        assert index.scheme == 'http' and index.hostname == '127.0.0.1' and index.path == '/index.json'
        port = index.port
        application.SESSION_ID_PREFIX = 'cold-'
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    FIXTURE = 'http://127.0.0.1:'+str(server.server_port)
    from dsh.util.plugin_detail_http import fetch_body
    async def redirect(url, maximum, signal, options):
        return await fetch_body(FIXTURE+'/files?url='+quote(url, safe=''), maximum, signal, options)
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    def prepare(home):
        if COLD_FROM is not None:
            seed = COLD_FROM/'comparison/home'
            assert seed.is_dir()
            for path in seed.rglob('*'):
                assert not (getattr(path.lstat(), 'st_file_attributes', 0) & 0x400 or path.is_symlink())
            shutil.copytree(str(seed), str(home), dirs_exist_ok=True)
            return
        from dsh.boot.profile import init_profile, PROFILE_TEMPLATES
        init_profile(str(home/'profiles/web'), PROFILE_TEMPLATES['web']['bundles']+['@deepseek-ai/dsh-experimental-plugin-market-bundle'])
    application.PREPARE_HOME = prepare
    application.PLATFORM_PATCHES = [str(ROOT/'migration/candidates/rc022/win7-runtime.patch.yml')]
    application.BEFORE_SESSIONS, application.AFTER_SESSIONS = before, after
    try:
        with patch('dsh.util.plugin_detail_http.fetch_body', redirect):
            code = application.main()
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
    raise SystemExit(code)
