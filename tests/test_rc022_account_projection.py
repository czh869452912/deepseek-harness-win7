import json

import pytest

from dsh.credentials.account_client_metadata import mergePlatformCookies
from dsh.credentials.account_details import profile, parseAccountDetail
from dsh.credentials.account_errors import PlatformAuthError
from scripts import rc022_account_projection_probe as corpus


@pytest.mark.asyncio
async def test_account_projection_source_corpus(tmp_path):
    rows = await corpus.observe()
    encoded = json.dumps(rows, ensure_ascii=True)
    (tmp_path/'account-projection-observations.json').write_text(encoded, encoding='utf-8')
    assert len(rows) == len(corpus.cases())
    assert 'discard-secret' not in encoded
    assert any(row['value'] == dict(status='ready', value=[], bonusWallets=[]) for row in rows)
    assert any(row['value'] == dict(status='failed') for row in rows)


def test_profile_and_wallet_values_are_detached_without_losing_precision():
    raw = dict(email='e', id_profile=dict(name='Name', picture='url'), token='secret')
    projected = profile(raw); raw['id_profile']['name'] = 'changed'
    assert projected == dict(id=None, avatarUrl='url', name='Name', contact='e')
    amount = '12345678901234567890.00000000000000000001'
    wallet = dict(currency='CNY', balance=amount, token='secret')
    balance = parseAccountDetail('balance', dict(normal_wallets=[wallet], bonus_wallets=[]))
    wallet['balance'] = '0'
    assert balance['value'] == [dict(currency='CNY', balance=amount)]
    with pytest.raises(PlatformAuthError):
        parseAccountDetail('balance', dict(normal_wallets=[], bonus_wallets=None))


def test_cookie_override_retains_case_sensitive_insertion_order_and_js_trim():
    assert mergePlatformCookies('a=1; A=2; \ufeffz = old; =empty', 'a=3; z=new; b=x=y') == 'a=3; A=2; z=new; =empty; b=x=y'
