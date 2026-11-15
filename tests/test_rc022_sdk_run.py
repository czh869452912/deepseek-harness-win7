import json
from pathlib import Path
import pytest
from scripts.rc022_sdk_run_probe import observe


@pytest.mark.asyncio
async def test_sdk_coordinator_publication_cancellation_and_safe_failures():
    rows=await observe()
    assert len(rows)==25
    assert all(row['listeners']==0 for row in rows)
    assert rows[1]['value']['result']==dict(output=[dict(type='text',text='answer')],stopReason='completed')
    assert rows[13]['value']['result']['output']==[dict(type='text',text='partial')]
    assert rows[-1]['trace']==[]
    assert all(row['value'].get('sameDisposal',True) for row in rows)
    for row in rows:
        serialized=json.dumps(row['value'])
        assert 'private' not in serialized
        if row['options']:
            assert row['options']['cwd']=='origin' and row['options']['processCwd']=='child'
            assert row['environment']==dict(RC022_AMBIENT_TOKEN='explicit',DSH_RC022_FACT=None)


def test_sdk_event_validation_rejects_malformed_consumed_fields():
    from dsh.sdk.event_validation import validated_session_event
    from dsh.sdk.errors import SdkProtocolError
    for value in [None,1,{},dict(type='assistant/message'),dict(type='turn/end',data={}),dict(type='turn/end',data=dict(reason=dict(kind='aborted',reason=dict(kind='unknown'))))]:
        with pytest.raises(SdkProtocolError):validated_session_event(value)
    for reason in [dict(kind='future'),dict(kind='aborted',reason=dict(kind='hook',reason='policy'))]:
        event=dict(type='turn/end',data=dict(reason=reason))
        assert validated_session_event(event) is event
