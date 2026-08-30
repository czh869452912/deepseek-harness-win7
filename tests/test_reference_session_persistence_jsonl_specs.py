import asyncio
import json
import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionHeader, SessionStore
from dsh.session.persistence import SessionFormatUnsupportedError
from dsh.session.persistence_jsonl import (
    JsonlSessionPersistence,
    encode_segment,
    from_header_line,
    is_header_line,
    log_path,
    parse_header_meta,
    project_dir,
    project_key,
    scan_log,
    session_dir,
    to_header_line,
)



def test_encode_segment_neutralizes_traversal_separators_and_absolute_paths():
    assert encode_segment('..') == '~002E~002E'
    assert encode_segment('.') == '~002E'
    assert encode_segment('a/b') == 'a~002Fb'
    assert encode_segment('/etc/passwd') == '~002Fetc~002Fpasswd'
    assert encode_segment('a\u0000b') == 'a~0000b'
    assert encode_segment('plain-ID_1.2') == 'plain-ID_1.2'
    assert encode_segment('a~b') == 'a~007Eb'



def test_encode_segment_rejects_empty_id():
    with pytest.raises(ValueError, match='cannot encode an empty path segment'):
        encode_segment('')


def test_project_key_normalizes_project_paths():
    assert project_key('/Users/qyj/work/deepseek-harness') == '--Users-qyj-work-deepseek-harness--'
    assert project_key('/a/b-c') == project_key('/a-b/c')
    assert project_key('C:\\work\\agent') == '--C-work-agent--'
    assert project_key('/') == '--root--'
    long_path = '/' + 'x' * 1000
    assert len(project_key(long_path)) <= 255
    with pytest.raises(ValueError, match='cannot encode an empty project path'):
        project_key('')


def test_header_line_round_trip():
    hdr = SessionHeader(
        session_id='sess-123',
        cwd='C:\\work\\repo' if os.name == 'nt' else '/work/repo',
        delegation_depth=2,
        parent_session='parent-1',
        seed_length=5,
        origin='subagent',
    )
    line = to_header_line(hdr)
    assert line['type'] == 'session'
    assert line['id'] == 'sess-123'
    assert line['delegationDepth'] == 2
    assert is_header_line(line) is True

    restored = from_header_line(line)
    assert restored.id == hdr.id
    assert restored.cwd == hdr.cwd
    assert restored.delegation_depth == 2
    assert restored.parent_session == 'parent-1'


@pytest.mark.asyncio
async def test_jsonl_persistence_lifecycle_and_read_raw():
    with tempfile.TemporaryDirectory() as temp_dir:
        persistence = JsonlSessionPersistence(root=temp_dir, pack_chunks=True)
        cwd = os.path.abspath(temp_dir)
        meta = SessionHeader(session_id='sess-raw-test', cwd=cwd)

        # Locate without materializing
        loc = persistence.locate(meta)
        assert os.path.isabs(loc.path)
        assert os.path.exists(loc.path) is False

        # Create
        await persistence.create(meta)
        assert os.path.exists(loc.path) is True

        # Append events
        events = [
            {'type': 'turn/start', 'seq': 0, 'time': 1000, 'data': {'turn': 1}},
            {'type': 'user/message', 'seq': 1, 'time': 1001, 'data': {'role': 'user', 'content': 'Hello'}},
            {'type': 'turn/end', 'seq': 2, 'time': 1002, 'data': {'turn': 1, 'reason': {'kind': 'completed'}}},
        ]
        await persistence.append('sess-raw-test', events)

        # Read raw
        raw = await persistence.read_raw('sess-raw-test')
        assert raw is not None
        assert raw['filename'] == 'session.jsonl'
        assert raw['meta'].id == 'sess-raw-test'
        assert 'turn/start' in raw['content']

        # Load
        loaded = await persistence.load('sess-raw-test')
        assert len(loaded.events) == 3
        assert loaded.events[0]['type'] == 'turn/start'
        assert loaded.events[2]['type'] == 'turn/end'


@pytest.mark.asyncio
async def test_jsonl_future_version_refusal():
    with tempfile.TemporaryDirectory() as temp_dir:
        persistence = JsonlSessionPersistence(root=temp_dir)
        cwd = os.path.abspath(temp_dir)
        meta = SessionHeader(session_id='future-sess', cwd=cwd)
        path = persistence.locate(meta).path
        os.makedirs(os.path.dirname(path), exist_ok=True)

        future_header =  {'type': 'session', 'version': 42, 'id': 'future-sess', 'createdAt': 1000, 'delegationDepth': 0}
        with open(path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(future_header) + '\n')

        with pytest.raises(SessionFormatUnsupportedError, match='uses log format v42'):
            await persistence.load('future-sess')


@pytest.mark.asyncio
async def test_jsonl_crash_recovery_closes_interrupted_turn():
     with tempfile.TemporaryDirectory() as temp_dir:
        persistence = JsonlSessionPersistence(root=temp_dir)
        cwd = os.path.abspath(temp_dir)
        meta = SessionHeader(session_id='crash-sess', cwd=cwd)
        await persistence.create(meta)

        events_turn1 = [
            {'type': 'turn/start', 'seq': 0, 'time': 100, 'data': {'turn': 1}},
             {'type': 'turn/end', 'seq': 1, 'time': 101, 'data': {'turn': 1, 'reason': {'kind': 'completed'}}},
        ]
        await persistence.append('crash-sess', events_turn1)

        # Append open turn 2 without closing turn/end, plus trailing torn fragment
        path = persistence.locate(meta).path
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'type': 'turn/start', 'seq': 2, 'time': 102, 'data': {'turn': 2}}) + '\n')
            f.write('{"type": "assistant/chunk", "seq": 3, "ti')

        # Load must repair the crash tail by appending turn/end {interrupted}
        loaded = await persistence.load('crash-sess')
        assert len(loaded.events) == 4
        assert loaded.events[2]['type'] == 'turn/start'
        assert loaded.events[3]['type'] == 'turn/end'
        assert loaded.events[3]['data']['reason'] == {'kind': 'interrupted'}


@pytest.mark.asyncio
async def test_jsonl_path_traversal_session_id_safely_encoded():
    with tempfile.TemporaryDirectory() as temp_dir:
        persistence = JsonlSessionPersistence(root=temp_dir)
        evil_id = '../../etc/passwd'
        meta = SessionHeader(session_id=evil_id)
        loc = persistence.locate(meta)
        rel = os.path.relpath(loc.path, os.path.abspath(temp_dir))
        assert not rel.startswith('..')
