"""Sanitized account profile and decimal wallet projections.

Only these projections may enter the client-facing account state. Unknown Platform
fields, including tokens in a user response, are deliberately discarded.
"""
import re

from dsh.credentials.account_errors import PlatformAuthError

_DECIMAL = re.compile(r'-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:e[+-]?[0-9]+)?', re.I | re.ASCII)


def _invalid():
    raise PlatformAuthError('protocol')


def profile(value):
    if not isinstance(value, dict) or not isinstance(value.get('email'), str):
        _invalid()
    if value.get('id') is not None and not isinstance(value['id'], str):
        _invalid()
    for key in ('mobile', 'mobile_number'):
        if key in value and not isinstance(value[key], str):
            _invalid()
    identity = value.get('id_profile')
    if identity is not None:
        if not isinstance(identity, dict) or 'name' not in identity:
            _invalid()
        if identity['name'] is not None and not isinstance(identity['name'], str):
            _invalid()
        if identity.get('picture') is not None and not isinstance(identity['picture'], str):
            _invalid()
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


def parseAccountDetail(field, value):
    """Validate one query result; failure is distinct from an empty wallet list."""
    if field == 'profile':
        return dict(status='ready', value=profile(value))
    if field != 'balance':
        raise KeyError(field)
    if not isinstance(value, dict):
        _invalid()
    return dict(status='ready', value=_wallets(value.get('normal_wallets')),
                bonusWallets=_wallets(value.get('bonus_wallets')))
