"""Fresh, bounded current Source/paired lanes; not standalone release acceptance."""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rc022_office_runtime_probe import run_observer
from scripts.rc022_sdk_profile_probe import input_identity
from scripts.session_format_oracle import json_equal

TARGET = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
PLAN = ROOT / 'migration/candidates/rc022/release-gate-plan.json'
SEPARATE = {'rc022_application_probe.py', 'rc022_application_python_probe.py',
            'rc022_schedule_application_probe.py', 'rc022_schedule_browser_probe.py',
            'rc022_market_browser_probe.py', 'rc022_office_runtime_probe.py'}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
    return value.hexdigest()


def load_plan():
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    if plan['target_upstream'] != TARGET or plan['node_version'] != 'v24.9.0':
        raise ValueError('Current gate target/toolchain differs')
    if plan.get('source_test_node_version') != 'v24.13.1':
        raise ValueError('Current Windows Source test runtime differs')
    budget = plan.get('source_test_timeout_ms')
    if type(budget) is not int or not 1000 <= budget <= 120000:
        raise ValueError('Invalid Source shared-host test budget')
    scripts = [row['script'] for row in plan['paired']]
    separate = [row['script'] for row in plan['separate']]
    inventory = {'scripts/' + path.name for path in (ROOT / 'scripts').glob('rc022*_probe.py')}
    if (len(scripts) != len(set(scripts)) or set(scripts) & set(separate)
            or set(scripts + separate) != inventory
            or {Path(name).name for name in separate} != SEPARATE):
        raise ValueError('Unaccounted, duplicate or silently omitted current observer')
    tests = plan['source_tests']
    if len(tests) != len(set(tests)) or len(tests) < 476 or len(scripts) < 401:
        raise ValueError('Current contract/test selection shrank')
    for name in tests + scripts:
        if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:
            raise ValueError('Unsafe gate input path')
    exclusions = plan.get('source_platform_exclusions', {})
    if set(exclusions) != {'win32'}:
        raise ValueError('Explicit Source platform policy required')
    seen = set()
    for row in exclusions['win32']:
        name, pattern = row['path'], row['upstream_pattern']
        # **/ also matches a direct child in the upstream glob grammar.
        if (name not in tests or name in seen or not row.get('reason')
                or not (fnmatch.fnmatchcase(name, pattern) or fnmatch.fnmatchcase(name, pattern.replace('**/', '')))):
            raise ValueError('Invalid Source platform exclusion')
        seen.add(name)
    for row in plan['paired']:
        if type(row['timeout_seconds']) is not int or row['timeout_seconds'] < 1:
            raise ValueError('Invalid owned process deadline')
        if row['receipt'] not in ['report', 'summary', 'all_equal']:
            raise ValueError('Unknown current observer receipt')
        if any(Path(name).name != name or name in ['.', '..'] for name in row['disposable_directories']):
            raise ValueError('Invalid disposable asset path')
    return plan


def validate_pair(row, output):
    receipt = output / ('summary.json' if row['receipt'] == 'summary' else 'report.json')
    value = json.loads(receipt.read_text(encoding='utf-8'))
    pin = value.get('target_upstream', value.get('upstream', TARGET))
    if pin != TARGET:
        raise ValueError('Paired receipt names another Source')
    if row['receipt'] == 'report':
        if value.get('status') != 'passed': raise ValueError('Current paired observer did not pass')
        if value.get('inputs_unchanged') is False: raise ValueError('Paired frozen inputs changed')
    elif row['receipt'] == 'all_equal':
        rows = value.get('rows', [])
        if (value.get('all_equal') is not True or not rows or value.get('count') != len(rows)
                or any(item.get('equal') is not True or not json_equal(item['source'], item['native']) for item in rows)):
            raise ValueError('Office contract rows differ or are incomplete')
    else:
        if type(value.get('difference_count')) is not int or value['difference_count'] != 0 or value.get('differences'):
            raise ValueError('Current paired summary contains differences')
        for left, right in [('source_rows', 'native_rows'), ('codec_rows', 'native_rows')]:
            if left in value and (type(value[left]) is not int or value[left] < 1
                    or type(value.get(right)) is not int or value[left] != value[right]):
                raise ValueError('Paired observation counts differ or are empty')
        if 'source_exit_code' in value and value['source_exit_code'] != 0:
            raise ValueError('Source observer did not exit successfully')
    return dict(receipt=receipt.relative_to(output).as_posix(), sha256=digest(receipt))


def unlink_readonly_entry(path):
    """Modern Windows host cleanup: remove this entry, preserving shared attributes."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path.absolute()), 0x10000, 7, None, 3, 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value: raise ctypes.WinError(ctypes.get_last_error())
    try:
        # DELETE | POSIX_SEMANTICS | IGNORE_READONLY_ATTRIBUTE affects this
        # directory entry, unlike chmod/SetFileAttributes on shared hardlinks.
        flags = wintypes.DWORD(0x13)
        if not kernel.SetFileInformationByHandle(handle, 21, ctypes.byref(flags), ctypes.sizeof(flags)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


def remove_owned(path):
    """Unlink reparse points without entering their targets or changing ACLs."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        if stat.S_ISDIR(info.st_mode): os.rmdir(str(path))
        else: path.unlink()
        return 0
    if stat.S_ISDIR(info.st_mode):
        size = sum(remove_owned(child) for child in path.iterdir())
        path.rmdir()
        return size
    deadline = time.monotonic() + 5
    while True:
        try:
            path.unlink()
            break
        except OSError as error:
            if (os.name == 'nt' and getattr(error, 'winerror', None) == 5
                    and getattr(info, 'st_file_attributes', 0) & 1):
                unlink_readonly_entry(path)
                break
            # Chromium's Windows BITS cleanup can briefly hold a file after
            # its process job has closed. Never reset attributes or permissions.
            if getattr(error, 'winerror', None) != 32 or time.monotonic() >= deadline:
                raise
            time.sleep(.1)
    return info.st_size


def retire_success(output, names, receipt_name='gate-cleanup.json'):
    if Path(receipt_name).name != receipt_name or not receipt_name.endswith('.json'):
        raise ValueError('Invalid cleanup receipt name')
    receipt = output / receipt_name
    if receipt.exists(): raise ValueError('Cleanup receipt already exists')
    inventory, observations, assets = [], [], []
    stem = Path(receipt_name).stem
    def snapshot(path):
        info = path.lstat()
        name = path.relative_to(output).as_posix()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            inventory.append(dict(path=name, kind='reparse'))
        elif stat.S_ISDIR(info.st_mode):
            for child in path.iterdir(): snapshot(child)
        else:
            if not stat.S_ISREG(info.st_mode): raise ValueError('Unsupported owned fixture entry')
            row = dict(path=name, kind='file', bytes=info.st_size, sha256=digest(path))
            inventory.append(row)
            if path.suffix.lower() in ['.json', '.jsonl', '.log', '.png', '.zstd']:
                target = output / (stem + '-observations') / path.relative_to(output)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists(): raise ValueError('Observation destination already exists')
                shutil.copyfile(str(path), str(target))
                if target.stat().st_size != info.st_size or digest(target) != row['sha256']:
                    raise ValueError('Preserved cleanup observation differs')
                observations.append(dict(path=target.relative_to(output).as_posix(),
                                         bytes=info.st_size, sha256=row['sha256']))
    for name in names:
        if Path(name).name != name or name in ['.', '..']:
            raise ValueError('Asset escaped its owner')
        path = output / name
        try: path.lstat()
        except FileNotFoundError: continue
        if path.parent.resolve() != output.resolve(): raise ValueError('Asset escaped its owner')
        snapshot(path); assets.append((name, path))
    # Save original observations and an exact inventory before deleting any
    # reconstructible fixture. Failed removals retain both these and the asset.
    (output / (stem + '-inventory.json')).write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    (output / (stem + '-preserved.json')).write_text(json.dumps(observations, indent=2), encoding='utf-8')
    removed = []; size = 0
    for name, path in assets:
        # output is a fresh owned observer directory, with no remaining process
        # or comparison consumer. Only the plan's declared synthetic roots go.
        if path.parent.resolve() != output.resolve(): raise ValueError('Asset escaped its owner')
        size += remove_owned(path); removed.append(name)
    result = dict(removed=removed, bytes_removed=size)
    receipt.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def execute(command, cwd, output, name, environment, timeout):
    commands = output / 'commands'; commands.mkdir(exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix='g-')).resolve()
    env = dict(environment, TEMP=str(workspace), TMP=str(workspace))
    receipt = dict(command=command, cwd=str(cwd), workspace=str(workspace), completed=False)
    path = commands / (name + '.json')
    path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    start = time.monotonic()
    try:
        with (commands / (name + '.log')).open('wb') as log:
            receipt['exit_code'] = run_observer(command, cwd, env, log, timeout=timeout)
        if receipt['exit_code'] != 0: raise RuntimeError('Process failed: ' + name)
    except BaseException as error:
        receipt['error'] = str(error)
        # Preserve this run's raw failed fixture and mapping. A later targeted
        # repair must explicitly retire it after retaining required observations.
        raise
    finally:
        receipt.update(completed=True, seconds=time.monotonic() - start)
        try:
            if receipt.get('exit_code') == 0:
                receipt['temporary_bytes_removed'] = remove_owned(workspace)
        except BaseException as error:
            receipt['cleanup_error'] = str(error)
            raise
        finally:
            path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def source_test_runtime(plan, selected=None):
    node = Path(selected or ROOT / '.goose/tools/node-24.13.1-win-x64/node.exe').resolve()
    if (not node.is_file() or subprocess.check_output([str(node), '--version'], encoding='utf-8').strip()
            != plan['source_test_node_version']):
        raise ValueError('Pinned Windows Source test runtime required')
    return node


def source_exclusions(plan, source, platform=None):
    if (platform or sys.platform) != 'win32': return {}
    text = (source / 'vitest.config.ts').read_text(encoding='utf-8')
    block = re.search(r"const windowsUnsupportedTests = process\.platform === 'win32'\s*\?\s*\[(.*?)\]\s*:\s*\[\]", text, re.S)
    if not block: raise ValueError('Upstream Windows test policy unavailable')
    patterns = set(re.findall(r"(?m)^\s*'([^']+)',?\s*$", block.group(1)))
    rows = plan['source_platform_exclusions']['win32']
    if any(row['upstream_pattern'] not in patterns for row in rows):
        raise ValueError('Source platform exclusion is not declared by upstream')
    return {row['path']: row for row in rows}


def source_lane(plan, source, node, output, environment, only=()):
    selected = list(only) if only else plan['source_tests']
    if not set(selected) <= set(plan['source_tests']): raise ValueError('Unplanned Source test')
    exclusions = source_exclusions(plan, source)
    # The unchanged upstream config applies its shared-host budget to each
    # inline project's tests, hooks and polling. Preserve explicit case limits.
    environment = dict(environment, DSH_COVERAGE_TEST_TIMEOUT_MS=str(plan['source_test_timeout_ms']),
                       PATH=str(node.parent) + os.pathsep + environment.get('PATH', ''))
    rows = []
    for offset in range(0, len(selected), 32):
        batch = selected[offset:offset + 32]
        if any(not (source / name).is_file() for name in batch): raise ValueError('Missing current Source test')
        name = 'source-%03d' % (offset // 32 + 1)
        result = output / (name + '.json')
        command = [str(node), '--expose-internals', str(source / 'node_modules/vitest/vitest.mjs'),
                   'run', *batch, '--maxWorkers=2', '--reporter=default', '--reporter=json', '--outputFile=' + str(result)]
        print(name + ' starting', flush=True)
        executed = execute(command, source, output, name, environment, 900)
        value = json.loads(result.read_text(encoding='utf-8'))
        actual = {Path(item['name']).resolve().relative_to(source).as_posix() for item in value['testResults']}
        expected = set(batch) - set(exclusions)
        if (not value.get('success') or value.get('numFailedTests') != 0 or not value.get('numPassedTests')
                or actual != expected):
            raise ValueError('Source cases failed, disappeared or expanded: ' + name)
        rows.append(dict(name=name, planned_files=batch, files=sorted(actual),
                         upstream_platform_exclusions=[exclusions[name] for name in batch if name in exclusions],
                         passed=value['numPassedTests'],
                         pending=value['numPendingTests'], sha256=digest(result), seconds=executed['seconds'],
                         test_timeout_ms=plan['source_test_timeout_ms']))
        print(name + ' passed ' + str(value['numPassedTests']), flush=True)
    return rows


def paired_lane(plan, source, node, browser, output, environment, only=()):
    selected = [row for row in plan['paired'] if not only or row['script'] in only]
    if only and {row['script'] for row in selected} != set(only): raise ValueError('Unplanned paired observer')
    rows = []
    for row in selected:
        name = Path(row['script']).stem
        destination = output / name
        # Namespace-package entrypoints resolve siblings from the selected
        # checkout without relying on an inherited PYTHONPATH or per-file shim.
        module = Path(row['script']).with_suffix('').as_posix().replace('/', '.')
        command = [sys.executable, '-m', module, '--source', str(source), '--output', str(destination)]
        if row['node']: command += ['--node', str(node)]
        if row['browser']: command += ['--browser', str(browser)]
        print(name + ' starting', flush=True)
        executed = execute(command, ROOT, output, name, environment, row['timeout_seconds'])
        receipt = validate_pair(row, destination)
        if (destination / 'files').exists() and 'files' not in row['disposable_directories']:
            raise ValueError('Undeclared synthetic files fixture: ' + name)
        cleanup = retire_success(destination, row['disposable_directories'])
        rows.append(dict(script=row['script'], **receipt, seconds=executed['seconds'], cleanup=cleanup))
        print(name + ' passed', flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['source', 'node', 'browser', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-test-node', type=Path, help='Pinned Windows Source unit-test runtime, separate from contract Node')
    parser.add_argument('--lane', choices=['source', 'paired'], required=True)
    parser.add_argument('--only', action='append', default=[], help='Explicit planned subset; never a complete lane')
    args = parser.parse_args()
    source, node, browser, output = [getattr(args, name).resolve() for name in ['source', 'node', 'browser', 'output']]
    output.relative_to(ROOT / '.goose/out'); output.mkdir(parents=True, exist_ok=False)
    plan = load_plan()
    if subprocess.check_output([str(node), '--version'], encoding='utf-8').strip() != plan['node_version']:
        raise ValueError('Current development Node differs')
    def source_clean():
        return (subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip() == TARGET
                and not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], encoding='utf-8').strip())
    if not source_clean(): raise ValueError('Unchanged current Source required')
    test_node = source_test_runtime(plan, args.source_test_node) if args.lane == 'source' else None
    environment = {key: value for key, value in os.environ.items()
        if not re.search(r'(?:^|_)(?:API_KEY|API_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|OAUTH_TOKEN)$', key, re.I)
        and key.upper() not in ['DSH_HOME', 'PYTHONPATH', 'PYTHONHOME']}
    environment.update(PATH=str(node.parent) + os.pathsep + environment['PATH'],
                       DSH_TEST_CHROMIUM=str(browser), DSH_TEST_CHROMIUM108=str(browser))
    before = input_identity(source, node)
    if test_node: before['source_test_runtime'] = dict(path=str(test_node), sha256=digest(test_node))
    before['plan'] = digest(PLAN)
    (output / 'inputs.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    report = dict(target_upstream=TARGET, plan_sha256=before['plan'], status='failed', lane=args.lane,
                  complete_lane=not args.only, release_acceptance=False)
    try:
        if args.lane == 'source': report['rows'] = source_lane(plan, source, test_node, output, environment, args.only)
        else: report['rows'] = paired_lane(plan, source, node, browser, output, environment, args.only)
        report['status'] = 'passed'
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        after = input_identity(source, node); after['plan'] = digest(PLAN)
        if test_node: after['source_test_runtime'] = dict(path=str(test_node), sha256=digest(test_node))
        report['inputs_unchanged'] = before == after and source_clean()
        if not report['inputs_unchanged']: report.update(status='failed', error='Frozen current inputs changed')
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if not report['inputs_unchanged']: raise ValueError('Frozen current inputs changed')
    print(report['status'], flush=True)


if __name__ == '__main__':
    main()
