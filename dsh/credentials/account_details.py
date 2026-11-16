"""Sanitized account profile and decimal wallet projections.

Only these projections may enter the client-facing account state. Unknown Platform
fields, including tokens in a user response, are deliberately discarded.
"""
import re

from dsh.credentials.account_errors import PlatformAuthError

_DECIMAL = re.compile(r'-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[+-]?[0-9]+)?', re.I | re.ASCII)


def _invalid():
    raise PlatformAuthError('protocol')


def _profileIssues(value):
    if not isinstance(value, dict):
        return [dict(path=[], code='invalid_type')]
    issues = []
    if not isinstance(value.get('email'), str):
        issues.append(dict(path=['email'], code='invalid_type'))
    if value.get('id') is not None and not isinstance(value['id'], str):
        issues.insert(0, dict(path=['id'], code='invalid_type'))
    for key in ('mobile', 'mobile_number'):
        if key in value and not isinstance(value[key], str):
            issues.append(dict(path=[key], code='invalid_type'))
    identity = value.get('id_profile')
    if identity is not None:
        if not isinstance(identity, dict):
            issues.append(dict(path=['id_profile'], code='invalid_type'))
        else:
            if 'name' not in identity or identity['name'] is not None and not isinstance(identity['name'], str):
                issues.append(dict(path=['id_profile', 'name'], code='invalid_type'))
            if identity.get('picture') is not None and not isinstance(identity['picture'], str):
                issues.append(dict(path=['id_profile', 'picture'], code='invalid_type'))
    return issues


def profile(value):
    if _profileIssues(value):
        _invalid()
    identity = value.get('id_profile')
    identity = identity or {}
    return dict(id=value.get('id'), avatarUrl=identity.get('picture') or None,
                name=identity.get('name') or None,
                contact=value.get('mobile') or value.get('mobile_number') or value['email'] or None)


def _wallets(value):
    if not isinstance(value, list):
        _invalid()
    wallets = []
    for item in value:
        if not isinstance(item, dict) or item.get('currency') not in ('CNY', 'USD'):
            _invalid()
        balance = item.get('balance')
        if not isinstance(balance, str) or _DECIMAL.fullmatch(balance) is None:
            _invalid()
        wallets.append(dict(currency=item['currency'], balance=balance))
    return wallets


def _balanceIssues(value):
    if not isinstance(value, dict):
        return [dict(path=[], code='invalid_type')]
    issues = []
    for key in ('normal_wallets', 'bonus_wallets'):
        wallets = value.get(key)
        if not isinstance(wallets, list):
            issues.append(dict(path=[key], code='invalid_type'))
            continue
        for index, wallet in enumerate(wallets):
            path = [key, index]
            if not isinstance(wallet, dict):
                issues.append(dict(path=path, code='invalid_type'))
                continue
            if wallet.get('currency') not in ('CNY', 'USD'):
                issues.append(dict(path=path+['currency'], code='invalid_value'))
            balance = wallet.get('balance')
            if not isinstance(balance, str):
                issues.append(dict(path=path+['balance'], code='invalid_type'))
            elif _DECIMAL.fullmatch(balance) is None:
                issues.append(dict(path=path+['balance'], code='invalid_format'))
    return issues


def parseAccountDetail(field, value):
    """Validate one query result; failure is distinct from an empty wallet list."""
    from dsh.credentials.account_protocol import _diagnostic
    if field not in ('profile', 'balance'):
        raise KeyError(field)
    issues = _profileIssues(value) if field == 'profile' else _balanceIssues(value)
    if issues:
        _diagnostic(field+' schema rejected', dict(issues=issues))
        _invalid()
    if field == 'profile':
        return dict(status='ready', value=profile(value))
    return dict(status='ready', value=_wallets(value.get('normal_wallets')),
                bonusWallets=_wallets(value.get('bonus_wallets')))


async def readAccountDetail(field, origin, token, signal, headers):
    from dsh.credentials.account_protocol import requestAccount
    from dsh.credentials.account_errors import AccountUnauthorizedError
    path = '/auth-api/v0/users/current' if field == 'profile' else '/api/v0/users/get_user_summary'
    try:
        return parseAccountDetail(field, await requestAccount(origin, path, token, signal, headers))
    except AccountUnauthorizedError:
        raise
    except Exception:
        return dict(status='failed')
