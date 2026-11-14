"""Offline evidence index and explicit verification of externally stored bytes.

Python 3.8/std lib only. Never downloads assets or treats an index as byte proof.
Set DSH_EVIDENCE_ROOT to an archive directory mirroring repository paths.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
INDEX = 'migration/storage/external-artifacts.json'
PREFIX = 'migration/evidence/artifacts/'


def safe_path(base, name):
    if (not isinstance(name, str) or not name or '\\' in name
            or PurePosixPath(name).is_absolute() or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Noncanonical evidence path: ' + str(name))
    base = Path(base).resolve()
    path = base / name
    path.resolve().relative_to(base)
    # Evidence is data, never a link to an unowned destination.
    for item in (path,) + tuple(path.parents):
        if item == base:
            break
        if item.is_symlink() or (item.exists() and getattr(os.lstat(str(item)), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Evidence reparse path refused: ' + name)
    return path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_index(root):
    path = Path(root) / INDEX
    if not path.exists():
        return {}
    record = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(record, dict) or record.get('schema_version') != 1 or not isinstance(record.get('artifacts'), list):
        raise ValueError('Invalid external evidence index')
    rows = {}
    for row in record['artifacts']:
        if not isinstance(row, dict) or 'path' not in row:
            raise ValueError('Invalid external evidence row')
        name = row['path']
        safe_path(root, name)
        if (not name.startswith(PREFIX) or not name.endswith('.zip') or name in rows
                or type(row.get('size')) is not int or row['size'] < 0
                or not isinstance(row.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Invalid/duplicate external evidence identity: ' + name)
        rows[name] = row
    return rows


def resolve_asset(root, name, rows=None):
    rows = read_index(root) if rows is None else rows
    row = rows.get(name)
    bases = [Path(root)]
    if os.environ.get('DSH_EVIDENCE_ROOT'):
        bases.append(Path(os.environ['DSH_EVIDENCE_ROOT']))
    for base in bases:
        path = safe_path(base, name)
        if path.is_file():
            if row and (path.stat().st_size != row['size'] or file_sha256(path) != row['sha256']):
                raise ValueError('External evidence bytes differ: ' + name)
            return path
    raise ValueError('Evidence bytes not verified; set DSH_EVIDENCE_ROOT: ' + name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'verify'])
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        rows = read_index(args.root)
        if not rows:
            raise ValueError('External evidence index missing or empty')
        if args.command == 'verify':
            for name in rows:
                resolve_asset(args.root, name, rows)
        print(json.dumps(dict(status='bytes-verified' if args.command == 'verify' else 'index-only',
                              artifacts=len(rows), bytes=sum(row['size'] for row in rows.values()))))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('evidence: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
