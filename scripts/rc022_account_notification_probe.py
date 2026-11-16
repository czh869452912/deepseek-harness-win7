"""Actual notification query projection and exported login payload schemas."""
import copy
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def wire():
    return dict(id='notice', created_at='2026-10-28T06:12:11Z', display_until=None,
                title='News', body='Content', actions=[])


def cases():
    rows = []; notices = [wire(), None, [], {}, dict(wire(), token='discard-secret'), dict(wire(), id='')]
    for field, values in {
        'id': [None, 0, False], 'title': [None, '', 0], 'body': [None, '', []],
        'created_at': ['2024-02-29T23:59:59.123456789Z', '0000-02-29T00:00:00Z', '1900-02-29T00:00:00Z',
                       '2000-02-29T00:00:00Z', '2026-11-31T00:00:00Z', '2026-11-17T00:00Z',
                       '2026-11-17T00:00:00+23:59', '2026-11-17T00:00:00+24:00',
                       '2026-11-17T24:00:00Z', '2026-11-17T00:00:60Z', '2026-11-17t00:00:00z',
                       '2026-11-17T00:00:00+0000', '2026-11-17T00:00:00Z\n', '2026-11-17T00:00:00', None],
        'display_until': [None, '2026-10-28T06:12:11-03:30', '', False],
        'actions': [None, {}, [None], [{}], [dict(label='', style='primary', target=dict(type='dismiss', token='discard-secret'))],
                    [dict(label='Account', style='secondary', target=dict(type='app_route', name='account'))],
                    [dict(label='x', style='wrong', target=dict(type='unknown'))],
                    [dict(label=None, style='primary', target=dict(type='app_route', name='wrong'))],
                    [dict(label='x', style='primary', target=None)]],
        'data': [None, True, 0, '', ['x', {'nested': [None, 1]}], {'any': {'json': 'value'}}],
    }.items():
        notices.extend(dict(wire(), **{field: value}) for value in values)
    for field in wire():
        value = wire(); del value[field]; notices.append(value)
    for op, notice in itertools.product(('list', 'content'), notices):
        rows.append(dict(kind=op, value=dict(next_poll_after=600, notifications=[wire(), notice, wire()]) if op == 'list' else notice))
    for delay in (None, 0, -1, True, '600', .0001, 2147483.647, 2147483.648):
        rows.append(dict(kind='list', value=dict(next_poll_after=delay, notifications=[])))
    for value in (None, [], {}, {'next_poll_after': 1}, {'next_poll_after': 1, 'notifications': None}):
        rows.append(dict(kind='list', value=value))
    for value in (None, {}, {'acked': True}, {'acked': False}, {'acked': 0}, {'acked': None}, {'acked': 'true'}):
        rows.append(dict(kind='event', value=value))
    initial = dict(authorize_url='https://platform.example/dsh/authorize', authorize_id='id', expires_in=60)
    exchange = dict(token='token', authorized_url='https://platform.example/dsh/authorized')
    for kind, valid in [('initialization', initial), ('exchange', exchange)]:
        rows.extend(dict(kind=kind, value=value) for value in (valid, None, [], {}, dict(valid, user={'extra': True}, extra='discard-secret')))
        for field in valid:
            values = [None, False, 0, '', ' ', 'bad-url', 'mailto:a@b', 'javascript:', 'https://', 'https://host:65536',
                      'https://platform.example', 'ftp://host/', '\u96ea', 'token\n', 'token\x7f', 1, -1, .5]
            rows.extend(dict(kind=kind, value=dict(valid, **{field: value})) for value in values)
            value = dict(valid); del value[field]; rows.append(dict(kind=kind, value=value))
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8'); return [path]


async def observe():
    from dsh.core.abort import AbortController
    from dsh.credentials import account_notifications as notifications, account_protocol as protocol
    from dsh.credentials.account_payloads import parsePayload, payloadIssues
    rows = []; logs = []
    original = {key: getattr(protocol, key) for key in ('requestNotifications', 'requestNotificationContent', 'requestNotificationEvent', '_diagnostic')}
    protocol._diagnostic = lambda label, value: logs.append(dict(label=label, **value))
    try:
        for index, case in enumerate(cases()):
            start = len(logs); kind = case['kind']
            if kind in ('initialization', 'exchange'):
                issues = payloadIssues(kind, case['value'])
                result = dict(issues=issues) if issues else dict(value=parsePayload(kind, case['value']))
            else:
                async def response(*_): return copy.deepcopy(case['value'])
                for key in original:
                    if key != '_diagnostic': setattr(protocol, key, response)
                try:
                    args = ('https://platform.example', 'fixture-token')
                    tail = (AbortController().signal, {})
                    if kind == 'list': value = await notifications.readNotifications(*args, *tail)
                    elif kind == 'content': value = await notifications.readNotificationContent(*args, 'notice', *tail)
                    else:
                        await notifications.sendNotificationEvent(*args, 'notice', 'dismissed', *tail)
                        value = '<void>'
                    result = dict(value=value)
                except Exception as error: result = dict(error=dict(message=str(error), code=getattr(error, 'code', None)))
            rows.append(dict(index=index, result=result, diagnostics=logs[start:]))
        return rows
    finally:
        for key, value in original.items(): setattr(protocol, key, value)


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_notification.mts', 'Actual notification queries, safe projection, ISO datetimes and initialization/exchange schemas.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/account_notifications.py', ROOT/'dsh/credentials/account_payloads.py'], prepare=prepare)
