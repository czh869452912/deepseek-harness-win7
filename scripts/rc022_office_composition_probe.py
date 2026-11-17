"""Source Loader expressions used by current Office application composition."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

EXPRESSIONS=["process.getBuiltinModule('node:path').resolve(process.env.DSH_PRIMARY_RUNTIME ?? '')",
 "!process.env.DSH_PRIMARY_RUNTIME","process.env.DSH_PRIMARY_RUNTIME ? 'workspace-dependencies' : 'user'",
 "ctx.get('profileContext')?.name !== 'desktop' || !process.env.DSH_PRIMARY_RUNTIME",
 "ctx.get('profileContext')?.name === 'desktop' && process.env.DSH_PRIMARY_RUNTIME ? 'workspace-dependencies' : 'user'",
 "dshHomePath('office-kit', 'outputs')","dshHomePath('dsh-runtimes', 'dsh-primary-runtime')"]


def cases():
    return [dict(value=value,profile=profile) for profile in [None,'web','desktop','sdk'] for value in [None,'','relative/runtime','C:\\fixture\\runtime']]


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(dict(expressions=EXPRESSIONS,cases=cases(),home=str(ROOT/'.goose/out/fixture-home'))),encoding='utf-8');return [path]


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.loader import evaluate_expr
    rows=[]
    for case in cases():
        ctx=Context();ctx.provide('nativeProcessEnvironment',{} if case['value'] is None else dict(DSH_PRIMARY_RUNTIME=case['value']))
        if case['profile'] is not None:ctx.provide('profileContext',dict(name=case['profile']))
        ctx.provide('dshHomePath',lambda *parts:os.path.join(str(ROOT/'.goose/out/fixture-home'),*parts))
        rows.append([evaluate_expr(ctx,expr) for expr in EXPRESSIONS])
        await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_office_composition.mts',scope='Actual Source Loader evaluation and Native evaluator for all seven selected Office composition expressions, four profile contexts and absent/empty/relative/absolute primary runtime.',prepare=prepare,extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/cordis/loader.py',ROOT/'dsh/boot/app_boot.py',ROOT/'packages/bundle/web-app/cordis.patch.yml',ROOT/'packages/bundle/sdk-app/cordis.patch.yml'])
