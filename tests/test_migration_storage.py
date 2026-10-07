import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location('migration_storage',
    Path(__file__).resolve().parents[1] / 'scripts/migration_storage.py')
storage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storage)


def git(root, *args, **kwargs):
    return subprocess.check_output(['git', '-C', str(root)] + list(args), **kwargs).strip()


def save_proof(root, record):
    (root / 'migration/storage/lfs-transport.json').write_text(json.dumps(record), encoding='utf-8')


@pytest.fixture
def converted(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    git(root, 'init', '-b', 'master')
    git(root, 'config', 'user.name', 'Storage verification')
    git(root, 'config', 'user.email', 'storage@example.invalid')
    git(root, 'config', 'core.autocrlf', 'false')
    (root / 'product.py').write_text('unchanged product\n', encoding='utf-8')
    (root / '.gitattributes').write_bytes(b'migration/** text eol=lf\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'published base')
    base = git(root, 'rev-parse', 'HEAD').decode()
    archive_path = root / 'migration/evidence/artifacts/sample.zip'
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(b'exact archived bytes\x00\xff')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'original acceptance')
    old = git(root, 'rev-parse', 'HEAD').decode()
    reader = storage.GitObjects(root)
    old_body = reader.read(old, 'commit')
    original_objects = {('commit', old): old_body}

    def collect(oid):
        body = reader.read(oid, 'tree')
        original_objects['tree', oid] = body
        for name, (mode, child) in storage.tree_entries(body).items():
            if mode == b'40000':
                collect(child)
            elif name == b'.gitattributes':
                original_objects['blob', child] = reader.read(child, 'blob')

    old_tree = storage.commit_parts(old_body)[0]
    collect(old_tree)
    reader.close()
    size, blob, digest = storage.file_digests(archive_path)
    pointer = ('version https://git-lfs.github.com/spec/v1\noid sha256:' + digest
        + '\nsize ' + str(size) + '\n').encode('ascii')
    pointer_oid = git(root, 'hash-object', '-w', '--stdin', input=pointer).decode()
    git(root, 'update-index', '--cacheinfo', '100644', pointer_oid, 'migration/evidence/artifacts/sample.zip')
    (root / '.gitattributes').write_bytes(b'migration/** text eol=lf\n' + storage.TRACKING + b'\n')
    git(root, 'add', '.gitattributes')
    new_tree = git(root, 'write-tree').decode()
    new_body = old_body.replace(('tree ' + old_tree).encode(), ('tree ' + new_tree).encode(), 1)
    new = git(root, 'hash-object', '-t', 'commit', '-w', '--stdin', input=new_body).decode()
    git(root, 'update-ref', 'refs/heads/master', new)
    folder = root / 'migration/storage'
    folder.mkdir(parents=True)
    metadata = folder / 'original-git-metadata.zip'
    with zipfile.ZipFile(str(metadata), 'w', zipfile.ZIP_DEFLATED) as package:
        for (kind, oid), body in original_objects.items():
            package.writestr(kind + '/' + oid, body)
    mapping = folder / 'lfs-map.csv'
    with mapping.open('w', encoding='utf-8', newline='') as stream:
        csv.writer(stream, lineterminator='\n').writerow([old, new])
    record = dict(schema_version=1, original_tip=old, rewritten_tip=new, remote_base=base,
        mapping_path='migration/storage/lfs-map.csv', mapping_sha256=hashlib.sha256(mapping.read_bytes()).hexdigest(),
        objects_path='migration/storage/original-git-metadata.zip', objects_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),
        archives=[dict(path=archive_path.relative_to(root).as_posix(), git_blob=blob, sha256=digest, size=size)])
    save_proof(root, record)
    return root, record, old_body, original_objects


def replace_converted_tree(root, record, old_body):
    new_tree = git(root, 'write-tree').decode()
    old_tree = storage.commit_parts(old_body)[0]
    new_body = old_body.replace(('tree ' + old_tree).encode(), ('tree ' + new_tree).encode(), 1)
    new = git(root, 'hash-object', '-t', 'commit', '-w', '--stdin', input=new_body).decode()
    git(root, 'update-ref', 'refs/heads/master', new)
    mapping = root / record['mapping_path']
    mapping.write_text(record['original_tip'] + ',' + new + '\n', encoding='utf-8')
    record.update(rewritten_tip=new, mapping_sha256=hashlib.sha256(mapping.read_bytes()).hexdigest())
    save_proof(root, record)


def test_exact_conversion_and_no_manifest_behavior(converted, tmp_path):
    root, record, _, _ = converted
    assert storage.verify_rewrite(root) == {record['original_tip']: record['rewritten_tip']}
    assert storage.verify_rewrite(tmp_path) == {}


def test_conversion_verified_in_clone_without_original_commit_objects(converted, tmp_path):
    root, record, _, _ = converted
    clone = tmp_path / 'clone'
    environment = dict(os.environ, GIT_LFS_SKIP_SMUDGE='1')
    subprocess.check_call(['git', 'clone', '--no-local', str(root), str(clone)], env=environment)
    assert subprocess.call(['git', '-C', str(clone), 'cat-file', '-e', record['original_tip']],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0
    shutil.copytree(str(root / 'migration/storage'), str(clone / 'migration/storage'))
    shutil.copyfile(str(root / record['archives'][0]['path']), str(clone / record['archives'][0]['path']))
    assert storage.verify_rewrite(clone) == {record['original_tip']: record['rewritten_tip']}


@pytest.mark.parametrize('damage', ['mapping', 'metadata', 'malformed-metadata', 'archive', 'wrong-head', 'unrelated-map'])
def test_invalid_proofs_and_archive_changes_rejected(converted, damage):
    root, record, _, _ = converted
    if damage == 'mapping':
        (root / record['mapping_path']).write_text('changed\n', encoding='utf-8')
    elif damage in ('metadata', 'malformed-metadata'):
        (root / record['objects_path']).write_bytes(b'changed')
        if damage == 'malformed-metadata':
            record['objects_sha256'] = hashlib.sha256((root / record['objects_path']).read_bytes()).hexdigest()
            save_proof(root, record)
    elif damage == 'archive':
        (root / record['archives'][0]['path']).write_bytes(b'changed archive')
    elif damage == 'wrong-head':
        git(root, 'update-ref', 'refs/heads/master', record['remote_base'])
    else:
        path = root / record['mapping_path']
        with path.open('a', encoding='utf-8') as stream:
            stream.write('a' * 40 + ',' + 'b' * 40 + '\n')
        record['mapping_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        save_proof(root, record)
    with pytest.raises(storage.StorageError):
        storage.verify_rewrite(root)


@pytest.mark.parametrize('damage', ['code', 'mode', 'attributes', 'pointer', 'extra-file'])
def test_mapping_cannot_authorize_other_tree_changes(converted, damage):
    root, record, old_body, _ = converted
    if damage == 'code':
        (root / 'product.py').write_text('changed product\n', encoding='utf-8')
        git(root, 'add', 'product.py')
    elif damage == 'mode':
        git(root, 'update-index', '--chmod=+x', 'product.py')
    elif damage == 'attributes':
        (root / '.gitattributes').write_bytes(b'* text eol=crlf\n' + storage.TRACKING + b'\n')
        git(root, 'add', '.gitattributes')
    elif damage == 'pointer':
        pointer = git(root, 'hash-object', '-w', '--stdin', input=b'fake pointer').decode()
        git(root, 'update-index', '--cacheinfo', '100644', pointer, record['archives'][0]['path'])
    else:
        (root / 'extra.py').write_text('extra product\n', encoding='utf-8')
        git(root, 'add', 'extra.py')
    replace_converted_tree(root, record, old_body)
    with pytest.raises(storage.StorageError):
        storage.verify_rewrite(root)


def test_original_metadata_self_relabeling_rejected(converted):
    root, record, _, original_objects = converted
    metadata = root / record['objects_path']
    with zipfile.ZipFile(str(metadata), 'w', zipfile.ZIP_DEFLATED) as archive:
        for (kind, oid), body in original_objects.items():
            archive.writestr(kind + '/' + oid, body + b'changed' if kind == 'commit' else body)
    record['objects_sha256'] = hashlib.sha256(metadata.read_bytes()).hexdigest()
    save_proof(root, record)
    with pytest.raises(storage.StorageError, match='original metadata object hash mismatch'):
        storage.verify_rewrite(root)


def test_migration_checkout_resolves_only_verified_ancestors(converted, monkeypatch):
    root, record, _, _ = converted
    spec = importlib.util.spec_from_file_location('storage_migration_workflow',
        Path(__file__).resolve().parents[1] / 'scripts/migration.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    target = 'c' * 40
    monkeypatch.setattr(migration, 'git', lambda root, *args: target if args[0] == 'rev-parse' else '')
    monkeypatch.setattr(migration, 'source_inventory', lambda root: [])
    data = dict(baseline=dict(target_upstream=target, product_commit=record['original_tip']),
        modules=dict(manifests=[]), tasks=dict(task=dict(state='integrated', integrated_commit=record['original_tip'])))
    migration.validate_checkout(data, root)
    data['tasks']['task']['integrated_commit'] = 'd' * 40
    with pytest.raises(subprocess.CalledProcessError):
        migration.validate_checkout(data, root)


def test_actual_lfs_import_preserves_metadata_and_tracking_scope(converted, tmp_path):
    if subprocess.call(['git', 'lfs', 'version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        pytest.skip('Git LFS development observer unavailable')
    root, record, _, _ = converted
    original_bytes = (root / record['archives'][0]['path']).read_bytes()
    git(root, 'update-ref', 'refs/heads/master', record['original_tip'])
    git(root, 'reset', '--mixed', record['original_tip'])
    (root / '.gitattributes').write_bytes(b'migration/** text eol=lf\n')
    git(root, 'update-ref', 'refs/remotes/origin/master', record['remote_base'])
    mapping = tmp_path / 'actual-map.csv'
    environment = dict(os.environ, GIT_LFS_SKIP_SMUDGE='1')
    git(root, 'lfs', 'migrate', 'import', '--include-ref=refs/heads/master',
        '--exclude-ref=refs/remotes/origin/master', '--include=' + storage.PREFIX + '*.zip',
        '--object-map=' + str(mapping), '--yes', env=environment)
    converted_mapping = dict(csv.reader(mapping.read_text(encoding='utf-8').splitlines()))
    assert set(converted_mapping) == {record['original_tip']}
    new = converted_mapping[record['original_tip']]
    (root / record['archives'][0]['path']).write_bytes(original_bytes)
    target = root / record['mapping_path']
    target.write_text(mapping.read_text(encoding='utf-8'), encoding='utf-8')
    record.update(rewritten_tip=new, mapping_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    save_proof(root, record)
    assert storage.verify_rewrite(root) == converted_mapping
