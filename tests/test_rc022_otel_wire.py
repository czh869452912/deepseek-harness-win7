import json

import pytest

from dsh.session.otel_records_current import event_log_record
from dsh.session.otel_wire_current import serialize_records
from scripts.rc022_otel_wire_probe import observe


@pytest.mark.asyncio
async def test_actual_pinned_http_json_documents_and_exact_byte_counts(tmp_path):
    rows = await observe()
    (tmp_path/'otel-wire-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 44
    assert rows[0]['captures'][0]['bytes'] == 842
    assert rows[1]['captures'][0]['bytes'] == 638
    for row in rows:
        assert row['warnings'] == [] and row['error'] is None


def test_timestamp_origin_hrtime_and_invalid_attribute_graphs():
    shared = dict(value='same')
    record = event_log_record(dict(eventName='fixture', body='body', timestamp=5.25,
        attributes={'': 'invalid', 'cycle': [shared, shared], 'valid': {'nested': None}}), 6.5)
    payload = json.loads(serialize_records([record], dict(name='scope'), {}, now=7, time_origin=1700000000000))
    log = payload['resourceLogs'][0]['scopeLogs'][0]['logRecords'][0]
    assert log['timeUnixNano'] == '1700000000005250000'
    assert log['observedTimeUnixNano'] == '1700000000006500000'
    assert [item['key'] for item in log['attributes']] == ['valid']
    record['timestamp'] = [1700000000, 123]
    payload = json.loads(serialize_records([record], dict(name='scope'), {}))
    assert payload['resourceLogs'][0]['scopeLogs'][0]['logRecords'][0]['timeUnixNano'] == '1700000000000000123'
