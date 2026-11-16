"""Validated localized account notifications; unsupported list items are skipped."""
import copy
import math
import re

from dsh.credentials import account_protocol as protocol
from dsh.credentials.account_errors import PlatformAuthError

_DATETIME = re.compile(r'([0-9]{4})-([0-9]{2})-([0-9]{2})T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])', re.ASCII)


def _datetime(value):
    if not isinstance(value, str):
        return False
    match = _DATETIME.fullmatch(value)
    if match is None:
        return False
    year, month, day = map(int, match.groups())
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return 1 <= month <= 12 and 1 <= day <= (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month-1]


def _issue(issues, path, code='invalid_type'):
    issues.append(dict(path=path, code=code))


def _notification(value):
    if not isinstance(value, dict):
        return None, [dict(path=[], code='invalid_type')]
    issues = []
    for key in ('id', 'created_at', 'display_until', 'title', 'body'):
        item = value.get(key)
        if key == 'display_until' and key in value and item is None:
            continue
        if not isinstance(item, str):
            _issue(issues, [key])
        elif key in ('created_at', 'display_until') and not _datetime(item):
            _issue(issues, [key], 'invalid_format')
    actions = value.get('actions'); projected = []
    if not isinstance(actions, list):
        _issue(issues, ['actions'])
    else:
        for index, action in enumerate(actions):
            path = ['actions', index]
            if not isinstance(action, dict):
                _issue(issues, path)
                continue
            if not isinstance(action.get('label'), str):
                _issue(issues, path+['label'])
            if action.get('style') not in ('primary', 'secondary'):
                _issue(issues, path+['style'], 'invalid_value')
            target = action.get('target'); target_value = None
            if not isinstance(target, dict):
                _issue(issues, path+['target'])
            elif target.get('type') not in ('app_route', 'dismiss'):
                _issue(issues, path+['target', 'type'], 'invalid_union')
            elif target['type'] == 'app_route':
                if target.get('name') != 'account':
                    _issue(issues, path+['target', 'name'], 'invalid_value')
                target_value = dict(type='app_route', name='account')
            else:
                target_value = dict(type='dismiss')
            projected.append(dict(label=action.get('label'), style=action.get('style'), target=target_value))
    if 'data' in value:
        issues.extend(_jsonIssues(value['data'], ['data']))
    if issues:
        return None, issues
    result = dict(id=value['id'], createdAt=value['created_at'], displayUntil=value['display_until'],
                  title=value['title'], body=value['body'], actions=projected)
    if 'data' in value:
        result['data'] = copy.deepcopy(value['data'])
    return result, []


def _jsonIssues(value, path):
    if value is None or isinstance(value, (str, bool)):
        return []
    if isinstance(value, (int, float)) and math.isfinite(value):
        return []
    if isinstance(value, list):
        return [issue for index, item in enumerate(value) for issue in _jsonIssues(item, path+[index])]
    if isinstance(value, dict):
        return [issue for key, item in value.items() for issue in _jsonIssues(item, path+[key])]
    return [dict(path=path, code='invalid_union')]


def _reject(issues):
    protocol._diagnostic('notification schema rejected', dict(issues=issues))
    raise PlatformAuthError('protocol')


async def readNotifications(origin, token, signal, headers):
    value = await protocol.requestNotifications(origin, token, signal, headers)
    if not isinstance(value, dict):
        _reject([dict(path=[], code='invalid_type')])
    issues = []; delay = value.get('next_poll_after')
    if not isinstance(delay, (int, float)) or isinstance(delay, bool) or not math.isfinite(delay):
        _issue(issues, ['next_poll_after'])
    elif delay <= 0:
        _issue(issues, ['next_poll_after'], 'too_small')
    elif delay > 2147483647/1000:
        _issue(issues, ['next_poll_after'], 'too_big')
    if not isinstance(value.get('notifications'), list):
        _issue(issues, ['notifications'])
    if issues:
        _reject(issues)
    notifications = []
    for index, entry in enumerate(value['notifications']):
        result, issues = _notification(entry)
        if issues:
            protocol._diagnostic('skipping unsupported notification', dict(index=index, issues=issues))
        else:
            notifications.append(result)
    return dict(nextPollAfterSeconds=delay, notifications=notifications)


async def readNotificationContent(origin, token, id, signal, headers):
    value = await protocol.requestNotificationContent(origin, token, id, signal, headers)
    result, issues = _notification(value)
    if issues:
        _reject(issues)
    if result['id'] != id:
        raise PlatformAuthError('protocol')
    return result


async def sendNotificationEvent(origin, token, id, event, signal, headers):
    value = await protocol.requestNotificationEvent(origin, token, id, event, signal, headers)
    if not isinstance(value, dict):
        _reject([dict(path=[], code='invalid_type')])
    if not isinstance(value.get('acked'), bool):
        _reject([dict(path=['acked'], code='invalid_type')])
