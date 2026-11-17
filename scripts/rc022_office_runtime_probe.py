"""Qualify exact offline Office copies using isolated current Python modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.office_runtime_inputs import office_runtime_source, bundle_office_runtime


def run_observer(command, candidate, env, log, timeout=90):
    if os.name != 'nt':
        return subprocess.run(command, cwd=str(candidate), env=env, stdout=log,
                              stderr=subprocess.STDOUT, timeout=timeout).returncode
    from dsh.subprocess.windows_process import WindowsJobProcess
    process = WindowsJobProcess(command, cwd=str(candidate), env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pumps = [threading.Thread(target=shutil.copyfileobj, args=(stream, log))
             for stream in (process.stdout, process.stderr)]
    for pump in pumps:
        pump.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            time.sleep(0.02)
        return process.returncode
    finally:
        if process.range_alive():
            process.kill_range()
        process.wait()
        while process.range_alive():
            time.sleep(0.02)
        for pump in pumps:
            pump.join()
        process.stdout.close()
        process.stderr.close()
        process.close_handles()

PROGRAM = '''import asyncio,hashlib,json,sys,ctypes
from pathlib import Path
base=Path(sys.argv[1]).absolute();sys.path.insert(0,str(base))
from dsh.cordis import Context
from dsh.office.plugin_current import CurrentOfficeKitPlugin
from dsh.core.session.current_session import CurrentSessionPlugin
from dsh.typert.current import CurrentTypertRegistry
import dsh.office.plugin_current as provider
async def main():
 report=dict(python=sys.version,bits=ctypes.sizeof(ctypes.c_void_p)*8,module=str(Path(provider.__file__).absolute()))
 ctx=Context()
 await ctx.plugin(CurrentSessionPlugin)
 await ctx.plugin(CurrentTypertRegistry)
 options=dict(outputDirectory=str(base/('outputs-'+str(report['bits']))),fontDirectories=[str(Path('C:/Windows/Fonts')/name) for name in ('arial.ttf','arialbd.ttf','cour.ttf','times.ttf')])
 await ctx.plugin(CurrentOfficeKitPlugin,options)
 try:
  data=(base/'input.docx').read_bytes()
  async def read(signal,maximum):return dict(bytes=data,version='one')
  value=await ctx.officeKit.convertTo(dict(extension='docx',source=dict(key='isolated',version='one',bytes=len(data),read=read),format='txt',output=dict(owner='session',name='result.txt')))
  actual=Path(value['path']).read_bytes();assert actual==b'\\xef\\xbb\\xbfOffice preview ready\\r'
  engine=ctx.officeKitEngine.engine;report.update(output_sha256=hashlib.sha256(actual).hexdigest(),output_bytes=len(actual),missingFonts=value['missingFonts'],executable=engine.carrier.executable,package=engine.package)
 finally:await ctx.fiber.dispose()
 report.update(status='passed',activeTasks=len(engine.carrier.active),converters=len(engine.converters),states=len(engine.states))
 assert base in Path(report['module']).parents
 assert not engine.carrier.active and not engine.converters and not engine.states
 Path(sys.argv[2]).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
asyncio.run(main())
'''


def main():
    parser = argparse.ArgumentParser()
    for key in ('inputs', 'fixture', 'python64', 'python32', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    out = args.output.absolute()
    assert (ROOT / '.goose/out').absolute() in out.parents
    out.mkdir()
    candidate = out / 'candidate'
    candidate.mkdir()
    def ignore(directory, names):
        ignored = ['__pycache__'] if '__pycache__' in names else []
        if Path(directory).absolute() == (ROOT / 'dsh/office').absolute() and 'bin' in names:
            ignored.append('bin')
        return ignored
    shutil.copytree(str(ROOT / 'dsh'), str(candidate / 'dsh'), ignore=ignore)
    for patch in (ROOT / 'packages/bundle').glob('*/cordis.patch.yml'):
        target = candidate / patch.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(patch), str(target))
    shutil.copyfile(str(args.fixture), str(candidate / 'input.docx'))
    rows = []
    report = dict(command=[sys.executable] + sys.argv, rows=rows,
                  scope='Isolated current dsh module distribution and exact Office runtime copy. Python interpreters are external pinned 3.8.10; this is not complete Portable/release or actual Win7 guest acceptance.')
    script = out / 'observe.py'
    script.write_text(PROGRAM, encoding='utf-8')
    try:
        for architecture, python in [('x64', args.python64), ('x86', args.python32)]:
            source = office_runtime_source(ROOT, args.inputs, architecture)
            manifest = bundle_office_runtime(candidate, source, architecture)
            start = time.monotonic()
            temporary = out / ('tmp-' + architecture)
            temporary.mkdir()
            env = dict(os.environ, TEMP=str(temporary), TMP=str(temporary), DSH_HOME=str(out / ('home-' + architecture)))
            env.pop('PYTHONPATH', None)
            command = [str(python.absolute()), str(script), str(candidate), str(out / (architecture + '.json'))]
            with (out / (architecture + '.log')).open('wb') as log:
                returncode = run_observer(command, candidate, env, log)
            assert returncode == 0, architecture
            observed = json.loads((out / (architecture + '.json')).read_text(encoding='utf-8'))
            row = dict(architecture=architecture, seconds=time.monotonic() - start, resource_count=len(manifest['resources']), observation=observed)
            rows.append(row)
            print(json.dumps(dict(architecture=architecture, status=observed['status'], seconds=row['seconds'])), flush=True)
        report['status'] = 'passed'
    except BaseException as cause:
        report.update(status='failed', error=repr(cause))
        raise
    finally:
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
