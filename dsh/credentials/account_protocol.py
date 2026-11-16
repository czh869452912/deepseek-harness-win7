"""Bounded Platform envelopes, private authorization headers and safe diagnostics."""
import asyncio
import json
import math
import re
import sys
from urllib.parse import quote, urlsplit

from dsh.core.cancellation import aborted
from dsh.cordis.utils import _UNDEFINED
from dsh.cordis.json_text import stringify_json
from dsh.credentials.account_errors import PlatformAuthError, AccountUnauthorizedError
from dsh.credentials.account_urls import platformOrigin, browserUrl, loginOrigin
from dsh.credentials.account_http import request

_RESERVED = {'authorization', 'x-dsh-auth-token', 'host', 'content-length', 'transfer-encoding', 'connection', 'content-type'}
_HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", re.ASCII)


def _diagnostic(label, value):
    print('[deepseek-account] '+label, json.dumps(value, ensure_ascii=True), file=sys.stderr)


def platformHeaders(values):
    headers = {}
    for name, value in values.items():
        key = name.lower()
        if key in _RESERVED or key in headers:
            raise ValueError('account: requestHeaders contains a reserved or duplicate header')
        value = value.strip(' \t\r\n')
        if _HEADER.fullmatch(name) is None or any(ord(char) > 255 for char in value) or re.search('[\r\n\0]', value):
            raise ValueError('account: requestHeaders contains an invalid header')
        headers[key] = value
    return dict(sorted(headers.items()))


def _integer(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and -9007199254740991 <= value <= 9007199254740991 and math.isfinite(value) and int(value) == value


def _integerIssue(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return 'invalid_type'
        if int(value) == value:
            if value > 9007199254740991:
                return 'too_big'
            if value < -9007199254740991:
                return 'too_small'
    return 'invalid_type'


def _callerCancelled(signal):
    reason = getattr(signal, 'reason', None)
    return aborted(signal) and not (isinstance(reason, BaseException) and getattr(reason, 'name', None) == 'TimeoutError')


def _issues(payload):
    if not isinstance(payload, dict):
        return [dict(path=[], code='invalid_type')]
    issues = []
    if type(payload.get('code')) not in (int, float) or payload.get('code') != 0:
        issues.append(dict(path=['code'], code='invalid_value'))
    data = payload.get('data')
    if not isinstance(data, dict):
        issues.append(dict(path=['data'], code='invalid_type'))
    else:
        if not _integer(data.get('biz_code')):
            issues.append(dict(path=['data', 'biz_code'], code=_integerIssue(data.get('biz_code'))))
        if 'biz_data' not in data:
            issues.append(dict(path=['data', 'biz_data'], code='invalid_type'))
    return issues


async def _platformRequest(url, method, headers, body, signal):
    path = urlsplit(url).path
    authenticated = any(key.lower() == 'x-dsh-auth-token' for key in headers)
    stage = None
    try:
        async with request(url, method, headers, body, signal) as (response, chunks):
            status = response['status']
            if status == 401 and authenticated:
                if not _callerCancelled(signal):
                    _diagnostic('request failed', dict(path=path, status=status, errorCode='expired'))
                raise AccountUnauthorizedError()
            if not 200 <= status < 300 or not response['hasBody']:
                if not _callerCancelled(signal):
                    _diagnostic('request failed', dict(path=path, status=status, errorCode='network'))
                raise PlatformAuthError('network')
            stage = 'read-body'; size = 0; received = []; codes = {}; issues = None
            try:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > 65536:
                        stage = 'body-limit'
                        raise PlatformAuthError('protocol')
                    received.append(chunk)
                stage = 'parse-json'
                payload = json.loads(b''.join(received).decode('utf-8', 'replace'),
                                     parse_constant=lambda text: (_ for _ in ()).throw(ValueError(text)))
                if isinstance(payload, dict):
                    data = payload.get('data')
                    if _integer(payload.get('code')) and ('data' not in payload or isinstance(data, dict) and _integer(data.get('biz_code'))):
                        codes['code'] = payload['code']
                        if data is not None:
                            codes['bizCode'] = data['biz_code']
                    if type(payload.get('code')) in (int, float) and payload['code'] == 40003 and authenticated:
                        raise AccountUnauthorizedError()
                stage = 'envelope'; issues = _issues(payload)
                if issues:
                    raise PlatformAuthError('protocol')
                issues = None; stage = 'business-code'
                if payload['data']['biz_code'] != 0:
                    raise PlatformAuthError('protocol')
                return payload['data'].get('biz_data', _UNDEFINED)
            except Exception as error:
                if not _callerCancelled(signal):
                    detail = dict(path=path, status=status, stage=stage, **codes)
                    if issues is not None:
                        detail['issues'] = issues
                    detail['errorCode'] = error.code if isinstance(error, PlatformAuthError) else 'protocol'
                    _diagnostic('response rejected', detail)
                if isinstance(error, PlatformAuthError):
                    raise
                raise PlatformAuthError('protocol') from None
    except PlatformAuthError:
        raise
    except asyncio.CancelledError:
        raise
    except Exception:
        if not _callerCancelled(signal):
            _diagnostic('request failed', dict(path=path, errorCode='no-response', aborted=aborted(signal)))
        raise PlatformAuthError('no-response') from None


async def requestPlatform(origin, method, body, signal, headers):
    return await _platformRequest(origin+'/auth-api/v0/dsh/'+method, 'POST', dict(headers, **{'content-type': 'application/json'}), stringify_json(body), signal)


async def requestAccount(origin, path, token, signal, headers):
    return await _platformRequest(origin+path, 'GET', dict(headers, **{'x-dsh-auth-token': token}), None, signal)


async def requestNotifications(origin, token, signal, headers):
    return await requestAccount(origin, '/api/v0/users/notifications/list', token, signal, headers)


async def requestNotificationContent(origin, token, id, signal, headers):
    return await requestAccount(origin, '/api/v0/users/notifications/content?id='+quote(id, safe="-_.!~*'()"), token, signal, headers)


async def requestNotificationEvent(origin, token, id, event, signal, headers):
    values = dict(headers, **{'x-dsh-auth-token': token, 'content-type': 'application/json'})
    return await _platformRequest(origin+'/api/v0/users/notifications/events', 'POST', values,
                                  stringify_json(dict(notification_id=id, type=event)), signal)


async def logoutAccount(origin, token, signal, headers):
    await _platformRequest(origin+'/auth-api/v0/users/logout', 'POST', dict(headers, **{'x-dsh-auth-token': token}), None, signal)
