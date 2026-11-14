"""Read minimal, byte-preserved members with their original archive provenance."""
import gzip
import hashlib
import json
from pathlib import Path

from scripts import evidence_assets


ROOT = Path(__file__).resolve().parent / 'fixtures/evidence'


def read_member(archive, member):
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    row = next(row for row in manifest['members']
               if row['archive'] == archive and row['member'] == member)
    originals = evidence_assets.read_index(Path(__file__).resolve().parents[1])
    if originals[evidence_assets.PREFIX + archive]['sha256'] != row['archive_sha256']:
        raise ValueError('Evidence fixture archive provenance differs: ' + archive)
    content = gzip.decompress((ROOT / row['fixture']).read_bytes())
    if len(content) != row['size'] or hashlib.sha256(content).hexdigest() != row['sha256']:
        raise ValueError('Evidence fixture member differs: ' + member)
    return json.loads(content)
