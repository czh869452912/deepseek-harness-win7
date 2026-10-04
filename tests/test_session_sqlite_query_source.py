import os
from pathlib import Path
import re
import shutil
import subprocess


def test_unchanged_original_sqlite_query_specs():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    assert node is not None
    result = subprocess.run([node,str(root/'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run','--config',str(root/'scripts/oracles/vitest.session-sqlite-query.config.mts')],
        cwd=str(root),env=dict(os.environ),capture_output=True,timeout=90)
    output = (result.stdout+result.stderr).decode('utf-8',errors='replace')
    assert result.returncode == 0, output
    normalized = re.sub(r'\x1b\[[0-9;]*m','',output)
    assert re.findall(r'Tests\s+(\d+) passed',normalized) == ['10'],output
