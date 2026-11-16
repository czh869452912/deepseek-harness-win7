"""Client identity and sanitized account projections against actual pinned Source."""
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows = []
    cookies = ['', 'a=1; b=2', 'a=old;a=new;A=upper', '=skip; =empty; flag; x=a=b',
               '\ufeffname\u00a0=\u2003value\ufeff; z= ; a=2', '\u0085name\u0085=\u0085v\u0085']
    rows.extend(dict(kind='cookies', base=a, override=b) for a, b in itertools.product(cookies, repeat=2))
    rows.extend(dict(kind='headers', platform=platform, client=dict(version='0.2.2-rc.3', locale=locale,
                timezoneOffsetSeconds=offset)) for platform, locale, offset in itertools.product(
                    (None, 'win32', 'darwin'), ('zh', 'ZH-CN', 'zh_TW', 'zh-Hant-CN', 'zhx', ' en', '', 'en-US'),
                    (0, -0.0, 28800, -12600, 1e-7, 1e21)))
    users = [None, [], '', {}, {'email': None}, {'email': ''}, {'email': 'masked@example.test'},
             dict(id='', email='e', mobile='', mobile_number='number', id_profile=dict(name=None, picture='')),
             dict(id='id', email='e', mobile=' ', id_profile=dict(name=' ', picture='url'), token='discard-secret')]
    for key, values in {'id': [None, '', 'id', 0, False, []], 'mobile': [None, '', 'mobile', 0, {}],
                        'mobile_number': [None, '', 'number', False],
                        'id_profile': [None, {}, [], '', {'name': None}, {'name': ''}, {'name': 'Name'},
                                       {'name': False}, {'name': 'Name', 'picture': 0},
                                       {'name': None, 'picture': None}, {'name': 'Name', 'picture': 'URL', 'token': 'discard-secret'}]}.items():
        users.extend(dict(email='e', **{key: value}) for value in values)
    rows.extend(dict(kind='profile', value=value) for value in users)
    amounts = ['', '0', '-0', '1.', '.1', '-.1', '1e+3', '0E-16', '001.20', '1e999999',
               '+1', '.', '-', '1e', '1E+', '1\n', '1\r\n', '1\u2028', '\u0661', ' 1', '1 ',
               'NaN', 'Infinity', 1, None, False, '12345678901234567890.00000000000000000001']
    for amount, currency, bonus in itertools.product(amounts, ('CNY', 'USD', 'EUR', None), (False, True)):
        wallet = dict(currency=currency, balance=amount, token='discard-secret')
        rows.append(dict(kind='balance', value=dict(normal_wallets=[] if bonus else [wallet], bonus_wallets=[wallet] if bonus else [])))
    rows.extend(dict(kind='balance', value=value) for value in (None, [], {}, {'normal_wallets': []},
                {'normal_wallets': [], 'bonus_wallets': None}, {'normal_wallets': [], 'bonus_wallets': []}))
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8'); return [path]


async def observe():
    from dsh.credentials.account_client_metadata import mergePlatformCookies, platformClientHeaders, platformWireLocale
    from dsh.credentials.account_details import profile, parseAccountDetail
    from dsh.credentials.account_errors import PlatformAuthError
    rows = []
    for index, case in enumerate(cases()):
        kind = case['kind']
        if kind == 'cookies': value = mergePlatformCookies(case['base'], case['override'])
        elif kind == 'headers':
            value = dict(headers=platformClientHeaders(case['platform'], case['client']), locale=platformWireLocale(case['client']['locale']))
        else:
            try: value = profile(case['value']) if kind == 'profile' else parseAccountDetail(kind, case['value'])
            except PlatformAuthError as error:
                value = dict(error=dict(code=error.code, message=error.message)) if kind == 'profile' else dict(status='failed')
        rows.append(dict(index=index, value=value))
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_projection.mts', 'Platform metadata, cookies, sanitized profiles and exact decimal wallet projection.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/account_client_metadata.py',
         ROOT/'dsh/credentials/account_details.py', ROOT/'dsh/credentials/account_errors.py'], prepare=prepare)
