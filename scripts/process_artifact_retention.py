import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import xml.etree.ElementTree as ET


FAKE_ARCHIVE = b'exact candidate archive'
MAX_RECEIPT_BYTES = 64 * 1024 * 1024


def native_path(path):
    absolute = os.path.abspath(str(path))
    if os.name != 'nt' or absolute.startswith('\\\\?\\'):
        return absolute
    return '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute


def owned_path(output_root, path, missing=False):
    root = Path(os.path.abspath(str(output_root)))
    if root.resolve() != root:
        raise ValueError('Process output root must not traverse an alias')
    selected = Path(os.path.abspath(str(path)))
    selected.relative_to(root)
    cursor = selected
    while True:
        try:
            information = os.lstat(native_path(cursor))
        except FileNotFoundError:
            if not missing:
                raise
        else:
            if stat.S_ISLNK(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Process artifact reparse points are not owned')
        if cursor == root:
            break
        cursor = cursor.parent
    return selected


def digest_file(path):
    digest = hashlib.sha256()
    with open(native_path(path), 'rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    with open(native_path(path), 'r', encoding='utf-8') as stream:
        return json.load(stream)


def candidate(output_root, path, expected=None):
    try:
        selected = owned_path(output_root, path)
        if selected.name not in ('receipt.json', 'extracted.json'):
            return None
        information = os.lstat(native_path(selected))
        if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= MAX_RECEIPT_BYTES:
            return None
        archive = owned_path(output_root, selected.parent / 'portable.zip')
        archive_info = os.lstat(native_path(archive))
        if not stat.S_ISREG(archive_info.st_mode) or archive_info.st_size != len(FAKE_ARCHIVE):
            return None
        with open(native_path(archive), 'rb') as stream:
            if stream.read() != FAKE_ARCHIVE:
                return None
        if expected is not None:
            result = dict(path=str(selected), size=information.st_size, sha256=digest_file(selected))
            return result if result == expected else None
        with open(native_path(selected), 'rb') as stream:
            payload = stream.read(MAX_RECEIPT_BYTES + 1)
        if len(payload) != information.st_size:
            return None
        report = json.loads(payload.decode('utf-8'))
        if not isinstance(report, dict) or 'runtime' not in report:
            return None
        runtime = report['runtime']
        if runtime is not None and (not isinstance(runtime, dict) or runtime.get('checks') != ['actual runtime']):
            return None
        return dict(path=str(selected), size=information.st_size, sha256=hashlib.sha256(payload).hexdigest())
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def execution_workspace(output_root, output, mapping, missing=False):
    """Validate an explicit release mapping without trusting an arbitrary temp path."""
    retained = Path(output) / 'pytest-workspace'
    if Path(mapping['retained_path']) != retained:
        raise ValueError('Retained process artifact owner differs')
    if 'format' not in mapping:
        execution = owned_path(output_root, mapping['execution_path'], missing=missing)
        if execution.parent != Path(os.path.abspath(str(output_root))) or not execution.name.startswith('g-'):
            raise ValueError('Short execution workspace owner differs')
        return execution
    parent = Path(tempfile.gettempdir()).resolve()
    if mapping['format'] != 'dsh-release-workspace@2' or mapping.get('temporary_parent') != str(parent):
        raise ValueError('System temporary workspace owner differs')
    execution = Path(mapping['execution_path'])
    if not execution.is_absolute() or execution.parent != parent or not re.fullmatch(r'g-[a-z0-9_]{8}', execution.name):
        raise ValueError('Short execution workspace owner differs')
    try:
        parent.relative_to(Path(output_root).resolve())
    except ValueError:
        pass
    else:
        raise ValueError('System temporary workspace must be external')
    return owned_path(parent, execution, missing=missing)


def active_workspace_root(output_root, workspace, owner=None):
    """Authorize only the mapped active external workspace, never its siblings."""
    try:
        owned_path(output_root, workspace)
        return Path(os.path.abspath(str(output_root)))
    except (ValueError, OSError):
        if not owner:
            raise
    output = owned_path(output_root, owner)
    mapping = read_json(owned_path(output_root, output / 'pytest-workspace-mapping.json'))
    execution = execution_workspace(output_root, output, mapping)
    if execution != Path(workspace):
        raise ValueError('Active pytest workspace owner differs')
    return execution


def completed_workspace(output_root, output):
    selected = owned_path(output_root, output)
    mapping_path = owned_path(output_root, selected / 'pytest-workspace-mapping.json')
    mapping = read_json(mapping_path)
    retained = selected / 'pytest-workspace'
    if Path(mapping['retained_path']) != retained:
        raise ValueError('Retained process artifact owner differs')
    execution = execution_workspace(output_root, selected, mapping, missing=True)
    if os.path.lexists(native_path(execution)):
        raise ValueError('Process tests are still active')
    validate_completed_xml(output_root, selected / 'pytest.xml')
    return owned_path(output_root, retained)


def validate_completed_xml(output_root, path):
    xml_path = owned_path(output_root, path)
    with open(native_path(xml_path), 'rb') as stream:
        report = ET.parse(stream).getroot()
    suites = [report] if report.tag == 'testsuite' else list(report.findall('testsuite'))
    if not suites or any(int(suite.attrib['tests']) != len(suite.findall('testcase')) or int(suite.attrib['tests']) <= 0 for suite in suites):
        raise ValueError('Completed process test XML is required')


def prune_synthetic_workspace(output_root, workspace, audit):
    workspace = owned_path(output_root, workspace)
    candidates = []
    for child in os.scandir(native_path(workspace)):
        folder = workspace / child.name
        if not child.name.startswith('test_') or not child.is_dir(follow_symlinks=False):
            continue
        for name in ('receipt.json', 'extracted.json'):
            item = candidate(output_root, folder / name)
            if item is not None:
                candidates.append(item)
    return prune_candidates(output_root, candidates, audit)


def prune_finished_test_folder(output_root, workspace, folder):
    try:
        output_root = active_workspace_root(output_root, workspace, os.environ.get('DSH_RELEASE_PYTEST_OUTPUT'))
        workspace = owned_path(output_root, workspace)
        folder = owned_path(output_root, folder)
    except (OSError, ValueError, TypeError):
        return None
    if folder.parent != workspace or not folder.name.startswith('test_') or not folder.is_dir():
        return None
    candidates = []
    for name in ('receipt.json', 'extracted.json'):
        item = candidate(output_root, folder / name)
        if item is not None:
            candidates.append(item)
    return prune_candidates(output_root, candidates, folder / 'unit-receipts-pruned.json')


def prune_candidates(output_root, candidates, audit):
    candidates.sort(key=lambda item: item['path'])
    result = dict(removed_files=0, removed_bytes=0,
        manifest_sha256=hashlib.sha256(json.dumps(candidates, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest(),
        examples=candidates[-32:],
        scope='Only completed owned pytest direct test folders,synthetic runtime marker or explicitly missing runtime,and exact adjacent fake archive. Real archives,inputs,XML,logs,Source/browser observations and unclassified files stay retained.')
    audit = Path(audit)
    if candidates:
        owned_path(output_root, audit, missing=True)
        original_audit = audit
        retry = 0
        while os.path.lexists(native_path(audit)):
            retry += 1
            audit = original_audit.with_name(original_audit.stem + '-retry-' + str(retry) + original_audit.suffix)
            owned_path(output_root, audit, missing=True)
        with open(native_path(audit), 'x', encoding='utf-8') as stream:
            json.dump(dict(result, status='planned', expected_files=len(candidates)), stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        status = 'failed'
        try:
            for item in candidates:
                if candidate(output_root, Path(item['path']), expected=item) != item:
                    raise RuntimeError('Synthetic receipt changed before cleanup')
                os.unlink(native_path(item['path']))
                result['removed_files'] += 1
                result['removed_bytes'] += item['size']
            status = 'completed'
        finally:
            owned_path(output_root, audit)
            with open(native_path(audit), 'w', encoding='utf-8') as stream:
                json.dump(dict(result, status=status, expected_files=len(candidates)), stream, ensure_ascii=False, indent=2)
                stream.write('\n')
    return result


def prune_completed_regression(output_root, output):
    workspace = completed_workspace(output_root, output)
    return prune_synthetic_workspace(output_root, workspace, Path(output) / 'unit-receipts-pruned.json')


def configure_pytest_workspace(config, output_root):
    if config.option.basetemp is not None:
        return None
    root = owned_path(output_root, output_root, missing=True)
    root.mkdir(parents=True, exist_ok=True)
    owned_path(root, root)
    workspace = owned_path(root, tempfile.mkdtemp(prefix='t-', dir=str(root)))
    config.option.basetemp = str(workspace)
    return workspace


def prune_pytest_session(session, exitstatus, output_root):
    if isinstance(exitstatus, bool) or exitstatus not in (0, 1):
        return None
    factory = getattr(session.config, '_tmp_path_factory', None)
    workspace = getattr(factory, '_basetemp', None)
    if workspace is None:
        return None
    owner = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
    try:
        workspace_root = active_workspace_root(output_root, workspace, owner)
        selected = owned_path(workspace_root, workspace)
    except (ValueError, OSError):
        return None
    if owner:
        try:
            output = owned_path(output_root, owner)
        except (ValueError, OSError):
            output = None
        if output is not None:
            mapping = read_json(owned_path(output_root, output / 'pytest-workspace-mapping.json'))
            execution = execution_workspace(output_root, output, mapping)
            if execution == selected:
                retained = owned_path(output_root, mapping['retained_path'], missing=True)
                if retained != output / 'pytest-workspace':
                    raise ValueError('Deferred pytest cleanup owner differs')
                return dict(status='deferred', owner=str(output), workspace=str(selected), exitstatus=int(exitstatus))
    return prune_synthetic_workspace(workspace_root, selected, selected / 'unit-receipts-pruned.json')


def expire_finished_manifests(output_root, folder, keep=2):
    selected = owned_path(output_root, folder)
    if type(keep) is not int or keep < 1:
        raise ValueError('At least one cleanup manifest must be retained')
    obsolete = []
    for child in os.scandir(native_path(selected)):
        if not re.fullmatch(r'unit-receipt-cleanup-(?:687|candidates-v[1-9][0-9]*)\.json', child.name):
            continue
        try:
            path = owned_path(output_root, selected / child.name)
            report = read_json(path)
            if not isinstance(report, dict):
                continue
            items = report.get('candidates', report.get('Receipts'))
            count = report.get('files', report.get('Files'))
            if not isinstance(items, list) or not items or type(count) is not int or count != len(items):
                continue
            if any(not isinstance(item, dict) for item in items):
                continue
            targets = [owned_path(output_root, Path(item.get('path', item.get('Path'))), missing=True) for item in items]
            if any(os.path.lexists(native_path(target)) for target in targets):
                continue
            obsolete.append((os.stat(native_path(path)).st_mtime_ns, path, digest_file(path)))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    removed = []
    for modified, path, expected in sorted(obsolete, reverse=True)[keep:]:
        owned_path(output_root, path)
        if digest_file(path) != expected:
            raise RuntimeError('Expired cleanup manifest changed before removal')
        os.unlink(native_path(path))
        removed.append(dict(path=str(path), sha256=expected))
    return removed


def prune_finished_focus_runs(output_root, folder):
    selected = owned_path(output_root, folder)
    reports = []
    for child in os.scandir(native_path(selected)):
        if not child.name.endswith('.xml') or not child.is_file(follow_symlinks=False):
            continue
        workspace = selected / Path(child.name).stem
        try:
            owned_path(output_root, workspace)
            validate_completed_xml(output_root, selected / child.name)
            log = owned_path(output_root, selected / (workspace.name + '.log'))
            with open(native_path(log), 'r', encoding='utf-8') as stream:
                if not re.search(r'^=+[^\n]*(?:[0-9]+ passed|[0-9]+ failed|[0-9]+ error)[^\n]*=+\s*$', stream.read(), re.M):
                    continue
            result = prune_synthetic_workspace(output_root, workspace, workspace / 'unit-receipts-pruned.json')
            if result['removed_files']:
                reports.append(dict(output=str(workspace), **result))
        except (OSError, ValueError, TypeError, KeyError, ET.ParseError):
            continue
    return reports


def prune_previous_regressions(output_root):
    root = owned_path(output_root, output_root)
    reports = []
    for child in os.scandir(native_path(root)):
        if not child.is_dir(follow_symlinks=False):
            continue
        output = root / child.name
        try:
            summary = read_json(owned_path(root, output / 'summary.json'))
            if summary.get('result') not in ('passed', 'failed'):
                continue
            result = prune_completed_regression(root, output)
            if result['removed_files']:
                reports.append(dict(output=str(output), **result))
        except (OSError, ValueError, TypeError, KeyError, ET.ParseError):
            continue
    return reports


PREFLIGHT_DAMAGE_CASES = ('missing-frontend', 'extra-frontend', 'wrong-target', 'missing-runtime',
    'missing-icu', 'changed-icu-license', 'missing-case-fold', 'changed-case-fold',
    'missing-zstd', 'changed-zstd-license', 'changed-zstd-dictionary', 'missing-sql',
    'changed-sql', 'changed-sql-manifest', 'missing-client', 'changed-client', 'extra-client', 'wrong-build-profile')


def preflight_sources(product_root, frozen):
    if not isinstance(frozen, dict):
        raise ValueError('Frozen preflight inputs must be a mapping')
    product_root = Path(os.path.abspath(str(product_root)))
    sources = {}
    for name, expected in frozen.items():
        ucrt_copy = name in ('vendor/ucrt/ucrt-input.json', 'vendor/ucrt/SDK-LICENSE.rtf', 'vendor/ucrt/REDIST.html') or re.fullmatch(r'vendor/ucrt/x64/[^/]+\.dll', name)
        if not ucrt_copy and not name.startswith(('apps/web/dist/', 'dsh/session/bin/icu/')) and not re.fullmatch(r'packages/[^/]+/[^/]+/lib/client\.js(?:\.map)?', name):
            continue
        if '\\' in name or ':' in name or '..' in Path(name).parts:
            raise ValueError('Invalid frozen preflight input path')
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid frozen preflight input hash')
        path = owned_path(product_root, product_root / name)
        if path.relative_to(product_root).as_posix() != name or not stat.S_ISREG(os.lstat(native_path(path)).st_mode) or digest_file(path) != expected:
            raise ValueError('Preserved preflight original differs from frozen input')
        sources[name] = expected
    return sources


def preflight_test_inputs(output_root, workspace, product_root, owner=None):
    try:
        workspace_root = active_workspace_root(output_root, workspace, owner)
        workspace = owned_path(workspace_root, workspace)
    except (OSError, ValueError):
        return None
    product_root = Path(os.path.abspath(str(product_root)))
    if owner:
        output = owned_path(output_root, owner)
        mapping = read_json(owned_path(output_root, output / 'pytest-workspace-mapping.json'))
        execution = execution_workspace(output_root, output, mapping)
        retained = owned_path(output_root, mapping['retained_path'], missing=True)
        if execution != workspace or retained != output / 'pytest-workspace':
            raise ValueError('Active preflight test owner differs')
        frozen = read_json(owned_path(output_root, output / 'inputs.json'))
    else:
        frontend = read_json(owned_path(product_root, product_root / 'scripts/frontend-inputs.json'))
        frozen = {item['path']: item['sha256'] for item in frontend['files'] + frontend.get('client_files', [])}
        icu_path = owned_path(product_root, product_root / 'dsh/session/bin/icu/icu.json')
        icu = read_json(icu_path)
        frozen['dsh/session/bin/icu/icu.json'] = digest_file(icu_path)
        for group in ('dll_sha256', 'license_sha256'):
            for name, expected in icu[group].items():
                if Path(name).name != name or '/' in name or '\\' in name:
                    raise ValueError('Invalid ICU input name')
                frozen['dsh/session/bin/icu/' + name] = expected
        if os.path.lexists(native_path(product_root / 'vendor/ucrt')):
            from scripts.ucrt_inputs import verify_pinned_ucrt
            ucrt = verify_pinned_ucrt(product_root)
            for row in ucrt['files']:
                frozen['vendor/ucrt/x64/' + row['name']] = row['sha256']
            for name in ('ucrt-input.json', 'SDK-LICENSE.rtf', 'REDIST.html'):
                frozen['vendor/ucrt/' + name] = digest_file(product_root / 'vendor/ucrt' / name)
    return preflight_sources(product_root, frozen)


def prune_preflight_folders(output_root, folders, product_root, frozen, audit):
    product_root = Path(os.path.abspath(str(product_root)))
    sources = preflight_sources(product_root, frozen)
    if not sources:
        return None
    candidates = []
    for folder in folders:
        folder = owned_path(output_root, folder)
        if not re.fullmatch(r'test_invalid_input_fails_befor[0-9]+', folder.name) or not folder.is_dir():
            raise ValueError('Finished preflight folder differs')
        for name, expected in sources.items():
            try:
                path = owned_path(output_root, folder / 'checkout' / name)
                information = os.lstat(native_path(path))
                if stat.S_ISREG(information.st_mode) and information.st_nlink == 1 and digest_file(path) == expected:
                    candidates.append(dict(path=str(path), source=name, size=information.st_size, sha256=expected))
            except FileNotFoundError:
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item['path'])
    audit = Path(audit)
    original_audit = audit
    suffix = 0
    while os.path.lexists(native_path(audit)):
        suffix += 1
        audit = original_audit.with_name(original_audit.stem + '-retry-' + str(suffix) + '.json')
    owned_path(output_root, audit, missing=True)
    result = dict(status='planned', removed_files=0, removed_bytes=0, expected_files=len(candidates),
        manifest_sha256=hashlib.sha256(json.dumps(candidates, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest(),
        examples=candidates[-32:], scope='Only unchanged private shell/client/ICU/UCRT copies after an owned preflight test body finishes; frozen inputs and preserved originals must match. Modified variants, shared files, unknown files, active tests, actual observations, logs, XML and ZIPs remain.')
    with open(native_path(audit), 'x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    result['status'] = 'failed'
    try:
        for item in candidates:
            path = owned_path(output_root, item['path'])
            source = owned_path(product_root, product_root / item['source'])
            information = os.lstat(native_path(path))
            if not stat.S_ISREG(information.st_mode) or information.st_nlink != 1 or information.st_size != item['size'] or digest_file(path) != item['sha256'] or digest_file(source) != item['sha256']:
                raise RuntimeError('Preflight copy or preserved original changed before cleanup')
            os.unlink(native_path(path))
            result['removed_files'] += 1
            result['removed_bytes'] += item['size']
        result['status'] = 'completed'
    finally:
        owned_path(output_root, audit)
        with open(native_path(audit), 'w', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
    return result


def prune_finished_preflight_folder(output_root, workspace, folder, product_root, frozen):
    output_root = active_workspace_root(output_root, workspace, os.environ.get('DSH_RELEASE_PYTEST_OUTPUT'))
    workspace = owned_path(output_root, workspace)
    folder = owned_path(output_root, folder)
    if folder.parent != workspace:
        raise ValueError('Finished preflight folder owner differs')
    return prune_preflight_folders(output_root, [folder], product_root, frozen, folder / 'preflight-copies-pruned.json')


def prune_preflight_copies(output_root, output, product_root):
    output = owned_path(output_root, output)
    workspace = completed_workspace(output_root, output)
    with open(native_path(owned_path(output_root, output / 'pytest.xml')), 'rb') as stream:
        report = ET.parse(stream).getroot()
    cases = [case for case in report.iter('testcase') if case.attrib.get('classname') == 'tests.test_release_preflight'
        and case.attrib.get('name', '').startswith('test_invalid_input_fails_before_release_replacement[')]
    generations = (PREFLIGHT_DAMAGE_CASES[:14], PREFLIGHT_DAMAGE_CASES)
    actual = {case.attrib['name'] for case in cases}
    if not any(len(cases) == len(generation) and actual == {
            'test_invalid_input_fails_before_release_replacement[' + damage + ']' for damage in generation}
            for generation in generations) or any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped')):
        return None
    frozen = read_json(owned_path(output_root, output / 'inputs.json'))
    folders = [workspace / child.name for child in os.scandir(native_path(workspace))
        if re.fullmatch(r'test_invalid_input_fails_befor[0-9]+', child.name) and child.is_dir(follow_symlinks=False)]
    return prune_preflight_folders(output_root, folders, product_root, frozen, output / 'preflight-copies-pruned.json')


def prune_previous_preflight_copies(output_root, product_root):
    root = owned_path(output_root, output_root)
    reports = []
    for child in os.scandir(native_path(root)):
        if not child.is_dir(follow_symlinks=False):
            continue
        output = root / child.name
        try:
            summary = read_json(owned_path(root, output / 'summary.json'))
            if summary.get('result') not in ('passed', 'failed'):
                continue
            result = prune_preflight_copies(root, output, product_root)
            if result is not None:
                reports.append(dict(output=str(output), **result))
        except (OSError, ValueError, TypeError, KeyError, ET.ParseError):
            continue
    return reports


def main():
    parser = argparse.ArgumentParser(description='Prune reconstructible completed process test receipts.')
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    output_root = Path(__file__).resolve().parents[1] / '.goose/out'
    result = prune_completed_regression(output_root, arguments.output) if arguments.output else prune_previous_regressions(output_root)
    folder = output_root / 'acp-a4-work'
    expired = expire_finished_manifests(output_root, folder) if folder.is_dir() else []
    focused = prune_finished_focus_runs(output_root, folder) if folder.is_dir() else []
    product_root = Path(__file__).resolve().parents[1]
    copies = prune_preflight_copies(output_root, arguments.output, product_root) if arguments.output else prune_previous_preflight_copies(output_root, product_root)
    print(json.dumps(dict(regressions=result, focused=focused, expired_manifests=expired, preflight_copies=copies), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
