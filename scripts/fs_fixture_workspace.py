"""Own isolated FS oracle fixtures through the last Root/Portable consumer."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'dsh-fs-fixture-workspace@1'


def native_path(path):
    value = os.path.abspath(str(path))
    if os.name != 'nt' or value.startswith('\\\\?\\'):
        return value
    return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value


def digest(path):
    with open(native_path(path), 'rb') as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def write_json(path, value):
    with open(native_path(path), 'x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def read_json(path):
    with open(native_path(path), 'r', encoding='utf-8') as stream:
        return json.load(stream)


def owned_root(record):
    parent = Path(record['temporaryParent'])
    selected = Path(record['path'])
    if (record.get('format') != FORMAT or not parent.is_absolute() or not selected.is_absolute()
            or selected.parent != parent or not re.fullmatch(r'dsh-fs-[a-z0-9_]{8}', selected.name)
            or parent.resolve() != parent or selected.resolve() != selected):
        raise ValueError('FS fixture owner differs')
    try:
        selected.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError('FS fixture must be outside the repository')
    information = os.lstat(native_path(selected))
    if not stat.S_ISDIR(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400:
        raise ValueError('FS fixture owner must be an ordinary directory')
    return selected


def inventory(root):
    files = {}
    directories = []
    for directory, folders, names in os.walk(native_path(root), followlinks=False):
        for name in folders + names:
            path = os.path.join(directory, name)
            information = os.lstat(path)
            if stat.S_ISLNK(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400:
                raise ValueError('FS fixture reparse point refused')
            relative = os.path.relpath(path, native_path(root)).replace('\\', '/')
            if '..' in PurePosixPath(relative).parts:
                raise ValueError('FS fixture path escapes its owner')
            if name in names:
                if not stat.S_ISREG(information.st_mode):
                    raise ValueError('FS fixture non-file refused')
                if information.st_nlink != 1:
                    raise ValueError('FS fixture shared hardlink refused')
                files[relative] = dict(bytes=information.st_size, sha256=digest(path),
                    readonly=bool(getattr(information, 'st_file_attributes', 0) & 1))
            else:
                directories.append(relative)
    return dict(files=files, directories=sorted(directories))


def allocate(output):
    output = Path(output).resolve()
    marker = output.with_suffix('.fixture-owner.json')
    if marker.exists():
        raise ValueError('Fresh FS fixture owner required')
    parent = Path(tempfile.gettempdir()).resolve()
    try:
        parent.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError('FS fixture must be outside the repository')
    selected = Path(tempfile.mkdtemp(prefix='dsh-fs-', dir=str(parent))).resolve()
    record = dict(format=FORMAT, ownerOutput=str(output), temporaryParent=str(parent),
                  path=str(selected), state='allocated')
    owned_root(record)
    write_json(marker, record)
    return selected


def mark_ready(output):
    output = Path(output).resolve()
    marker = output.with_suffix('.fixture-owner.json')
    record = read_json(marker)
    if record['ownerOutput'] != str(output) or record['state'] != 'allocated':
        raise ValueError('FS fixture producer owner differs')
    source = output.with_suffix('.source.json')
    native = output.with_suffix('.native.json')
    selected = owned_root(record)
    record.update(inventory(selected))
    record.update(state='ready',
                  sourceSha256=digest(source), nativeSha256=digest(native))
    with open(native_path(marker), 'w', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')


def cleanup(output, audit=None):
    """Prune only a matched pair's unchanged, explicitly owned fixture bytes."""
    if __package__:
        from scripts.fs_values_oracle import complete_digest, identity
    else:
        from fs_values_oracle import complete_digest, identity
    output = Path(output).resolve()
    marker = output.with_suffix('.fixture-owner.json')
    if not marker.exists():
        return None  # Historical observers retain their existing workspace.
    record = read_json(marker)
    if record['ownerOutput'] != str(output) or record['state'] != 'ready':
        raise ValueError('FS fixture is not a completed owned producer')
    result = read_json(output)
    source_path, native_file = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if digest(source_path) != record['sourceSha256'] or digest(native_file) != record['nativeSha256']:
        raise ValueError('FS fixture observations changed before cleanup')
    source, native = read_json(source_path), read_json(native_file)
    expected = identity(source, ROOT / 'reference', check_files=False)
    if (result.get('status') != 'matched' or result.get('cases') != len(source['rows'])
            or result.get('observationsSha256') != expected or complete_digest(native['rows']) != expected
            or source['fixtureWorkspace'] != record['path'] or native['fixtureWorkspace'] != record['path']):
        raise ValueError('FS fixture complete matching observations required')
    selected = owned_root(record)
    if inventory(selected) != dict(files=record['files'], directories=record['directories']):
        raise ValueError('FS fixture bytes changed or unknown files appeared')
    audit = Path(audit).resolve() if audit else output.with_suffix('.fixture-cleanup.json')
    report = dict(status='started', path=str(selected), ownerOutput=str(output),
                  sourceSha256=record['sourceSha256'], nativeSha256=record['nativeSha256'],
                  removedFiles=len(record['files']), removedBytes=sum(row['bytes'] for row in record['files'].values()),
                  scope='Only matched, unchanged, isolated oracle fixtures after their last consumer. Source/native observations and unresolved failures retained.')
    write_json(audit, report)
    try:
        # Attachment fixtures deliberately publish immutable objects. Change
        # only the verified owned fixture's read-only bit before deletion.
        for name, item in record['files'].items():
            if item['readonly']:
                os.chmod(native_path(selected / name), stat.S_IREAD | stat.S_IWRITE)
        shutil.rmtree(native_path(selected))
        report['status'] = 'completed'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = dict(name=type(error).__name__, message=str(error))
        raise
    finally:
        with open(native_path(audit), 'w', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
    return report
