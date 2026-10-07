"""Verify byte-preserving LFS history conversion without rewriting old receipts."""
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile


SHA = re.compile(r'^[0-9a-f]{40}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
TRACKING = b'migration/evidence/artifacts/*.zip filter=lfs diff=lfs merge=lfs -text'
PREFIX = 'migration/evidence/artifacts/'


class StorageError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise StorageError(message)


def object_id(kind, body):
    return hashlib.sha1(kind.encode('ascii') + b' ' + str(len(body)).encode('ascii') + b'\0' + body).hexdigest()


def file_digests(path):
    size = path.stat().st_size
    blob = hashlib.sha1(b'blob ' + str(size).encode('ascii') + b'\0')
    content = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            blob.update(block)
            content.update(block)
    return size, blob.hexdigest(), content.hexdigest()


def owned_file(root, name):
    require(isinstance(name, str) and '\\' not in name and PurePosixPath(name).as_posix() == name
            and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts,
            'storage proof path is not canonical')
    path = root / name
    require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), 'storage proof requires a regular file')
    require(root.resolve() in path.resolve().parents, 'storage proof path escapes repository')
    return path


class GitObjects:
    def __init__(self, root):
        self.process = subprocess.Popen(['git', '-C', str(root), 'cat-file', '--batch'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.cache = {}

    def read(self, oid, kind):
        require(bool(SHA.fullmatch(oid)), 'invalid storage Git object id')
        key = kind, oid
        if key not in self.cache:
            self.process.stdin.write((oid + '\n').encode('ascii'))
            self.process.stdin.flush()
            header = self.process.stdout.readline().split()
            require(len(header) == 3 and header[0].decode('ascii') == oid
                    and header[1].decode('ascii') == kind, 'missing/wrong storage Git object')
            size = int(header[2])
            require(0 <= size <= 4 * 1024 * 1024, 'storage metadata object is too large')
            body = self.process.stdout.read(size)
            require(len(body) == size and self.process.stdout.read(1) == b'\n', 'truncated storage Git object')
            require(object_id(kind, body) == oid, 'storage Git object hash mismatch')
            self.cache[key] = body
        return self.cache[key]

    def close(self):
        self.process.stdin.close()
        self.process.terminate()
        self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()


def tree_entries(body):
    result = {}
    position = 0
    while position < len(body):
        separator = body.find(b' ', position)
        ending = body.find(b'\0', separator + 1)
        require(separator > position and ending > separator, 'malformed storage tree')
        mode = body[position:separator]
        name = body[separator + 1:ending]
        require(mode in (b'40000', b'100644', b'100755', b'120000', b'160000')
                and name not in (b'.', b'..') and b'/' not in name and b'\\' not in name
                and name not in result and ending + 21 <= len(body), 'invalid storage tree entry')
        result[name] = mode, body[ending + 1:ending + 21].hex()
        position = ending + 21
    return result


def commit_parts(body):
    header, separator, message = body.partition(b'\n\n')
    require(bool(separator), 'malformed storage commit')
    lines = header.split(b'\n')
    trees = [line[5:].decode('ascii') for line in lines if line.startswith(b'tree ')]
    parents = [line[7:].decode('ascii') for line in lines if line.startswith(b'parent ')]
    require(len(trees) == 1 and bool(SHA.fullmatch(trees[0]))
            and all(SHA.fullmatch(parent) for parent in parents), 'invalid storage commit graph')
    return trees[0], parents, lines, message


def ancestors(root, commit):
    require(bool(SHA.fullmatch(commit)), 'invalid storage anchor')
    return set(subprocess.check_output(['git', '-C', str(root), 'rev-list', commit],
        encoding='ascii').splitlines())


def _verify_rewrite(root):
    root = Path(root)
    manifest_path = root / 'migration/storage/lfs-transport.json'
    if not manifest_path.exists():
        return {}
    manifest = json.loads(owned_file(root, 'migration/storage/lfs-transport.json').read_text(encoding='utf-8'))
    require(manifest.get('schema_version') == 1, 'unsupported storage proof schema')
    mapping_file = owned_file(root, manifest['mapping_path'])
    metadata_file = owned_file(root, manifest['objects_path'])
    require(hashlib.sha256(mapping_file.read_bytes()).hexdigest() == manifest['mapping_sha256'], 'storage mapping hash mismatch')
    require(hashlib.sha256(metadata_file.read_bytes()).hexdigest() == manifest['objects_sha256'], 'original Git metadata hash mismatch')
    aliases = {}
    with mapping_file.open(encoding='utf-8', newline='') as stream:
        for row in csv.reader(stream):
            require(len(row) == 2 and all(SHA.fullmatch(value) for value in row)
                    and row[0] not in aliases and row[1] not in aliases.values(), 'invalid/duplicate storage mapping')
            aliases[row[0]] = row[1]
    require(bool(aliases) and aliases.get(manifest['original_tip']) == manifest['rewritten_tip'], 'storage tip mapping mismatch')
    remote_ancestors = ancestors(root, manifest['remote_base'])
    require(not set(aliases).intersection(remote_ancestors), 'storage conversion rewrites published history')
    rewritten_ancestors = ancestors(root, manifest['rewritten_tip'])
    require(manifest['remote_base'] in rewritten_ancestors
            and manifest['rewritten_tip'] in ancestors(root, subprocess.check_output(
                ['git', '-C', str(root), 'rev-parse', 'HEAD'], encoding='ascii').strip()), 'storage conversion has wrong ancestry')
    originals = {}
    with zipfile.ZipFile(str(metadata_file)) as archive:
        require(len(set(archive.namelist())) == len(archive.namelist()), 'duplicate original metadata member')
        for information in archive.infolist():
            pieces = information.filename.split('/')
            require(len(pieces) == 2 and pieces[0] in ('commit', 'tree', 'blob')
                    and bool(SHA.fullmatch(pieces[1])) and information.file_size <= 4 * 1024 * 1024,
                    'invalid original metadata member')
            body = archive.read(information)
            require(object_id(pieces[0], body) == pieces[1], 'original metadata object hash mismatch')
            originals[pieces[0], pieces[1]] = body
    archives = {}
    for row in manifest['archives']:
        require(SHA.fullmatch(row['git_blob']) and SHA256.fullmatch(row['sha256'])
                and type(row['size']) is int and row['size'] >= 0
                and row['git_blob'] not in archives and row['path'].startswith(PREFIX)
                and row['path'].endswith('.zip'), 'invalid original archive identity')
        path = owned_file(root, row['path'])
        require(file_digests(path) == (row['size'], row['git_blob'], row['sha256']), 'original archive bytes changed')
        archives[row['git_blob']] = row
    objects = GitObjects(root)
    compared = set()
    reachable = set()

    def original(kind, oid):
        require((kind, oid) in originals, 'missing original metadata object')
        return originals[kind, oid]

    def compare_tree(before, after, prefix=''):
        if before == after or (before, after, prefix) in compared:
            return
        compared.add((before, after, prefix))
        old = tree_entries(original('tree', before))
        new = tree_entries(objects.read(after, 'tree'))
        require(set(old) == set(new) or (not prefix and set(new) == set(old) | {b'.gitattributes'}),
                'storage conversion changed tree paths')
        for name, current in new.items():
            path = prefix + name.decode('utf-8')
            previous = old.get(name)
            if previous == current:
                continue
            require(previous is not None or path == '.gitattributes', 'storage conversion added product files')
            if path == '.gitattributes':
                require(current[0] == b'100644' and (previous is None or previous[0] == b'100644'), 'storage attributes mode changed')
                before_lines = original('blob', previous[1]).splitlines() if previous else []
                after_lines = objects.read(current[1], 'blob').splitlines()
                require(after_lines.count(TRACKING) == 1, 'storage tracking scope differs')
                after_lines.remove(TRACKING)
                require([line for line in before_lines if line] == [line for line in after_lines if line],
                        'storage conversion changed unrelated attributes')
            elif previous[0] == current[0] == b'40000':
                compare_tree(previous[1], current[1], path + '/')
            elif path.startswith(PREFIX) and path.endswith('.zip'):
                require(previous[0] == current[0] == b'100644' and previous[1] in archives, 'unproved archive conversion')
                row = archives[previous[1]]
                expected = ('version https://git-lfs.github.com/spec/v1\noid sha256:'
                    + row['sha256'] + '\nsize ' + str(row['size']) + '\n').encode('ascii')
                require(objects.read(current[1], 'blob') == expected, 'storage archive pointer differs from original bytes')
            else:
                require(False, 'storage conversion changed product bytes: ' + path)

    try:
        pending = [manifest['original_tip']]
        while pending:
            old = pending.pop()
            if old in reachable:
                continue
            require(old in aliases, 'original conversion range is incomplete')
            reachable.add(old)
            new = aliases[old]
            require(new in rewritten_ancestors, 'mapped commit is outside rewritten history')
            old_tree, parents, lines, message = commit_parts(original('commit', old))
            new_body = objects.read(new, 'commit')
            new_tree = commit_parts(new_body)[0]
            replacement = []
            for line in lines:
                if line.startswith(b'tree '):
                    line = b'tree ' + new_tree.encode('ascii')
                elif line.startswith(b'parent '):
                    parent = line[7:].decode('ascii')
                    require(parent in aliases or parent in remote_ancestors, 'original parent escapes published anchor')
                    line = b'parent ' + aliases.get(parent, parent).encode('ascii')
                replacement.append(line)
            require(new_body == b'\n'.join(replacement) + b'\n\n' + message, 'storage conversion changed commit metadata')
            compare_tree(old_tree, new_tree)
            pending.extend(parent for parent in parents if parent in aliases)
        require(reachable == set(aliases), 'storage mapping includes unrelated commits')
    finally:
        objects.close()
    return aliases


def verify_rewrite(root):
    try:
        return _verify_rewrite(root)
    except StorageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        raise StorageError('invalid storage proof: ' + str(exc)) from exc
