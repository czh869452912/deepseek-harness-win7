"""Retained v3 Win7 carrier fixtures; not the current upstream v4 lifecycle."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from dsh.host.desktop.wire import (CHUNK_BYTES, CONTROL_BYTES, FrameDecoder,
    DesktopProtocolError, encode_start, encode_data, encode_end, encode_error, encode_frame)

CASES_PATH = Path(__file__).resolve().parents[1] / 'scripts/oracles/desktop_wire_current_cases.json'
CASES = json.loads(CASES_PATH.read_text(encoding='utf-8')) if CASES_PATH.exists() else []


def observed(case):
    decoder, frames = FrameDecoder(case['direction']), []
    data = base64.b64decode(case['bytes'])
    try:
        for offset in range(0, len(data), case['split']):
            frames.extend(decoder.push(data[offset:offset + case['split']]))
        if case['finish']:
            decoder.finish()
        value = dict(frames=frames)
    except DesktopProtocolError as error:
        value = dict(frames=frames, error=str(error))
    for row in frames:
        if row['type'] == 'data':
            row['data'] = base64.b64encode(row['data']).decode('ascii')
    return value


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['case'])
def test_actual_source_fragmented_frames(case):
    value, expected = observed(case), case['expected']
    if 'invalid-json' in case['case']:
        # Python and V8 syntax diagnostics are runtime-owned. No other protocol
        # errors or successful bytes/fields receive normalization.
        assert value['error'].split('payload is not JSON:')[0] == expected['error'].split('payload is not JSON:')[0]
        assert value['frames'] == expected['frames']
    else:
        assert value == expected


def test_source_corpus_must_be_present():
    assert len(CASES) >= 80


@pytest.mark.parametrize('case', [case for case in CASES
    if case['direction'] == 'response' and 'error' not in case['expected'] and case['finish']], ids=lambda case: case['case'])
def test_response_encoder_bytes_equal_actual_source(case):
    frames = []
    for row in case['expected']['frames']:
        identity, kind = row['streamId'], row['type']
        if kind == 'start':
            frames.append(encode_start(identity, {key: row[key] for key in ('status', 'headers', 'hasBody')}))
        elif kind == 'data':
            frames.append(encode_data(identity, base64.b64decode(row['data'])))
        elif kind == 'error':
            frames.append(encode_error(identity, row['message']))
        else:
            frames.append(encode_end(identity))
    assert b''.join(frames) == base64.b64decode(case['bytes'])


def test_outgoing_response_round_trip_and_frame_limits():
    decoder = FrameDecoder('response')
    start = dict(status=206, headers=[['x-value', '中文'], ['x-value', '💾']], hasBody=True)
    frames = decoder.push(encode_start(1, start) + encode_data(1, b'\x00\xff') + encode_end(1) + encode_error(2, 'closed'))
    decoder.finish()
    assert frames == [dict(type='start', streamId=1, **start), dict(type='data', streamId=1, data=b'\x00\xff'),
                      dict(type='end', streamId=1), dict(type='error', streamId=2, message='closed')]
    with pytest.raises(DesktopProtocolError, match='65536-byte'):
        encode_data(1, b'x' * (CHUNK_BYTES + 1))
    with pytest.raises(DesktopProtocolError, match='1048576-byte'):
        encode_error(1, 'x' * CONTROL_BYTES)
    for identity in (0, -1, True, 0x100000000, 1.5, float('nan')):
        with pytest.raises(DesktopProtocolError):
            encode_end(identity)


def test_response_credit_is_a_negotiated_empty_request_frame():
    frame = encode_frame(5, 1, direction='request')
    assert FrameDecoder(response_credit=True).push(frame) == [
        dict(type='response-credit', streamId=1)]
    for decoder in (FrameDecoder(), FrameDecoder('response', response_credit=True)):
        with pytest.raises(DesktopProtocolError, match='unknown'):
            decoder.push(frame)
    with pytest.raises(DesktopProtocolError, match='carried a payload'):
        FrameDecoder(response_credit=True).push(encode_frame(5, 1, b'x'))


@pytest.mark.parametrize('carrier', ('credit', 'legacy'))
def test_actual_pipe_response_flow(carrier):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the Desktop main-process pipe adapter')
    root = CASES_PATH.parents[2]
    script = Path(__file__).parent / 'fixtures/desktop_pipe_flow.cjs'
    result = subprocess.run([node, str(script), sys.executable, carrier], cwd=str(root),
        env=dict(os.environ, PYTHONPATH=str(root)), capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
