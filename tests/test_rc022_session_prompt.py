from types import SimpleNamespace as NS

import pytest

from dsh.api.session_commands_authorized import AuthorizedSessionCommands, resolve_prompt_receipts
from dsh.api.session_continuation import EMPTY, apply, ending_schema
from dsh.typert.remote import RemoteError
from scripts.rc022_session_prompt_probe import observe


@pytest.mark.asyncio
async def test_real_agent_failure_retry_deduplication_and_caller_journal(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 11
    for name in ('fresh-empty', 'after-completion'):
        assert rows[name]['error']['code'] == 'session/agent-busy'
        assert rows[name]['requests'] == rows[name]['admitted'] == 0
    for name in ('whitespace', 'bad-zone'):
        assert rows[name]['resolved'] == rows[name]['requests'] == 0
    assert rows['first-ending']['value'] is True
    for name in ('original', 'retry-1', 'retry-2'):
        assert rows[name]['value'] == dict(accepted=True)
        assert rows[name]['requests'] == 1
    for name in ('duplicate-original', 'duplicate-retry'):
        assert rows[name]['value'] == dict(accepted=True)
        assert rows[name]['requests'] == rows[name]['admitted'] == 0
    durable = rows['durable-messages']
    assert durable['endings'] == ['error', 'error', 'completed']
    assert durable['values'][0]['source'] == dict(kind='user', rpcId='original')
    assert durable['values'][1]['source'] == dict(kind='retry', rpcId='retry-1',
        clientTimeZone='Asia/Shanghai', principal=dict(kind='guest', id='g'))
    assert durable['values'][2]['content'] == []
    assert [len(messages) for messages in durable['requests']] == [1, 2, 3]


@pytest.mark.parametrize('code', ['RATE_LIMIT', 'SERVER', 'TIMEOUT', 'TRANSPORT',
    'EMPTY_RESPONSE', 'STREAM_CLOSED', 'AUTH', 'BAD_REQUEST', 'CANCELLED', 'UNKNOWN'])
def test_continuation_requires_admitted_input_and_unrecovered_attempt(code):
    message = dict(source=dict(kind='user'), content=[dict(type='text', text='task')])
    admitted = apply(EMPTY, dict(type='user/message', surfaceOp='append', data=message))
    failed = apply(admitted, dict(type='assistant/attempt'))
    end = dict(type='turn/end', seq=9, data=dict(reason=dict(kind='error', error=dict(code=code))))
    assert apply(failed, end)['ending'] == (9 if code in (
        'RATE_LIMIT', 'SERVER', 'TIMEOUT', 'TRANSPORT', 'EMPTY_RESPONSE', 'STREAM_CLOSED') else None)
    assert apply(admitted, end)['ending'] is None
    assert apply(apply(failed, dict(type='assistant/message')), end)['ending'] is None
    assert apply(apply(failed, dict(type='step/start')), end)['ending'] is None
    assert apply(apply(EMPTY, dict(type='assistant/attempt')), end)['ending'] is None
    assert apply(EMPTY, dict(type='user/message', surfaceOp='replace', data=message)) is EMPTY


@pytest.mark.parametrize('value', [-1, True, 0.5, 9007199254740992, float('inf'), float('nan')])
def test_persisted_continuation_rejects_invalid_sequence(value):
    with pytest.raises(ValueError):
        ending_schema(value)


def test_prompt_receipts_keep_first_insertion_identity_after_inherited_copy():
    class Journal:
        inheritedEventCount = 1
        events = []

        @property
        def seq(self):
            return len(self.events)

        def snapshotEvents(self, offset):
            return self.events[offset:]

    def message(identity, request):
        return dict(id=identity, source=dict(kind='retry', rpcId=request), content=[])

    journal = Journal()
    journal.events = [dict(seq=0, type='user/message', data=message('copied', 'ancestor'))]
    commands = AuthorizedSessionCommands(NS(), NS(), 'C:/work')
    assert not commands.has_prompt_request(journal, 'ancestor')
    journal.events.append(dict(seq=1, type='agent/inbox/spliced',
        data=dict(inserted=[message('copied', 'ancestor'), message('local', 'retry')], removed=[])))
    assert not commands.has_prompt_request(journal, 'ancestor')
    assert commands.has_prompt_request(journal, 'retry')
    journal.events.append(dict(seq=2, type='agent/inbox/spliced', data=dict(inserted=[], removed=['local'])))
    assert commands.has_prompt_request(journal, 'retry')


def test_staged_receipts_preserve_typed_image_and_deduplicate_binding_ids():
    image = dict(type='image', url='attachment:image', mediaType='image/png')
    part = dict(type='file', receiptId='receipt')
    content, receipts = resolve_prompt_receipts([part, part], lambda _: image)
    assert content == [image, image]
    assert receipts == ['receipt']
    with pytest.raises(RemoteError) as error:
        resolve_prompt_receipts([part], lambda _: None)
    assert error.value.code == 'session/attachment-invalid'
