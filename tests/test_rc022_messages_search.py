import json

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.web.messages_search_current import CurrentWebSearchDeepSeek
from scripts.rc022_messages_search_probe import observe as observe_provider
from scripts.rc022_messages_search_plugin_probe import observe as observe_plugin


def test_canonical_messages_search_binding():
    assert resolve_harness_plugin('@deepseek-ai/dsh-web-search-deepseek') is CurrentWebSearchDeepSeek


@pytest.mark.asyncio
async def test_real_messages_search_account_ownership_and_failure_corpus(tmp_path):
    rows = await observe_provider()
    (tmp_path/'messages-search-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 72
    for row in rows[1:]:
        assert row['listeners'] == 0
        assert len(row['hits']) <= 1
        for record in row['records']:
            assert record['body']['thinking'] == dict(type='disabled')
        for hit in row['hits']:
            headers = hit['headers']
            if headers.get('x-dsh-auth-token'):
                assert 'authorization' not in headers and 'x-api-key' not in headers


@pytest.mark.asyncio
async def test_live_plugin_readiness_dispatch_and_owned_registration_corpus(tmp_path):
    rows = await observe_plugin()
    (tmp_path/'messages-plugin-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 190
    assert all(row['changes'] == 2 and row['afterDispose'] == dict(search=[], fetch=[]) for row in rows)
    for row in rows:
        boundary = row['result'][0]['readinessEvents']
        assert all(not isinstance(event, str) or not event.startswith('resolve:') for event in row['events'][:boundary])
    live = rows[-1]
    assert len(live['sent']) == 2
    assert live['sent'][0]['endpoint'] == 'https://environment.test/v1/messages'
    assert live['sent'][1]['endpoint'] == 'https://updated.test/v2/messages'
    assert live['sent'][1]['key'] == 'updated-key'
    assert live['sent'][1]['body']['model'] == 'updated-model'
