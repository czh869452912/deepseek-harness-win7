"""Actual child process observations over the same Node executable and scripts."""
import asyncio
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[dict(code="process.stdout.write('CPU '+String.fromCodePoint(22411,21495))"),
        dict(code="process.stdout.write('private');process.stderr.write('private');process.exitCode=2"),
        dict(missing=True),dict(code='setInterval(()=>{},1000)',timeoutMillis=50),
        dict(code='setInterval(()=>{},1000)',abortMillis=20),
        dict(code='setInterval(()=>{},1000)',preabort=True),
        dict(code='process.stdout.write(Buffer.from([255,254,65,226,130]))')]
    for stream in ['stdout','stderr']:
        for count in [127,128,129,100000]:
            rows.append(dict(code="process.%s.write('x'.repeat(%d))"%(stream,count),maxOutputBytes=128))
        rows.append(dict(code="process.%s.write(String.fromCodePoint(30028).repeat(10000))"%stream,maxOutputBytes=128))
    rows.append(dict(code="process.stdout.write('x'.repeat(128));process.stderr.write('y'.repeat(128))",maxOutputBytes=128))
    return rows


def prepare(output):
    node=Path(sys.argv[sys.argv.index('--node')+1]).resolve()
    path=output/'inputs.json';path.write_text(json.dumps(dict(node=str(node),cases=cases())),encoding='utf-8')
    return [path]


async def observe(node=None):
    from dsh.client.analytics_environment_query_current import queryEnvironment
    from dsh.core.abort import AbortController
    node=str(node or Path(sys.argv[sys.argv.index('--node')+1]).resolve())
    rows=[]
    for entry in cases():
        controller=AbortController();timer=None
        if entry.get('preabort'):controller.abort()
        if 'abortMillis' in entry:timer=asyncio.get_running_loop().call_later(entry['abortMillis']/1000,controller.abort)
        try:
            rows.append(await queryEnvironment(node+'-missing' if entry.get('missing') else node,['-e',entry.get('code','')],
                dict(signal=controller.signal,timeoutMillis=entry.get('timeoutMillis',3000),maxOutputBytes=entry.get('maxOutputBytes',16384))))
        finally:
            if timer:timer.cancel()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_analytics_query.mts','Actual fixed Source execFile versus Native shell-free child processes with identical Node scripts; UTF-8, independent byte budgets, nonzero/spawn failure, timeout, abort, and close settlement.',
        [Path(__file__).resolve(),ROOT/'dsh/client/analytics_environment_query_current.py'],prepare=prepare)
