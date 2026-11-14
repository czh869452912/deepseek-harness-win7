import hashlib
import json

import pytest

from scripts import evidence_assets as assets


@pytest.fixture
def external(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    store = tmp_path / 'store'
    root.mkdir()
    store.mkdir()
    name = assets.PREFIX + 'original.zip'
    content = b'original evidence\x00\xff'
    row = dict(path=name, size=len(content), sha256=hashlib.sha256(content).hexdigest())
    index = root / assets.INDEX
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps(dict(schema_version=1, artifacts=[row])), encoding='utf-8')
    target = store / name
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    monkeypatch.setenv('DSH_EVIDENCE_ROOT', str(store))
    return root, store, row


def test_offline_index_does_not_claim_bytes_and_explicit_verify_requires_them(external, monkeypatch, capsys):
    root, store, row = external
    monkeypatch.delenv('DSH_EVIDENCE_ROOT')
    assert assets.main(['check', '--root', str(root)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'index-only'
    assert assets.main(['verify', '--root', str(root)]) == 1
    assert 'not verified' in capsys.readouterr().err
    monkeypatch.setenv('DSH_EVIDENCE_ROOT', str(store))
    assert assets.main(['verify', '--root', str(root)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'bytes-verified'


@pytest.mark.parametrize('damage', ['same-length', 'truncated', 'local-pointer'])
def test_corruption_is_rejected_even_with_valid_index(external, damage):
    root, store, row = external
    target = store / row['path']
    if damage == 'same-length':
        target.write_bytes(b'X' * row['size'])
    elif damage == 'truncated':
        target.write_bytes(b'X')
    else:
        target = root / row['path']
        target.parent.mkdir(parents=True)
        target.write_bytes(b'version https://git-lfs.github.com/spec/v1\n')
    with pytest.raises(ValueError, match='bytes differ'):
        assets.resolve_asset(root, row['path'])


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/escape', 'a\\b', 'a/../b', 'a//b'])
def test_noncanonical_paths_refused(tmp_path, name):
    with pytest.raises(ValueError):
        assets.safe_path(tmp_path, name)


def test_duplicate_identity_is_rejected(external):
    root, store, row = external
    (root / assets.INDEX).write_text(json.dumps(dict(schema_version=1, artifacts=[row, row])), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate'):
        assets.read_index(root)


@pytest.mark.parametrize('record', [[], None, {'schema_version': 1, 'artifacts': [None]}])
def test_malformed_index_reports_a_validation_error(external, record):
    root, store, row = external
    (root / assets.INDEX).write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(ValueError, match='Invalid external evidence'):
        assets.read_index(root)
