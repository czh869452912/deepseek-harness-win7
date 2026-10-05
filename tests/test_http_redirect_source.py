import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.http_redirect_oracle import NAMES, validate_runtime

ROOT = Path(__file__).resolve().parents[1]
DAMAGE = ['missing-module', 'changed-module', 'empty-closure', 'foreign-root', 'foreign-python',
          'missing-row', 'duplicate-row', 'changed-row']


@pytest.fixture(scope='module')
def observations(tmp_path_factory):
    output = tmp_path_factory.mktemp('http-redirect-source') / 'paired.json'
    subprocess.run([sys.executable, str(ROOT / 'scripts/http_redirect_oracle.py'), '--output', str(output)],
                   cwd=str(ROOT), env=dict(os.environ), check=True, timeout=45)
    paired = json.loads(output.read_text(encoding='utf-8'))
    native = json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))
    assert paired['status'] == 'matched' and paired['cases'] == 29
    return native, paired['observations_sha256']


@pytest.mark.parametrize('name', NAMES)
def test_actual_source_redirect_method_body_headers_limit_and_abort_match(observations, name):
    native, source_digest = observations
    validate_runtime(native, ROOT, source_digest, native['modules'])
    row = next(row for row in native['rows'] if row['name'] == name)
    first = row['requests'][0]
    assert first['headers']['authorization'] == 'Bearer fixture-key'
    if name.startswith('raw-'):
        assert all(request['hostOverride'] is False for request in row['requests'])
    if name in ('same-307-twenty-one', 'same-307-loop'):
        assert len(row['requests']) == 21
        assert row['error'] == dict(code='TRANSPORT', status=None)
    elif name in ('raw-same-credentials', 'raw-cross-credentials', 'raw-unsupported-protocol', 'raw-abort-before-follow'):
        assert len(row['requests']) == 1
        assert row['error'] == dict(code='ABORTED' if name == 'raw-abort-before-follow' else 'TRANSPORT', status=None)
    else:
        assert 'error' not in row
        last = row['requests'][-1]
        if name.startswith('cross') or name.startswith('raw-cross'):
            assert 'authorization' not in last['headers']
            assert 'proxy-authorization' not in last['headers']
            assert 'cookie' not in last['headers']
        else:
            assert last['headers']['authorization'] == 'Bearer fixture-key'
        rewritten = name == 'rewrite-then-preserve' or (first['method'] == 'POST' and name.endswith(('-301', '-302', '-303')))
        rewritten = rewritten or name == 'raw-same-PUT-303'
        assert last['method'] == ('GET' if rewritten else first['method'])
        assert last['body'] == (None if rewritten else first['body'])
        if rewritten:
            assert not {'content-type', 'content-encoding', 'content-language', 'content-location'}.intersection(last['headers'])
        if name.startswith('raw-'):
            assert row['status'] == 200
            assert bool(row['text']) == (first['method'] != 'HEAD')
        else:
            assert row['chunks'][-1] == dict(type='finish', reason=dict(kind='stop'))
        if name == 'same-307-twenty':
            assert len(row['requests']) == 21
        if name == 'raw-relative-fragment':
            assert last['path'] == '/redirect/one?query=hello%20world'


@pytest.mark.parametrize('damage', DAMAGE)
def test_redirect_receipt_refuses_incomplete_or_foreign_runtime(observations, damage):
    original, source_digest = observations
    native = copy.deepcopy(original)
    expected_modules = original['modules']
    if damage == 'missing-module':
        del native['modules']['dsh/llm/http_stream.py']
    elif damage == 'changed-module':
        native['modules']['dsh/llm/http_stream.py'] = '0' * 64
    elif damage == 'empty-closure':
        native['modules'] = {}
        expected_modules = {}
    elif damage == 'foreign-root':
        native['root'] = str(ROOT.parent)
    elif damage == 'foreign-python':
        native['python'] = '3.9.0'
    elif damage == 'missing-row':
        native['rows'].pop()
    elif damage == 'duplicate-row':
        native['rows'][1] = copy.deepcopy(native['rows'][0])
    else:
        native['rows'][0]['requests'][1]['method'] = 'POST'
    with pytest.raises(ValueError):
        validate_runtime(native, ROOT, source_digest, expected_modules)
