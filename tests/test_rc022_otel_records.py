import json

import pytest

from dsh.session.otel_records_current import resolve_session_log_limits, session_log_record
from scripts.rc022_otel_records_probe import observe


@pytest.mark.asyncio
async def test_actual_source_channel_admission_and_logger_emission_corpus(tmp_path):
    rows = await observe()
    (tmp_path/'otel-records-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 185
    assert rows[0] == dict(value=4000000)
    assert any('maxExportBatchSize must not exceed maxQueueSize' in row.get('error', '') for row in rows)
    assert rows[121]['value']['severityNumber'] == 9
    assert rows[121]['value']['attributes']['sessionId'] == 'fixture-session'


def test_session_content_is_frozen_json_text_and_reserved_attributes_win():
    event = dict(seq=1, time=1000, type='fixture', data=dict(value='before'))
    source = dict(sessionId='owned', event=event, attributes=dict(sessionId='forged', content='forged'))
    result = session_log_record(source)
    event['data']['value'] = 'after'
    assert json.loads(result['attributes']['content'])['data']['value'] == 'before'
    assert result['attributes']['sessionId'] == 'owned'
    assert result['observedTimestamp'] == result['timestamp'] == 1000
    assert source['attributes']['sessionId'] == 'forged'


def test_arbitrary_python_integer_is_rejected_with_the_contract_error():
    with pytest.raises(ValueError, match='maxRequestBytes must be an integer'):
        resolve_session_log_limits(dict(maxRequestBytes=10**1000))
