"""Compare focused event observations with the unchanged fixed Cordis source."""
import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGET='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'


async def native():
    from dsh.cordis import Context, EventSymbol
    ctx=Context();result={};trace=[];held=[]
    def outer(value,next_fn):
        held.append(next_fn);trace.append('outer');answer=next_fn()
        try:next_fn()
        except Exception as error:result['repeat']=str(error)
        return answer+'-outer'
    def inner(value,next_fn):
        result['independent']=next_fn is not held[0];trace.append('inner');return next_fn()+'-inner'
    ctx.on('chain',outer);ctx.on('chain',inner)
    result['value']=ctx.waterfall_sync('chain','input',lambda:'end');result['trace']=trace
    try:held[0]()
    except Exception as error:result['late']=str(error)
    left,right=EventSymbol('same'),EventSymbol('same');calls=[];observed=[]
    ctx.on('internal/dispatch',lambda mode,name,args,receiver:observed.append([mode,'left' if name is left else 'right',args]))
    ctx.on(left,lambda value:calls.append(['left',value]));ctx.on(right,lambda value:calls.append(['right',value]))
    await ctx.parallel(left,2);ctx.emit(right,3)
    result.update(calls=calls,observed=observed,disposal=[])
    for key in ('__proto__','constructor','toString',EventSymbol('once')):
        counter=[];dispose=ctx.once(key,lambda:counter.append(1));ctx.emit(key);ctx.emit(key)
        result['disposal'].append(dict(count=len(counter),retained=key in ctx.events._hooks,again=dispose()))
    await ctx.fiber.dispose()
    return result


def main(observer='rc022_events.mts', scope=None, extra_inputs=(), prepare=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','node','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();output=args.output.resolve()
    output.relative_to(ROOT/'.goose/out');output.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],encoding='utf-8').strip()==TARGET
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],encoding='utf-8').strip()
    prepared = prepare(output) if prepare is not None else []
    command=[str(args.node.resolve()),str(source/'node_modules/tsx/dist/cli.mjs'),'--tsconfig',str(source/'tsconfig.base.json'),str(ROOT/'scripts/oracles'/observer),str(source),*[str(path) for path in prepared]]
    report=dict(target_upstream=TARGET,command=command,scope=scope or 'Waterfall single-use delegates, symbol identity, parallel observer mode, empty listener key removal. Config resolution/update lifecycle remains separate.')
    start=time.monotonic()
    try:
        result=subprocess.run(command,capture_output=True,timeout=60)
        (output/'source.json').write_bytes(result.stdout);(output/'source.stderr').write_bytes(result.stderr)
        report['source_exit_code']=result.returncode
        if result.returncode:raise RuntimeError('Source observer failed')
        local=asyncio.run(native());(output/'native.json').write_text(json.dumps(local,ensure_ascii=False),encoding='utf-8')
        from scripts.session_format_oracle import json_equal
        assert json_equal(json.loads(result.stdout),local),'Source/native difference'
        report['status']='passed'
        if isinstance(local,list):report['observations']=len(local)
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        report['seconds']=time.monotonic()-start
        paths=[source/'vendor/cordis/src/events.ts',ROOT/'dsh/cordis/events.py',ROOT/'scripts/oracles'/observer,Path(__file__).resolve(),*extra_inputs,*prepared]
        report['inputs']={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(report['status'])


if __name__=='__main__':main()
