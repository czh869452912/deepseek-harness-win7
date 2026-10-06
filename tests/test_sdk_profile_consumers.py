import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import sdk_profile_oracle as oracle
from scripts import sdk_profile_values as values
from scripts.sdk_profile_cases import VALUE_DAMAGES, SOURCE_DAMAGES
from scripts.verify_portable import sdk_profile_receipts


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT
NATIVE_ROOT = ROOT


@pytest.fixture(scope='module')
def paired(tmp_path_factory):
    output = tmp_path_factory.mktemp('sdk-profile') / 'paired.json'
    completed = subprocess.run([sys.executable, str(STAGE / 'scripts/sdk_profile_oracle.py'),
        '--source-root', str(ROOT / 'reference'), '--native-root', str(NATIVE_ROOT), '--output', str(output)],
        capture_output=True, timeout=600)
    assert completed.returncode == 0, completed.stdout + completed.stderr + output.read_bytes()
    source = json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8'))
    native = json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))
    oracle.identity(source, ROOT / 'reference')
    return source, native


@pytest.mark.parametrize('scenario', values.SCENARIOS)
def test_actual_original_and_native_sdk_profile_match(paired, scenario):
    source, native = paired
    oracle.validate_runtime(native, NATIVE_ROOT, sys.executable, source, native['modules'])
    assert len(native['captures'][scenario]['frames']) == values.FRAME_COUNTS[scenario]


DAMAGES = VALUE_DAMAGES


def damage_runtime(report, damage):
    normal = report['captures']['normal']
    cancelled = report['captures']['cancel']
    failed = report['captures']['error']
    if damage == 'missing-scenario':
        del report['captures']['cancel']
    elif damage == 'frame-missing':
        normal['frames'].pop()
    elif damage == 'reply-order':
        normal['frames'][0], normal['frames'][5] = normal['frames'][5], normal['frames'][0]
    elif damage == 'reply-value':
        normal['frames'][0]['result']['foreign'] = True
    elif damage == 'notification-method':
        normal['frames'][1]['method'] = 'session.foreign'
    elif damage == 'session-id':
        normal['frames'][1]['params']['sessionId'] = 'foreign'
    elif damage == 'sequence':
        normal['frames'][1]['params']['event']['seq'] = 999
    elif damage == 'lifecycle':
        next(frame for frame in normal['frames'] if frame.get('method') == 'session.status')['params']['status'] = 'foreign'
    elif damage == 'request-body':
        normal['requests'][0]['temperature'] = 0.1234
    elif damage == 'tool-schema':
        normal['requests'][0]['tools'][0]['function']['description'] += 'foreign'
    elif damage == 'next-model':
        normal['requests'].pop()
    elif damage in ('durable-missing', 'durable-event', 'header'):
        name, payload = next(iter(normal['logs'].items()))
        lines = [json.loads(line) for line in payload.splitlines()]
        if damage == 'durable-missing':
            lines.pop()
        elif damage == 'durable-event':
            lines[1]['data']['foreign'] = True
        else:
            lines[0]['cwd'] = 'foreign'
        normal['logs'][name] = '\n'.join(json.dumps(line) for line in lines) + '\n'
    elif damage.startswith('partial-') or damage == 'cancel-reason':
        name, payload = next(iter(cancelled['logs'].items()))
        lines = [json.loads(line) for line in payload.splitlines()]
        partial = lines[11]
        if damage == 'partial-model':
            partial['data']['message']['source']['model'] = 'mock'
        elif damage == 'partial-marker':
            partial['data']['interrupted'] = False
        elif damage == 'partial-content':
            partial['data']['message']['content'][0]['text'] += 'foreign'
        elif damage == 'partial-causality':
            partial['sourceEventSeqs'] = [7, 9]
        else:
            lines[-1]['data']['reason']['reason']['kind'] = 'foreign'
        cancelled['logs'][name] = '\n'.join(json.dumps(line) for line in lines) + '\n'
    elif damage in ('error-code', 'error-message'):
        error = next(frame['params']['event']['data']['reason']['error'] for frame in failed['frames']
            if frame.get('method') == 'session.event' and frame['params']['event']['type'] == 'turn/end')
        error['code' if damage == 'error-code' else 'message'] = 'foreign'
    elif damage == 'clock-window':
        normal['endedAt'] = normal['startedAt'] + 90001
    elif damage == 'clock-type':
        normal['startedAt'] = True
    elif damage == 'diagnostics':
        normal['stderr'] = 'unexpected child error'
    elif damage == 'exit-type':
        normal['exitCode'] = False
    elif damage == 'fixture':
        normal['fixtureErrors'] = [dict(name='ConnectionResetError')]
    elif damage == 'side':
        normal['side'] = 'source'
    elif damage == 'rows':
        report['rows'].pop()
    elif damage == 'module':
        report['modules']['normal']['dsh/sdk/server.py'] = '0' * 64
    elif damage in ('closure-missing', 'closure-extra'):
        modules = normal['runtime']['modules']
        if damage == 'closure-missing':
            del modules['dsh/sdk/server.py']
        else:
            modules['dsh/foreign.py'] = '0' * 64
        report['modules']['normal'] = dict(modules)
    elif damage == 'group-missing':
        del report['modules']['cancel']
    elif damage == 'optional-bytes':
        cancelled['runtime']['modules'][values.OPTIONAL_CANCEL_IMPORT] = '0' * 64
        report['modules']['cancel'] = dict(cancelled['runtime']['modules'])
    elif damage in ('root', 'python', 'executable'):
        report[damage] = 'foreign'
    elif damage == 'workspace':
        report['destinations']['normal'] = 'foreign'
    elif damage.startswith('capture-'):
        normal['runtime'][damage[len('capture-'):]] = 'foreign'
    elif damage != 'bytes':
        raise AssertionError(damage)
    if set(report['captures']) == set(values.SCENARIOS) and damage != 'rows':
        try:
            report['rows'] = values.observations(report['captures'], report['destinations'], 'native')[0]
        except (ValueError, KeyError, TypeError):
            pass


@pytest.mark.parametrize('damage', DAMAGES)
def test_sdk_profile_requires_complete_values_runtime_and_closures(paired, monkeypatch, damage):
    source, original = paired
    native = copy.deepcopy(original)
    expected_modules = copy.deepcopy(native['modules'])
    damage_runtime(native, damage)
    if damage in ('closure-missing', 'closure-extra'):
        expected_modules = copy.deepcopy(native['modules'])
    if damage == 'bytes':
        original_digest = values.digest
        monkeypatch.setattr(values, 'digest', lambda path: '0' * 64 if Path(path).name == 'server.py' else original_digest(path))
    with pytest.raises((ValueError, KeyError, TypeError)):
        oracle.validate_runtime(native, NATIVE_ROOT, sys.executable, source, expected_modules)


@pytest.mark.parametrize('present', [False, True])
def test_cancelled_sdk_observed_import_variants_preserve_approved_bytes(paired, present):
    source, original = paired
    native = copy.deepcopy(original)
    modules = native['captures']['cancel']['runtime']['modules']
    if present:
        modules[values.OPTIONAL_CANCEL_IMPORT] = original['modules']['error'][values.OPTIONAL_CANCEL_IMPORT]
    else:
        modules.pop(values.OPTIONAL_CANCEL_IMPORT, None)
    native['modules']['cancel'] = dict(modules)
    oracle.validate_runtime(native, NATIVE_ROOT, sys.executable, source, original['modules'])


@pytest.mark.parametrize('damage', SOURCE_DAMAGES)
def test_sdk_profile_requires_actual_source_identity(paired, monkeypatch, damage):
    source = copy.deepcopy(paired[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v18.0.0'
    elif damage == 'inputs':
        source['inputs'].pop('reference/apps/cli/src/bin.ts')
    elif damage == 'input-shape':
        source['inputs']['reference/apps/cli/src/bin.ts'] = True
    elif damage == 'bytes':
        original_digest = oracle.digest
        monkeypatch.setattr(oracle, 'digest', lambda path: '0' * 64 if Path(path).name == 'sdk_profile_driver.py' else original_digest(path))
    elif damage == 'row':
        source['rows'].pop()
    elif damage == 'missing-scenario':
        del source['captures']['cancel']
    else:
        source['captures']['normal']['fixtureErrors'] = [dict(name='ConnectionResetError')]
    with pytest.raises((ValueError, KeyError, TypeError)):
        oracle.identity(source, ROOT / 'reference')


@pytest.mark.parametrize('side', ['source', 'native'])
def test_portable_sdk_profile_refuses_partial_receipts(tmp_path, side):
    receipt = tmp_path / 'one.json'
    receipt.write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='Both SDK profile'):
        sdk_profile_receipts(receipt if side == 'source' else None, receipt if side == 'native' else None,
            tmp_path / 'output.json')
