"""Bind retained Python extension controls to their original Source commit.

These observations test historical compatibility, never current Source parity.
Current inspection and lifecycle acceptance use the independent rc022 probes.
"""
import hashlib
import functools
import gzip
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIN = 'a4c74a91e06b00fe0b0937bde982170c526cc842'
FIXTURES = {
    'inspect': '98748bc42647f95a28380a21da03db14ecea4f1991a8e9dd535855612d0d5cb7',
    'cordis-runner': '6ec2651bb84c023d47c852021fe91d13ec7d3b39eceb7113e4e82e9a744fc77d',
    'cordis-guard': 'b6bac4654660388015a6d2c793f5ca6dea6983970c38c78aff08615b0ac1a17c',
    'cordis-retirement': 'd5606faa44770795cfead5dbd098b5749eee3977e9302801d9e877ad1da44c23',
    'cordis-tools': 'f0325fef17d684118cce9924550c959e0659c314baa2f081e6cb758cd471b148',
}


@functools.lru_cache(maxsize=1)
def _original_inputs():
    index = json.loads((ROOT / 'tests/fixtures/cordis-historical-source-inputs.json').read_text(encoding='utf-8'))
    assert index['source_commit'] == PIN
    data = gzip.decompress((ROOT / 'tests/fixtures/cordis-historical-source-inputs.json.gz').read_bytes())
    assert hashlib.sha256(data).hexdigest() == 'c7e6705a37c43821eacf736f72ec07a8d8c26f7948dbf68987305c09fec4e5ae'
    assert index['content_size'] == len(data)
    members = json.loads(data)
    assert set(members) == set(index['members'])
    for path, text in members.items():
        original = text.encode('utf-8')
        identity = index['members'][path]
        assert len(original) == identity['size']
        assert hashlib.sha256(original).hexdigest() == identity['sha256']
        assert hashlib.sha1(('blob ' + str(len(original)) + '\0').encode('ascii') + original).hexdigest() == identity['git_blob']
    return members


def assert_historical_cordis_inputs(name, fixture):
    raw = (ROOT / 'tests/fixtures' / (name + '-source-observations.json')).read_text(encoding='utf-8')
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == FIXTURES[name]
    assert json.loads(raw) == fixture
    assert fixture['target_upstream'] == PIN
    for path, expected in fixture['source_sha256'].items():
        if path.startswith('reference/'):
            text = _original_inputs()[path]
        else:
            text = (ROOT / path).read_text(encoding='utf-8')
        assert hashlib.sha256(text.encode('utf-8')).hexdigest() == expected, path
