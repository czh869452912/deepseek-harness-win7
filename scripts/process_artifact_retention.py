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


def completed_workspace(output_root, output):
    selected = owned_path(output_root, output)
    mapping_path = owned_path(output_root, selected / 'pytest-workspace-mapping.json')
    mapping = read_json(mapping_path)
    retained = selected / 'pytest-workspace'
    if Path(mapping['retained_path']) != retained:
        raise ValueError('Retained process artifact owner differs')
    execution = owned_path(output_root, Path(mapping['execution_path']), missing=True)
    if execution.parent != Path(os.path.abspath(str(output_root))) or not execution.name.startswith('g-'):
        raise ValueError('Short execution workspace owner differs')
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
    try:
        selected = owned_path(output_root, workspace)
    except (ValueError, OSError):
        return None
    owner = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
    if owner:
        try:
            output = owned_path(output_root, owner)
        except (ValueError, OSError):
            output = None
        if output is not None:
            mapping = read_json(owned_path(output_root, output / 'pytest-workspace-mapping.json'))
            execution = owned_path(output_root, mapping['execution_path'])
            if execution == selected:
                retained = owned_path(output_root, mapping['retained_path'], missing=True)
                if execution.parent != Path(output_root) or not execution.name.startswith('g-') or retained != output / 'pytest-workspace':
                    raise ValueError('Deferred pytest cleanup owner differs')
                return dict(status='deferred', owner=str(output), workspace=str(selected), exitstatus=int(exitstatus))
    return prune_synthetic_workspace(output_root, selected, selected / 'unit-receipts-pruned.json')


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


def main():
    parser = argparse.ArgumentParser(description='Prune reconstructible completed process test receipts.')
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    output_root = Path(__file__).resolve().parents[1] / '.goose/out'
    result = prune_completed_regression(output_root, arguments.output) if arguments.output else prune_previous_regressions(output_root)
    folder = output_root / 'acp-a4-work'
    expired = expire_finished_manifests(output_root, folder) if folder.is_dir() else []
    focused = prune_finished_focus_runs(output_root, folder) if folder.is_dir() else []
    print(json.dumps(dict(regressions=result, focused=focused, expired_manifests=expired), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
