import asyncio
import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.boot.market_index_022 import parse_index_body
from scripts.rc022_market_json_probe import observe, URL


@pytest.mark.asyncio
async def test_original_syntax_diagnostics_through_actual_body_reader():
    fixture = json.loads((Path(__file__).parent/'fixtures/rc022-market-json-diagnostics.json').read_text(encoding='utf-8'))
    assert len(fixture['rows']) >= 20
    for row in fixture['rows']:
        assert await parse_index_body(row['text'].encode('utf-8'), URL) == row['result']


def test_x86_worker_matches_full_x64_syntax_corpus():
    executable = os.environ.get('DSH_TEST_X86_PYTHON')
    if not executable:
        pytest.skip('explicit x86 Python fixture not configured')
    script = '''import asyncio,ctypes,json,os,sys
sys.path.insert(0,os.getcwd())
from scripts.rc022_market_json_probe import observe
assert ctypes.sizeof(ctypes.c_void_p)==4
print(json.dumps(asyncio.run(observe()),ensure_ascii=True))
'''
    result = subprocess.run([executable, '-c', script], cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')[-2000:]
    assert json.loads(result.stdout) == asyncio.run(observe())
