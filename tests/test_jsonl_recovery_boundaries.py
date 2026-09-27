"""Durable JSONL recovery boundaries derived from pinned coordinator/format."""
import json
from pathlib import Path
import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionHeader, SessionPlugin
from dsh.session.persistence import SessionFormatUnsupportedError
from dsh.session.persistence_jsonl import JsonlSessionPersistence, JsonlSessionPersistencePlugin, SessionLogScanner

FIXTURES = json.loads((Path(__file__).resolve().parents[1] / 'scripts/oracles/session-recovery-fixtures.json').read_text(encoding='utf-8'))

def write_log(p, events, tail=b'', header=None):
    meta = SessionHeader(session_id='recovery')
    path = Path(p.locate(meta).path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = ('\n'.join(json.dumps(e) for e in [header or dict(type='session', version=0, id=meta.id, createdAt=1)] + events) + '\n').encode('utf-8') + tail
    path.write_bytes(raw)
    return path, raw

@pytest.mark.asyncio
@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f: f['mode'])
async def test_cold_recovery_is_read_only_until_load_and_survives_reopen(tmp_path, fixture):
    p = JsonlSessionPersistence(str(tmp_path))
    events = fixture['events']
    path, raw = write_log(p, events, fixture['tail'].encode('utf-8'))
    logical = await p.inspect('recovery')
    assert path.read_bytes() == raw
    assert (await p.read_from('recovery', 1)).events == events[1:]
    assert logical.events[-1]['type'] == 'turn/end'
    assert logical.events[-1]['time'] == events[-1]['time']
    loaded = await p.load('recovery')
    assert loaded.events == logical.events
    repaired = path.read_bytes()
    fresh = JsonlSessionPersistence(str(tmp_path))
    assert (await fresh.load('recovery')).events == loaded.events
    assert (await fresh.read_from('recovery', 0)).events == loaded.events
    assert path.read_bytes() == repaired
    if fixture['mode'].startswith('tool-'):
        result = next(e for e in loaded.events if e['type'] == 'tool/result')
        expected = 'TOOL_OUTCOME_UNKNOWN' if fixture['mode'].endswith('unknown') else 'TOOL_NOT_STARTED'
        assert result['data']['error']['code'] == expected
        assert result.get('sourceEventSeqs') == ([3] if expected == 'TOOL_OUTCOME_UNKNOWN' else None)

@pytest.mark.asyncio
@pytest.mark.parametrize('value', [-1, True, 1.5, '0', None, 9007199254740992])
async def test_physical_suffix_requires_nonnegative_safe_integer(tmp_path, value):
    with pytest.raises(TypeError, match='safe integer'):
        await JsonlSessionPersistence(str(tmp_path)).read_from('missing', value)

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['inspect', 'load', 'read_from'])
async def test_header_identity_mismatch_never_changes_file(tmp_path, operation):
    p = JsonlSessionPersistence(str(tmp_path))
    path, raw = write_log(p, [], b'{', dict(type='session', version=0, id='other', createdAt=1))
    with pytest.raises(ValueError, match='does not match'):
        await getattr(p, operation)('recovery', *([0] if operation == 'read_from' else []))
    assert path.read_bytes() == raw

@pytest.mark.asyncio
async def test_next_format_version_is_refused_without_repair(tmp_path):
    p = JsonlSessionPersistence(str(tmp_path))
    path, raw = write_log(p, [], b'{', dict(type='session', version=1, id='recovery', createdAt=1))
    with pytest.raises(SessionFormatUnsupportedError):
        await p.load('recovery')
    assert path.read_bytes() == raw

@pytest.mark.parametrize('split', [1, 8, 50, 140])
def test_scanner_keeps_valid_byte_offset_across_chunks(split):
    header = b'{"type":"session","version":0,"id":"s","createdAt":1}\n'
    row = b'{"type":"turn/start","seq":0,"time":1,"data":{"turn":1}}\n'
    tail = row + b'bad-json\n{"type":'
    scanner = SessionLogScanner(header)
    for offset in range(0, len(tail), split):
        scanner.write(tail[offset:offset+split])
    result = scanner.finish()
    assert result['committed_bytes'] == len(header) + len(row)
    assert len(result['events']) == 1

@pytest.mark.asyncio
async def test_damage_inside_closed_turn_is_refused_not_truncated(tmp_path):
    p = JsonlSessionPersistence(str(tmp_path))
    end = dict(type='turn/end', seq=2, time=3, data=dict(turn=1, reason=dict(kind='completed')))
    path, raw = write_log(p, FIXTURES[0]['events'], b'bad-json\n' + json.dumps(end).encode('utf-8') + b'\n')
    with pytest.raises(ValueError, match='unparsable'):
        await p.load('recovery')
    assert path.read_bytes() == raw

@pytest.mark.asyncio
async def test_live_open_turn_is_never_crash_repaired(tmp_path):
    ctx = Context()
    SessionPlugin().apply(ctx)
    JsonlSessionPersistencePlugin(root=str(tmp_path)).apply(ctx)
    p = ctx.get('sessionPersistence')
    session = ctx.get('sessions').create('live')
    try:
        session.append('turn/start', {'turn': 1})
        assert (await p.inspect('live')).events == session.events
        with pytest.raises(FileNotFoundError):
            await p.read_from('live', 0)
        with pytest.raises(ValueError, match='live turn is open'):
            await p.load('live')
        assert [e['type'] for e in (await p.read_from('live', 0)).events] == ['turn/start']
        assert len(session.events) == 1
    finally:
        await ctx.fiber.dispose()
