"""Observe actual pinned channel constructors and their logger emission boundary."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    values = [None, False, True, 0, 1, -1, 1.5, 512, 2048, 4000000, 4000001,
              2147483647, 2147483648, 9007199254740991, 9007199254740992, '1', {}, []]
    rows = [dict(kind='limits', options={})]
    for value in values:
        rows.append(dict(kind='limits', options=dict(maxRequestBytes=value)))
        for key in ['maxQueueSize', 'maxExportBatchSize', 'scheduledDelayMillis', 'exportTimeoutMillis']:
            rows.append(dict(kind='limits', options=dict(processor={key: value})))
    rows += [dict(kind='limits', options=dict(processor=dict(maxQueueSize=queue, maxExportBatchSize=batch)))
             for queue in [1, 2, 511, 512, 1024, 2048] for batch in [1, 2, 512, 1024, 2048]]
    event = dict(seq=2, time=1700000000123.5, type='message/put', data=dict(text='synthetic\n\U0001f600', **{'10': 'ten', '2': 'two'}))
    for severity in [None, *range(26), -1, 1.5, '9', 'INFO', False]:
        rows.append(dict(kind='session', record=dict(sessionId='fixture-session', event=event,
            severityNumber=severity, attributes=dict(sessionId='override', content='override', flag=True, count=1))))
        rows.append(dict(kind='event', record=dict(eventName='fixture-event', body='synthetic', timestamp=1700000000123.5,
            severityNumber=severity, attributes=dict(flag=True, count=1))))
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.session.otel_records_current import resolve_session_log_limits, session_log_record, event_log_record
    from dsh.cordis.utils import _UNDEFINED
    def plain(value):
        if isinstance(value, dict): return {key: plain(item) for key, item in value.items() if item is not _UNDEFINED}
        if isinstance(value, list): return [plain(item) for item in value]
        return value
    rows = []
    for case in cases():
        try:
            value = (resolve_session_log_limits(case['options']) if case['kind'] == 'limits'
                else session_log_record(case['record']) if case['kind'] == 'session'
                else event_log_record(case['record'], 1700000000999))
            rows.append(dict(value=plain(value)))
        except Exception as error: rows.append(dict(error=str(error)))
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_otel_records.mts',
        'Pinned actual SessionLogReporter/EventLogReporter constructor admission and intercepted SDK logger emissions; pure Native record factories, not transport or queue acceptance.',
        [Path(__file__).resolve(), ROOT/'dsh/session/otel_records_current.py'], prepare=prepare)
