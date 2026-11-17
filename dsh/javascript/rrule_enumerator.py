"""Private pinned RRULE UTC-wall enumerator on the shipped Win7 engine.

Python owns rule validation, zone resolution and admission. This closed helper
only enumerates prepared recurrence text; it never exposes JavaScript execution
or an installed Node dependency to product callers.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dsh.javascript.runtime import JavaScriptRuntimeError,verify_resources,worker_environment,encode

ASSETS=Path(__file__).with_name('rrule')
MANIFEST_SHA256='66d85f91c6dd0251ee26936f380e25018d7db823f196536b26f96176106b00d4'


def bootstrap():
    raw=(ASSETS/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA256:raise JavaScriptRuntimeError('RRULE enumeration manifest differs')
    manifest=json.loads(raw)
    for name,expected in manifest['resources'].items():
        if Path(name).name!=name or ':' in name:raise JavaScriptRuntimeError('RRULE enumeration path differs')
        if hashlib.sha256((ASSETS/name).read_bytes()).hexdigest()!=expected:raise JavaScriptRuntimeError('RRULE enumeration resource differs: '+name)
    return (ASSETS/'rrule.min.js').read_text(encoding='utf-8')+'\n'+(ASSETS/'driver.js').read_text(encoding='utf-8')


def enumerate_wall(recurrence,anchor,from_wall,through=None,limit=2048,mode='window'):
    if mode not in ('window','after') or type(limit) is not int or not 1<=limit<=10080:raise ValueError('Invalid private RRULE query')
    query=dict(recurrence=recurrence,anchor=anchor,mode=mode,**{'from':from_wall},through=through,limit=limit)
    request=dict(body='return null',name='rrule-utc-wall',timeoutMs=15000,query=query,bootstrap=bootstrap())
    completed=subprocess.run([str(verify_resources())],input=encode(request)+encode(dict(type='go')),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=worker_environment(),timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:frames=[json.loads(line.decode('utf-8')) for line in completed.stdout.splitlines()]
    except (ValueError,UnicodeError) as error:raise JavaScriptRuntimeError('RRULE enumeration returned invalid protocol data') from error
    if completed.returncode!=0 or len(frames)!=2 or frames[0]!=dict(type='ready') or frames[1].get('type')!='terminal' or 'result' not in frames[1]:
        raise JavaScriptRuntimeError('RRULE enumeration failed: '+completed.stderr.decode('utf-8',errors='replace')+'\n'+completed.stdout.decode('utf-8',errors='replace'))
    result=frames[1]['result']
    valid=(result is None or type(result) is int) if mode=='after' else isinstance(result,list) and len(result)<=limit and all(type(value) is int for value in result)
    if not valid:raise JavaScriptRuntimeError('RRULE enumeration returned an invalid result shape')
    return result
