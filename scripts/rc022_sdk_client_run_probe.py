"""Actual SDK clients against the same pinned independently running wire peer."""
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.sdk.client import create_process_deepseek_harness

CASES=ROOT/'tests/fixtures/rc022_sdk_run.json'


async def observe(source=None,node=None):
    source=Path(source or sys.argv[sys.argv.index('--source')+1]);node=Path(node or sys.argv[sys.argv.index('--node')+1])
    rows=[]
    for case in json.loads(CASES.read_text(encoding='utf-8')):
        env=dict(os.environ)
        for key in list(env):
            if key.startswith('QUERY_'):del env[key]
        for key,target in [('result','QUERY_RESULT'),('completion','QUERY_COMPLETION')]:
            if key in case:env[target]=json.dumps(case[key],ensure_ascii=True,separators=(',',':'))
        if 'lifecycle' in case:env['QUERY_LIFECYCLE']=case['lifecycle']
        runtime=dict(command=str(node),args=[str(source/'packages/sdk/client/tests/fixtures/query.ts')],environment=lambda:env,description='query protocol fixture',initializeTimeoutMs=5000,requestTimeoutMs=5000,shutdownTimeoutMs=5000)
        harness=create_process_deepseek_harness(runtime);seen=[]
        def observer(note):
            if case.get('observerError'):raise RuntimeError('observer failed')
            seen.append(note)
        try:
            try:result=dict(value=await harness.run(case.get('input','input'),dict(sessionId='main',onNotification=observer)))
            except Exception as error:result=dict(error=str(error))
            state=await harness.client.request('test/state')
            rows.append(dict(name=case['name'],result=result,seen=seen,queries=state['queries'],subscriptions=len(harness.client.subscriptions)))
        finally:
            await harness.close()
            assert harness.client.child.poll()==0
            assert all(stream.closed for stream in (harness.client.child.stdin,harness.client.child.stdout,harness.client.child.stderr))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sdk_client_run.mts','Actual pinned SDK client and Python client run against the same independently running pinned query protocol fixture. Compare routing result validation, receipt-bounded root/tree activity, command lifecycle/completion ordering, callback errors, and subscription closure.',[Path(__file__).resolve(),CASES,ROOT/'dsh/sdk/run.py',ROOT/'dsh/sdk/client.py',ROOT/'reference/packages/sdk/client/tests/fixtures/query.ts'])
