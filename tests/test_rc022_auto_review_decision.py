import pytest

from dsh.interaction.auto_review_decision import parse_decision, read_decision
from scripts import rc022_auto_review_decision_probe as probe


@pytest.mark.asyncio
async def test_closed_review_protocol_and_stream_failures():
    rows = {row['name']: row['result'] for row in await probe.observe()}
    assert len(rows) == 126
    valid = [value['value'] for name, value in rows.items() if name.startswith('json-') and 'value' in value]
    assert len(valid) == 9
    assert all(value['decision'] == 'deny' or 'reason' not in value for value in valid)
    for name in ('valid', 'reasoning', 'reasonings', 'end-authoritative', 'delta-after-end', 'unknown-index-text'):
        assert rows['stream-' + name] == dict(value=dict(risk='low', decision='allow'))
    assert rows['stream-provider-failure']['error'] == dict(message='provider secret', original=True)
    assert rows['stream-absent-finish']['error']['message'].endswith('no terminal finish')
    assert rows['stream-after-finish']['error']['message'].endswith('after its terminal finish')
    assert rows['stream-aborted']['error']['message'].endswith('aborted UNKNOWN: provider secret')


@pytest.mark.parametrize('text', [
    '{"risk":"low","decision":"deny"}',
    '{"risk":"high","decision":"allow"}',
    '{"risk":"medium","decision":"allow","reason":"authorize"}',
    '{"risk":"medium","decision":"allow","decision":"deny"}',
    '{"risk":"medium","decision":"deny","reason":null}',
])
def test_never_admit_invalid_review_combinations(text):
    with pytest.raises(RuntimeError):
        parse_decision(text)


@pytest.mark.asyncio
async def test_early_finish_rejection_closes_owned_stream_consumer():
    closed = []
    async def stream():
        try:
            yield dict(type='finish', reason=dict(kind='error', failure=dict(code='BROKEN', message='unavailable')))
            pytest.fail('read after terminal failure')
        finally:
            closed.append(True)
    source = stream()
    try:
        with pytest.raises(RuntimeError, match='error BROKEN: unavailable'):
            await read_decision(source)
        assert closed == [True]
    finally:
        await source.aclose()
    assert closed == [True]
