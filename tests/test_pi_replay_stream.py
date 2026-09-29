import copy
import json
from pathlib import Path

import pytest

from dsh.core.abort import AbortController
from dsh.llm.pi_replay import replay_state, to_pi_assistant
from dsh.llm.pi_stream import to_stream_chunks

FIXTURES = json.loads((Path(__file__).resolve().parents[1] / 'scripts/oracles/pi-fixtures.json').read_text(encoding='utf-8'))


def test_signed_replay_roundtrip_and_foreign_fallback_keep_durable_content():
    native, assistant = copy.deepcopy(FIXTURES[0]['message']), copy.deepcopy(FIXTURES[1]['message'])
    assert replay_state(native) == assistant['source']['replayState']
    restored = to_pi_assistant(assistant)
    assert restored['content'] == native['content']
    assert restored['responseId'] == 'response-1' and restored['usage']['totalTokens'] == 0
    assistant['source']['replayState']['response']['provider'] = 'another'
    degraded = []
    foreign = to_pi_assistant(assistant, degraded.append)
    assert len(degraded) == 1 and foreign['api'] == 'dsh-foreign'
    assert foreign['content'][0] == dict(type='thinking', thinking='reason')
    assert foreign['content'][2]['arguments'] == {'x': 1}


@pytest.mark.asyncio
async def test_caller_abort_and_missing_terminal_never_report_success():
    fixture = next(row for row in FIXTURES if row['id'] == 'error-server')
    controller = AbortController()
    controller.abort()
    async def events():
        for event in fixture['events']:
            yield event
    chunks = [chunk async for chunk in to_stream_chunks(events(), signal=controller.signal)]
    assert chunks[-1]['reason']['kind'] == 'aborted'
    assert 'replayState' not in chunks[-1]
    async def truncated():
        yield dict(type='text_start', contentIndex=0)
        yield dict(type='text_delta', contentIndex=0, delta='partial')
    with pytest.raises(Exception) as error:
        [chunk async for chunk in to_stream_chunks(truncated())]
    assert error.value.code == 'STREAM_CLOSED'
