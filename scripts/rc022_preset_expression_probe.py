"""Compare official preset read-only Node path/require expressions."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
EXPRESSION="process.getBuiltinModule('node:path').join(process.getBuiltinModule('node:path').dirname(process.getBuiltinModule('node:module').createRequire(baseUrl).resolve('fixture-preset/package.json')), 'skills')"
EXPRESSIONS=[EXPRESSION,
    "process.getBuiltinModule('node:path').join('', 'skills', '..', 'other')",
    "process.getBuiltinModule('node:path').join()",
    "process.getBuiltinModule('node:path').dirname('name')",
    "process.getBuiltinModule('node:module').createRequire(baseUrl).resolve('fixture-preset/data')",
    "process.getBuiltinModule('node:module').createRequire(baseUrl).resolve('fixture-preset/blocked')",
    "process.getBuiltinModule('node:module').createRequire(baseUrl).resolve('fixture-missing')",
    "process.getBuiltinModule('node:module').createRequire(baseUrl).resolve('node:path')"]


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';directory=WORKSPACE/'node_modules/fixture-preset';directory.mkdir(parents=True)
    package=dict(name='fixture-preset',exports={'.':'./explode.js','./package.json':'./package.json',
        './data':{'import':'./import.json','require':'./require.json'},'./blocked':None})
    (directory/'package.json').write_text(json.dumps(package),encoding='utf-8')
    (directory/'explode.js').write_text('throw Error("resolution must not evaluate this module")',encoding='utf-8')
    for name in ['import.json','require.json']:(directory/name).write_text('{}',encoding='utf-8')
    path=output/'inputs.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),expressions=EXPRESSIONS)),encoding='utf-8');return [path]


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.cordis.loader import evaluate_expr
    ctx=Context();ctx.baseUrl=(workspace or WORKSPACE).as_uri()+'/'
    try:
        rows=[]
        for expression in EXPRESSIONS:
            try:rows.append(dict(value=evaluate_expr(ctx,expression)))
            except Exception as error:rows.append(dict(code=getattr(error,'code',type(error).__name__)))
        return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_preset_expression.mts',prepare=prepare,
        scope='Actual Source evaluate and Native evaluate_expr for shipped preset path/require resolution, read-only exports and require conditions, blocked/missing packages and builtin references.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/cordis/loader.py',ROOT/'dsh/boot/package_resolution.py'])
