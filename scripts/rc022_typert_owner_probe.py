"""Actual generated artifact ownership through incremental Typert Loader."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
FILES=None
PACKAGE='@deepseek-ai/dsh-schedule'


def generated():
    return """import { z } from 'zod'
import { createTypertRemoteInfo } from '@deepseek-ai/dsh-typert-protocol/remote-info'
let value$schema$value
const value$schema=()=>(value$schema$value ??= z.string())
const $remote=createTypertRemoteInfo({package:'@deepseek-ai/dsh-schedule',methods:{'fixture/echo':{
service:'fixture',invocation:{kind:'direct'},parameters:[{name:'value',source:'json',codec:{mode:'strict',typeSymbol:'Value',create:value$schema,jsonSchema:{type:'string'}}}],
result:{mode:'strict',typeSymbol:'Value',create:value$schema,jsonSchema:{type:'string'}}}}},z)
export const TYPERT={package:'@deepseek-ai/dsh-schedule',face:'host',schemas:[],get invocations(){return $remote.descriptors},model:{services:[],events:[],objects:[]}}
"""


async def observe(files=None):
    from dsh.cordis import Context
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.loader_current import CurrentTypertLoader
    files=Path(files or FILES);ctx=Context();ctx.baseUrl=str(files/'anchor.cjs')
    rows=[SimpleNamespace(options=dict(name=PACKAGE),fiber=SimpleNamespace(),disabled=False),SimpleNamespace(options=dict(name=PACKAGE),fiber=SimpleNamespace(),disabled=False)]
    loader=SimpleNamespace(entries=lambda:rows,harness_plugins={PACKAGE:object},installation_module_roots=[str(files/'node_modules')]);ctx.provide('loader',loader)
    directory=files/'native-package';directory.mkdir();manifest=directory/'package.json';artifact=directory/'host.mjs'
    manifest.write_text(json.dumps(dict(name=PACKAGE,exports={'./typert':dict(default='./host.mjs')})),encoding='utf-8');artifact.write_text(generated(),encoding='utf-8')
    ctx.provide('pluginPackages',SimpleNamespace(packageOf=lambda name,base:dict(manifestPath=str(manifest)) if name==PACKAGE else None))
    await ctx.plugin(CurrentTypertRegistry);fiber=await ctx.plugin(CurrentTypertLoader);registry=ctx.typert;answer=[]
    def snapshot(step):
        row=registry.local.get('fixture/echo');answer.append(dict(step=step,packages=len(registry.listPackages()),strict=row is not None,**(dict(value=row['parameters'][0]['codec']['schema'].parse('native')) if row is not None else {})))
    async def change(row):
        ctx.emit('internal/plugin',SimpleNamespace(entry=row))
        for _ in range(10):await asyncio.sleep(0)
    try:
        snapshot('mounted');rows[0].disabled=True;await change(rows[0]);snapshot('one-disabled')
        rows[1].disabled=True;await change(rows[1]);snapshot('all-disabled')
        artifact.write_text('broken after initial import',encoding='utf-8');rows[0].disabled=False;await change(rows[0]);snapshot('cached-remount')
        await fiber.dispose();snapshot('disposed')
    finally:await ctx.fiber.dispose()
    return answer


def prepare(output):
    global FILES
    FILES=output/'files';FILES.mkdir();(FILES/'generated.mjs').write_text(generated(),encoding='utf-8');path=output/'inputs.json';path.write_text(json.dumps(dict(files=str(FILES))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_typert_owner.mts','Current canonical package artifact over historical installation fallback, actual generated strict codec, duplicate Loader ownership, disable/remount cached manifest and disposal.',[Path(__file__).resolve(),ROOT/'dsh/typert/loader.py',ROOT/'dsh/typert/loader_current.py'],prepare=prepare)
