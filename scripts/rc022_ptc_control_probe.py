"""Actual process observations for independent output and control channels."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = ROOT


def cases():
    return [dict(name='forged-output', python="import os\nos.write(1, b'{\"type\":\"done\",\"value\":\"forged\"}\\n')\nreturn 42",
                 typescript='process.stdout.write(\'{"type":"done","value":"forged"}\\n\');return 42'),
        dict(name='stderr', python="import os\nos.write(2, '错误🙂'.encode('utf-8'))\nreturn True",
             typescript='process.stderr.write("错误🙂");return true'),
        dict(name='invalid-utf8', python="import os\nos.write(1, b'a\\xffb')\nreturn None",
             typescript='process.stdout.write((await import("node:buffer")).Buffer.from([97,255,98]));return null'),
        dict(name='raw-output-limit', python="import os\nos.write(1, b'x'*10000)\nreturn 42",
             typescript='process.stdout.write("x".repeat(10000));return 42')]


async def observe():
    from dsh.cordis import Context
    from dsh.code_runtime.ptc import PythonPtcRuntime
    ctx = Context()
    await ctx.plugin(PythonPtcRuntime, dict(timeoutMs=5000, maxOutputBytes=1024))
    runtime = ctx.get('ptcRuntime')
    rows = []
    try:
        for case in cases():
            result = await runtime.run(runtime.resolve(dict(program=case['python'], bindings=[], cwd=str(WORKSPACE))))
            projected = dict(error=result['error']['kind']) if 'error' in result else dict(
                logs=''.join(result['logs']), value=result.get('value'))
            rows.append(dict(name=case['name'], result=projected))
        assert not runtime.runs
    finally:
        await ctx.fiber.dispose()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE = output.parent/'tmp'/'workspace'
    WORKSPACE.mkdir()
    path = output/'cases.json'
    path.write_text(json.dumps(dict(cases=cases(), workspace=str(WORKSPACE))), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_control.mts',
        'Actual inherited stdout/stderr cannot become control messages; UTF-8 replacement and raw output byte ceilings. Python uses an authenticated per-run loopback channel, not the Node control descriptor ABI.',
        [Path(__file__).resolve(), ROOT/'dsh/code_runtime/control.py', ROOT/'dsh/code_runtime/process.py', ROOT/'dsh/code_runtime/worker.py'], prepare)
