import json
import os
from pathlib import Path
import subprocess
import sys


def test_acp_peer_reads_utf8_wire_without_inherited_python_encoding(tmp_path):
    root = Path(__file__).resolve().parents[1]
    record = tmp_path / 'wire.jsonl'
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith('PYTHON')}
    environment['PROBE_RECORD'] = str(record)
    packets = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
         'params': {'protocolVersion': 1, 'clientCapabilities': {}}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'session/new',
         'params': {'cwd': str(tmp_path / '\u4e2d\u6587'), 'mcpServers': []}},
    ]
    result = subprocess.run(
        [sys.executable, '-I', str(root / 'scripts/oracles/subagent_acp_peer.py')],
        input=''.join(json.dumps(packet, ensure_ascii=False) + '\n' for packet in packets).encode('utf-8'),
        env=environment, capture_output=True, timeout=5)
    assert result.returncode == 0
    assert result.stderr == b''
    observed = [json.loads(line) for line in record.read_text(encoding='utf-8').splitlines()]
    assert observed[1:3] == packets
