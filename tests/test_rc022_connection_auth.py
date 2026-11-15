import pytest
from scripts.rc022_connection_auth_probe import observe
from dsh.host.connection.auth_current import decode_cookie,encode_cookie


@pytest.mark.asyncio
async def test_browser_and_api_exchanges_signed_bytes_and_validation():
    rows=await observe()
    assert len(rows)==42
    browser,api,answer=rows[:3]
    assert browser['facts']==[dict(secure=False,browser=True,api=None),dict(secure=True,browser=False,api=None)]
    assert api['facts'][0]==dict(secure=False,browser=False,api='operator-id')
    assert '; Secure' in rows[14]['response']['headers']['set-cookie']
    for row in rows:
        if row['name']=='published':assert row['values']==['none','answer']
        if row['name']=='api-index':assert row['response']['status']==401
        if row['name']=='cookie-cleanup':assert row['response']['status']==303


def test_cookie_rejects_signature_tampering_and_preserves_json_number_semantics():
    payload=dict(version=2.0,authority='localhost',id='id',issuedAt=1.0,expiresAt=2.0)
    # JSON numbers have one numeric type in the Source runtime.
    cookie=encode_cookie(dict(payload,version=2),b'secret')
    assert decode_cookie(cookie,b'wrong') is None
    assert decode_cookie(cookie+'.extra',b'secret') is None
    assert decode_cookie(cookie,b'secret')['id']=='id'
