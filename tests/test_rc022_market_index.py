import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.boot import market_index_022 as market
from dsh.javascript.runtime import JavaScriptRuntimeError
from scripts.rc022_market_index_probe import cases


def test_market_validator_search_and_chunking():
    rows = market.observe_market_operations(cases())
    assert len(rows) >= 100
    assert rows[0]['ok']
    assert rows[0]['index']['metadata'] == dict(categories={}, labels={}, sortKeys={})
    assert rows[0]['targets'][0]['versions'] == [dict(spec='@scope/example@1.2.3')]
    assert all(row['ok'] or row['error']['name'] == 'MarketIndexError' for row in rows)
    assert len(rows[-1]['results'][0]) == 1001
    # Four-character query permits edit distance one: 100 is also a match.
    assert rows[-1]['results'][1] == ['dsh-item-100', 'dsh-item-1000']
    assert rows[-1]['results'][2] == ['dsh-item-'+str(i) for i in range(1001)]


def test_python_validation_failure_preserves_path_and_reason():
    with pytest.raises(market.MarketIndexError) as caught:
        market.parse_market_index(dict(format=2), 'https://market.example/')
    assert caught.value.path == '$.format'
    assert caught.value.reason == 'must be 1'
    assert str(caught.value) == '$.format must be 1'


@pytest.mark.parametrize('resource', ['manifest.json', 'market.js', 'driver.js', 'url.js', 'semver-LICENSE', 'minisearch-LICENSE.txt'])
def test_resources_fail_closed(tmp_path, monkeypatch, resource):
    for path in market.RESOURCE_ROOT.iterdir():
        (tmp_path/path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(market, 'RESOURCE_ROOT', tmp_path)
    (tmp_path/resource).write_bytes(b'changed')
    with pytest.raises(JavaScriptRuntimeError, match='bytes differ'):
        market.market_bootstrap()


def test_resource_path_cannot_escape_carrier(tmp_path, monkeypatch):
    manifest = dict(format='dsh-market-index@1', target_upstream='38a6a5c965aa99ab525161efb7cc5cf1fe62fced', resources={'../escape': 'x'})
    data = json.dumps(manifest).encode('utf-8'); (tmp_path/'manifest.json').write_bytes(data)
    monkeypatch.setattr(market, 'RESOURCE_ROOT', tmp_path)
    monkeypatch.setattr(market, 'MANIFEST_SHA256', hashlib.sha256(data).hexdigest())
    with pytest.raises(JavaScriptRuntimeError, match='resource path differs'):
        market.market_bootstrap()


def test_worker_transport_rejects_non_json_numbers():
    with pytest.raises(ValueError, match='Out of range float'):
        market.observe_market_operations([dict(value=float('nan'))])


def test_worker_uses_shipped_engine_only():
    manifest = json.loads((market.RESOURCE_ROOT/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['engine'] == 'shipped Win7 QuickJS'
    assert any('semver@7.8.5' in path for path in manifest['build_inputs'])
    assert any('minisearch@' in path for path in manifest['build_inputs'])
    assert 'globalThis.setTimeout' in (market.RESOURCE_ROOT/'driver.js').read_text(encoding='utf-8')


def test_x86_worker_matches_x64(tmp_path):
    executable = os.environ.get('DSH_TEST_X86_PYTHON')
    if not executable:
        pytest.skip('explicit x86 Python fixture not configured')
    script = ('import ctypes,json,sys,os;sys.path.insert(0,os.getcwd());'
        'from dsh.boot.market_index_022 import observe_market_operations;'
        'from scripts.rc022_market_index_probe import cases;'
        'assert ctypes.sizeof(ctypes.c_void_p)==4;'
        'print(json.dumps(observe_market_operations(cases()),ensure_ascii=True))')
    result = subprocess.run([executable, '-c', script], cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')[-2000:]
    assert json.loads(result.stdout) == market.observe_market_operations(cases())
