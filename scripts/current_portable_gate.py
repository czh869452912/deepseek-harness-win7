"""Fresh current-candidate qualification using the actual extracted runtime.

The development Node/browser observe the package; they are never on its PATH.
This lane alone establishes neither a complete release nor Windows 7 acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CURRENT_NOTICE = dict(version='2026-09-28.1', namespace='ui-settings-general', storage='cordis-patch',
                      relative_path='home/profiles/web/cordis.patch.yml')
sys.path.insert(0, str(ROOT))
from scripts.rc022_gate_runner import digest, execute
from scripts.rc022_sdk_profile_probe import SOURCE_PATCH, facts, input_identity
from scripts.oracles import sdk_profile_driver as sdk
from scripts.session_format_oracle import json_equal
from scripts.verify_portable import extract, product_environment, verification_workspace


def require(value, message):
    if not value: raise ValueError(message)


def archive_identity(archive, expected_commit, runtime_sha):
    # Reject an unrelated artifact before making an expensive extraction.
    with zipfile.ZipFile(str(archive)) as package:
        provenance = json.loads(package.read('dsh-win7-portable/build-provenance.json').decode('utf-8'))
    require(provenance.get('product_commit') == expected_commit, 'Archive candidate differs')
    require(provenance.get('runtime_inputs_sha256') == runtime_sha, 'Archive runtime data manifest differs')
    return provenance


def extracted_runtime(capture, portable, frozen):
    runtime = capture.get('runtime', {})
    require(runtime.get('root') == str(portable) and runtime.get('python', '').startswith('3.8.10 '),
            'SDK did not import the extracted Python 3.8.10 product')
    modules = runtime.get('modules', {})
    require({'apps/cli/main.py', 'dsh/session/session_log_deepseek_current.py',
             'dsh/llm/deepseek_messages_adapter.py'} <= modules.keys(), 'Extracted SDK import closure is incomplete')
    require(all(frozen.get(name) == value == digest(portable / name) for name, value in modules.items()),
            'Extracted SDK modules differ from frozen candidate')


def runtime_journey(portable, workspace, output, env, architecture):
    command = [str(portable / 'python.exe'), '-I', '-B', '-u', str(ROOT / 'scripts/portable_runtime_probe.py'),
               '--workspace', str(workspace), '--architecture', architecture]
    execute(command, workspace, output, 'runtime', env, 240)
    lines = (output / 'commands/runtime.log').read_text(encoding='utf-8').splitlines()
    rows = [json.loads(line[len('PORTABLE_PROBE '):]) for line in lines if line.startswith('PORTABLE_PROBE ')]
    require(len(rows) == 1 and rows[0].get('result') == 'passed', 'Actual Portable journey missing')
    value = rows[0]['value']
    required = {'dump-' + name for name in ['minimal', 'standard', 'creative', 'web', 'headless']}
    required.update(['creative-export-native-build-pack-install', 'web-real-boot-session-flush',
                     'cold-session-restart-read-surface'])
    require(required <= set(value['steps']), 'Actual installed application journey incomplete')
    return value


def _sdk_journey(source, node, portable, output, frozen):
    options = SimpleNamespace(source_root=source, native_root=portable, native_python=portable / 'python.exe',
                              native_label='extracted', source_patch=SOURCE_PATCH, protocol='messages',
                              tsconfig='tsconfig.base.json', native_environment=product_environment(portable, output))
    rows = []
    for scenario in ['normal', 'error', 'cancel']:
        folder = output / ('sdk-' + scenario); folder.mkdir()
        captures = {side: sdk.run(side, scenario, options, folder) for side in ['source', 'native']}
        extracted_runtime(captures['native'], portable, frozen)
        values = {side: facts(capture, folder) for side, capture in captures.items()}
        for side, value in values.items():
            (folder / (side + '.facts.json')).write_text(json.dumps(value, indent=2), encoding='utf-8')
        equal = json_equal(values['source'], values['native'])
        rows.append(dict(scenario=scenario, equal=equal))
        require(equal, 'Actual extracted SDK facts differ: ' + scenario)
    return rows


def sdk_journey(source, node, portable, output, frozen):
    previous = os.environ['PATH']
    os.environ['PATH'] = str(node.parent) + os.pathsep + previous
    try: return _sdk_journey(source, node, portable, output, frozen)
    finally: os.environ['PATH'] = previous


def office_journey(portable, workspace, output, env, source, architecture):
    # Read shipped code/resources in place, but keep all synthetic input/output
    # under the owned workspace, so qualification cannot mutate the product.
    program = '''import asyncio,ctypes,hashlib,json,sys
from pathlib import Path
import dsh.office.plugin_current as provider
from dsh.cordis import Context
from dsh.office.plugin_current import CurrentOfficeKitPlugin
from dsh.core.session.current_session import CurrentSessionPlugin
from dsh.typert.current import CurrentTypertRegistry
async def main():
 root=Path(sys.executable).resolve().parent; work=Path(sys.argv[1]); ctx=Context()
 assert root in Path(provider.__file__).resolve().parents
 await ctx.plugin(CurrentSessionPlugin);await ctx.plugin(CurrentTypertRegistry)
 await ctx.plugin(CurrentOfficeKitPlugin,dict(outputDirectory=str(work/'office-outputs'),fontDirectories=[str(Path('C:/Windows/Fonts')/name) for name in ('arial.ttf','arialbd.ttf','cour.ttf','times.ttf')]))
 try:
  data=Path(sys.argv[2]).read_bytes()
  async def read(signal,maximum):return dict(bytes=data,version='one')
  value=await ctx.officeKit.convertTo(dict(extension='docx',source=dict(key='extracted',version='one',bytes=len(data),read=read),format='txt',output=dict(owner='session',name='result.txt')))
  actual=Path(value['path']).read_bytes();assert actual==b'\\xef\\xbb\\xbfOffice preview ready\\r'
  engine=ctx.officeKitEngine.engine
  report=dict(module=str(Path(provider.__file__).resolve()),python=sys.version,bits=ctypes.sizeof(ctypes.c_void_p)*8,output_sha256=hashlib.sha256(actual).hexdigest(),output_bytes=len(actual),executable=engine.carrier.executable,package=engine.package)
 finally:await ctx.fiber.dispose()
 assert not engine.carrier.active and not engine.converters and not engine.states
 Path(sys.argv[3]).write_text(json.dumps(report,indent=2),encoding='utf-8')
asyncio.run(main())
'''
    script = output / 'office-observer.py'; script.write_text(program, encoding='utf-8')
    result = output / 'office.json'
    execute([str(portable / 'python.exe'), '-I', '-B', str(script), str(workspace),
             str(source / 'packages/bundle/web-app/tests/fixtures/document-conversion.docx'), str(result)],
            workspace, output, 'office', env, 120)
    report = json.loads(result.read_text(encoding='utf-8'))
    require(report['bits'] == (32 if architecture == 'x86' else 64), 'Office runtime architecture differs')
    return report


def browser_journeys(portable, workspace, output, env, node, browser, browser108, archive, runtime):
    from scripts.browser108_gate import validate_input, validate_observation, prepare_notice_input
    identity108 = validate_input(browser108)
    environment = output / 'host-environment.json'
    environment.write_text(json.dumps(env), encoding='utf-8')
    rows = {}; notice = None
    for name, executable in [('browser', browser), ('browser108', browser108)]:
        result = output / (name + '.json')
        command = [str(node), str(ROOT / 'scripts/portable_browser_oracle.mjs'), '--python', str(portable / 'python.exe'),
                   '--workspace', str(workspace), '--environment', str(environment), '--browser', str(executable),
                   '--output', str(result), '--archive', str(archive)]
        command += ['--notice-version', CURRENT_NOTICE['version'], '--notice-title', 'Preview Notice', '--current-onboarding', 'true']
        command += ['--notice-relative-path', CURRENT_NOTICE['relative_path']]
        if notice: command += ['--notice-input', str(output / 'browser108-notice-input.json')]
        execute(command, workspace, output, name, dict(os.environ), 150)
        rows[name] = json.loads(result.read_text(encoding='utf-8'))
        require(rows[name].get('passed') is True and rows[name].get('hostExitCode') == 0
                and not rows[name].get('hostErrors') and not rows[name].get('exceptions')
                and not rows[name].get('consoleErrors') and rows[name].get('archiveSha256') == digest(archive),
                'Actual original browser journey failed: ' + name)
        if name == 'browser':
            notice = prepare_notice_input(workspace, result, rows[name], notice_config=CURRENT_NOTICE)
            (output / 'browser108-notice-input.json').write_text(json.dumps(notice, indent=2), encoding='utf-8')
    validate_observation(rows['browser108'], archive, runtime['identity']['browserCompatibilitySha256'],
                         notice, rows['browser'], output / 'browser.json', notice_config=CURRENT_NOTICE)
    rows['browser108_input'] = identity108
    return rows


def qualify(args):
    archive, output, source, node = [getattr(args, name).resolve() for name in ['archive', 'output', 'source', 'node']]
    output.relative_to(ROOT / '.goose/out'); output.mkdir(parents=True, exist_ok=False)
    archive_identity(archive, args.expected_commit, digest(ROOT / 'scripts/runtime-inputs.json'))
    frozen = input_identity(source, node)
    archive_hash = digest(archive)
    report = dict(status='failed', archive_sha256=archive_hash, architecture=args.architecture,
                  release_acceptance=False, windows7_acceptance=False)
    (output / 'inputs.json').write_text(json.dumps(frozen, indent=2), encoding='utf-8')
    try:
        with verification_workspace(output / 'report.json', report) as selected:
            workspace = Path(selected)
            portable = extract(archive, workspace)
            provenance = json.loads((portable / 'build-provenance.json').read_text(encoding='utf-8'))
            require(provenance.get('product_commit') == args.expected_commit, 'Archive candidate differs')
            require(provenance.get('runtime_inputs_sha256') == digest(ROOT / 'scripts/runtime-inputs.json'),
                    'Archive runtime data manifest differs')
            require((portable / 'apps/cli/package.json').read_bytes() == (ROOT / 'apps/cli/package.json').read_bytes(),
                    'Archive lost the Native application closure')
            from scripts.office_runtime_inputs import validate_bundled_office_runtime
            validate_bundled_office_runtime(portable, provenance.get('office_runtime_input'))
            env = product_environment(portable, workspace)
            report['runtime'] = runtime_journey(portable, workspace, output, env, args.architecture)
            report['office'] = office_journey(portable, workspace, output, env, source, args.architecture)
            if args.architecture == 'x64':
                report['sdk'] = sdk_journey(source, node, portable, output, frozen['native'])
                report['browsers'] = browser_journeys(portable, workspace, output, env, node,
                    args.browser.resolve(), args.browser108.resolve(), archive, report['runtime'])
            report['status'] = 'passed'
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        report['inputs_unchanged'] = frozen == input_identity(source, node) and archive_hash == digest(archive)
        if not report['inputs_unchanged']: report.update(status='failed', error='Frozen candidate inputs changed')
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if not report['inputs_unchanged']: raise ValueError('Frozen candidate inputs changed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['archive', 'output', 'source', 'node', 'browser', 'browser108']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--architecture', choices=['x64', 'x86'], default='x64')
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    print(qualify(args)['status'], flush=True)


if __name__ == '__main__': main()
