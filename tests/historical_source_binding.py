"""Validate retained rc.3 observations against their byte-preserved Git inputs.

Current Source contracts run independently; these facts never move with the pin.
"""
import functools
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = 'a4c74a91e06b00fe0b0937bde982170c526cc842'
FIXTURES = {
    'remote-frozen': '268f0c0b3aa44b9f1cdfc4dc2d0a4e938945741e410aafd9f7cb013a19640877',
    'abort': 'd499767b0f3090888257b30de5f08bb5158f402d73f5b568391b85382047fdeb',
}


@functools.lru_cache(maxsize=1)
def original_inputs():
    base = ROOT / 'tests/fixtures/canonical-historical-source-inputs'
    index = json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
    raw = gzip.decompress(base.with_suffix('.json.gz').read_bytes())
    assert index['source_commit'] == PIN
    assert len(raw) == index['content_size'] == 130324
    assert hashlib.sha256(raw).hexdigest() == index['content_sha256'] == '4e7aba60ef294f3b5bbfa779a2008fa5697e032b4380cf5b0877dd485002bfbe'
    members = json.loads(raw)
    assert set(members) == set(index['members'])
    for path, text in members.items():
        data = text.encode('utf-8')
        identity = index['members'][path]
        assert len(data) == identity['size']
        assert hashlib.sha256(data).hexdigest() == identity['sha256']
        assert hashlib.sha1(('blob ' + str(len(data)) + '\0').encode('ascii') + data).hexdigest() == identity['git_blob']
    return members


def assert_historical_inputs(name, fixture):
    raw = (ROOT / 'tests/fixtures' / (name + '-source-observations.json')).read_text(encoding='utf-8')
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == FIXTURES[name]
    assert json.loads(raw) == fixture
    assert fixture['target_upstream'] == PIN and fixture['node'] == 'v22.22.2'
    for path, digest in fixture['source_sha256'].items():
        text = original_inputs()[path] if path.startswith('reference/') else (ROOT / path).read_text(encoding='utf-8')
        assert hashlib.sha256(text.encode('utf-8')).hexdigest() == digest, path
