import copy
import shutil
import zipfile

import pytest

from scripts import browser108_gate as gate


def valid(tmp_path):
    archive = tmp_path / 'actual-test-archive.zip'
    archive.write_bytes(b'ZIP identity control')
    pin = gate.pinned_input()
    report = dict(passed=True, steps=list(gate.PORTABLE_STEPS), hostExitCode=0, hostErrors='', exceptions=[], consoleErrors=[],
        browserBinarySha256=pin['binary_sha256'], compatibilitySha256='adapter',
        browser=dict(product=pin['protocol_product'], revision=pin['protocol_revision'],
                     userAgent='HeadlessChrome/108.0.5359.0'), archiveSha256=gate.digest(archive),
        capabilitiesBefore=dict(abortSignalAny='undefined', promiseWithResolvers='undefined', abortSignalTimeout='function'),
        capabilitiesAfter=dict(abortSignalAny='function', promiseWithResolvers='function', abortSignalTimeout='function'))
    gate.validate_observation(report, archive, 'adapter')
    return report, archive


@pytest.mark.parametrize('damage', ['absent', 'version', 'revision', 'binary', 'ua', 'adapter', 'zip',
                                  'exception', 'console', 'late', 'already-patched', 'timeout', 'host', 'missing-step'])
def test_zip_bound_observer_rejects_damage_after_valid_baseline(tmp_path, damage):
    report, archive = valid(tmp_path)
    if damage == 'absent':
        report = {}
    elif damage == 'version':
        report['browser']['product'] = 'HeadlessChrome/140.0.0.0'
    elif damage == 'revision':
        report['browser']['revision'] = '@other'
    elif damage == 'binary':
        report['browserBinarySha256'] = 'other'
    elif damage == 'ua':
        report['browser']['userAgent'] = 'Chrome/140'
    elif damage == 'adapter':
        report['compatibilitySha256'] = 'other'
    elif damage == 'zip':
        archive.write_bytes(b'other package')
    elif damage == 'exception':
        report['exceptions'] = ['first exception']
    elif damage == 'console':
        report['consoleErrors'] = ['new failure']
    elif damage == 'late':
        report['capabilitiesAfter']['promiseWithResolvers'] = 'undefined'
    elif damage == 'already-patched':
        report['capabilitiesBefore']['abortSignalAny'] = 'function'
    elif damage == 'timeout':
        report['capabilitiesAfter']['abortSignalTimeout'] = 'undefined'
    elif damage == 'missing-step':
        report['steps'].pop()
    else:
        report['hostExitCode'] = 1
    with pytest.raises(ValueError, match='incomplete or changed'):
        gate.validate_observation(report, archive, 'adapter')


def test_all_fixed_observer_resources_are_required(tmp_path, monkeypatch):
    folder = tmp_path / 'observer'
    binary = folder / 'chrome-win/chrome.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'binary')
    dll = binary.with_name('chrome.dll')
    dll.write_bytes(b'dll')
    pin = dict(files={'chrome-win/chrome.exe': gate.digest(binary), 'chrome-win/chrome.dll': gate.digest(dll)},
               binary_sha256=gate.digest(binary))
    monkeypatch.setattr(gate, 'pinned_input', lambda: pin)
    assert gate.validate_input(binary)['binary_sha256'] == pin['binary_sha256']
    dll.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='changed or missing'):
        gate.validate_input(binary)
    dll.unlink()
    with pytest.raises(ValueError, match='changed or missing'):
        gate.validate_input(binary)


def profile_baseline(tmp_path):
    root = tmp_path / 'portable'
    modules = {}
    for name in ('dsh/host/browser_compat/plugin.py', 'dsh/boot/profile_boot.py'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'owned byte identity control')
        modules[name] = gate.digest(path)
    archive = tmp_path / 'portable.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        for name in modules:
            package.write(root / name, root.name + '/' + name)
    pin = gate.pinned_input()
    reports = {}
    for preset in ('minimal', 'standard', 'cordis'):
        phases = []
        for phase in ('fresh', 'cold'):
            scenarios = ['WEB_REOPEN'] if phase == 'cold' else ['WEB_TOOL', 'WEB_CANCEL'] if preset == 'minimal' else [
                'WEB_TOOL', 'WEB_QUESTION', 'WEB_APPROVAL', 'WEB_CANCEL'] + (['WEB_CORDIS'] if preset == 'cordis' else [])
            phases.append(dict(name=phase, passed=True, hostErrors='', scenarios=scenarios,
                browserBinarySha256=pin['binary_sha256'], browserIdentity=dict(product=pin['protocol_product'],
                    revision=pin['protocol_revision'], userAgent='HeadlessChrome/108.0.5359.0'),
                capabilitiesBefore=dict(any='undefined', withResolvers='undefined', timeout='function'),
                capabilitiesAfter=dict(any='function', withResolvers='function', timeout='function'),
                final=dict(agentStatus='idle', events=[dict(type='assistant/message', data=s + '_FINAL')
                    for s in scenarios if s != 'WEB_CANCEL'], cancellation=[dict(finallyAborted=True, detached=1)]),
                hostReceipt=dict(root=str(root), executable=str(root / 'python.exe'), python='3.8.10 control',
                    phase=phase, preset=preset, exitCode=0, requests=[dict(control='identity')],
                    durableBefore={'state': 'before'}, durableAfter={'state': 'after'}, modules=modules)))
        reports[preset] = dict(status='qualified', side='native', preset=preset, phases=phases,
            errors=[], consoleErrors=[], archiveSha256=gate.digest(archive), compatibilitySha256='adapter')
    gate.validate_profile_journeys(reports, archive, 'adapter', root)
    return reports, archive, root


@pytest.mark.parametrize('damage', ['lane', 'phase', 'scenario', 'result', 'cancel', 'root', 'python',
                                  'interpreter', 'exit', 'module', 'bytes', 'version', 'late', 'zip', 'console'])
def test_profile_journeys_require_all_lanes_and_owned_runtime(tmp_path, damage):
    reports, archive, root = profile_baseline(tmp_path)
    reports = copy.deepcopy(reports)
    phase = reports['standard']['phases'][0]
    host = phase['hostReceipt']
    if damage == 'lane':
        reports.pop('minimal')
    elif damage == 'phase':
        reports['standard']['phases'].pop()
    elif damage == 'scenario':
        phase['scenarios'].pop()
    elif damage == 'result':
        phase['final']['events'].pop()
    elif damage == 'cancel':
        phase['final']['cancellation'][0]['detached'] = 0
    elif damage == 'root':
        host['root'] = str(tmp_path)
    elif damage == 'python':
        host['python'] = '3.9.0'
    elif damage == 'interpreter':
        host['executable'] = str(tmp_path / 'python.exe')
    elif damage == 'exit':
        host['exitCode'] = 1
    elif damage == 'module':
        host['modules'].pop('dsh/boot/profile_boot.py')
    elif damage == 'bytes':
        (root / 'dsh/boot/profile_boot.py').write_bytes(b'changed')
    elif damage == 'version':
        phase['browserIdentity']['product'] = 'HeadlessChrome/140'
    elif damage == 'late':
        phase['capabilitiesAfter']['any'] = 'undefined'
    elif damage == 'zip':
        archive.write_bytes(b'changed')
    else:
        reports['standard']['consoleErrors'].append('first exception')
    with pytest.raises(ValueError):
        gate.validate_profile_journeys(reports, archive, 'adapter', root)


def test_profile_imports_remain_bound_to_zip_after_owned_extraction_cleanup(tmp_path):
    reports, archive, root = profile_baseline(tmp_path)
    shutil.rmtree(root)
    gate.validate_profile_journeys(reports, archive, 'adapter', root, check_files=False)
    with pytest.warns(UserWarning, match='Duplicate name'):
        with zipfile.ZipFile(archive, 'a') as package:
            package.writestr('portable/dsh/boot/profile_boot.py', b'changed')
    # Bind the changed ZIP identity too: import-byte identity must still refuse.
    for report in reports.values():
        report['archiveSha256'] = gate.digest(archive)
    with pytest.raises(ValueError, match='verified ZIP'):
        gate.validate_profile_journeys(reports, archive, 'adapter', root, check_files=False)
