"""Actual file observations for guarded atomic replacement against fixed Source."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

OUTPUT=None


def cases():
    return [dict(initial=initial,new=new,mode=mode)
            for initial in ('[]','[]\r\n','[{"id":"first"}]','[{"value":"\u6587\u6863"}]')
            for new in ('[]','[{"id":"second"}]') for mode in ('same','stale','missing','unconditional')]


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def native():
    from dsh.cordis import Context
    from dsh.cordis.include import Include
    output=OUTPUT/'files'/'native';output.mkdir(parents=True)
    result=[]
    for index,case in enumerate(cases()):
        path=output/('%s.json'%index);path.write_bytes(case['initial'].encode('utf-8'))
        ctx=Context();include=Include(ctx,{'path':str(path)})
        if case['mode']=='missing':path.unlink()
        elif case['mode']=='stale':path.write_bytes(b'["external"]')
        error=None
        try:
            if case['mode']=='unconditional':await include._write_text(case['new'])
            else:await include._write_text(case['new'],case['initial'])
        except Exception as reason:error=type(reason).__name__
        result.append([error,path.read_bytes().decode('utf-8') if path.exists() else None,len(list(output.glob('.*.tmp')))])
        await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_include_atomic.mts',prepare=prepare,
        scope='Actual guarded/unconditional file replacement with exact UTF-8/CRLF bytes, externally changed and missing files, temporary cleanup. Queue integration remains separate.',
        extra_inputs=[ROOT/'dsh/cordis/include.py',ROOT/'scripts/rc022_include_atomic_probe.py',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/include/src/index.ts'])
