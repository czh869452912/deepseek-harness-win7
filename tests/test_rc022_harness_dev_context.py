import json
from types import SimpleNamespace as NS

import pytest

from dsh.cordis.awaiting import await_callback_result
from dsh.context.harness_dev_current import CONSTANTS, SOURCE_ROOT
from dsh.llm.message import create_system_message
from scripts.rc022_candidate_fixture import setup


@pytest.mark.asyncio
async def test_actual_loader_v4_admitted_prompt_preserved_while_runtime_url_changes(tmp_path):
    url = ['http://127.0.0.1:8123/']
    def prepare(ctx): ctx.set_service('webApp', NS(getAdvertisedUrl=lambda:url[0]))
    ctx = await setup(tmp_path, extra=[('harness-dev-context', {})], prepare=prepare); lease = None
    async def inspect():
        value = await ctx.systemPrompt.assemble(dict(agent=lease.agent, scope=lease.agent.ctx))
        return {kind:[row for row in value[kind] if row['name'] in ('harness:source', 'app:web-surface')] for kind in ('sections', 'contexts')}
    try:
        lease = await ctx.agents.create(dict(sessionId='owner', agentOptions=dict(provider='script', model='m')))
        before = await inspect()
        assert [row['text'] for row in before['sections']] == [CONSTANTS['HARNESS_SOURCE_PROMPT'], CONSTANTS['WEB_SURFACE_PROMPT']]
        assert all(SOURCE_ROOT not in row['text'] and url[0] not in row['text'] for row in before['sections'])
        source = CONSTANTS['LEGACY_SOURCE']; web = CONSTANTS['LEGACY_WEB_SURFACE']
        legacy = source['prefix']+'C:/old {{checkout}}'+source['suffix']+'\n\n'+web['prefix']+'http://old:1234/'+web['suffix']
        lease.agent.session.append('system/message', dict(turn=1, step=1, message=create_system_message(legacy, 'harness', format_version=4)), surface_op='append')
        held = await inspect()
        url[0] = 'http://127.0.0.1:9123/'
        changed = await inspect()
        assert changed['sections'] == held['sections']
        assert 'C:/old {{checkout}}' in held['sections'][0]['text']
        assert 'http://old:1234/' in held['sections'][1]['text']
        assert url[0] in changed['contexts'][1]['text']
        lease.agent.session.append('system/message', dict(turn=1, step=2, message=create_system_message('', 'harness', format_version=4)), surface_op='append')
        assert (await inspect())['sections'] == held['sections']
        entry = next(entry for entry in ctx.loader.entries() if entry.options.get('id') == 'harness-dev-context')
        await await_callback_result(ctx.loader.update(entry.id, dict(disabled=True)))
        assert await inspect() == dict(sections=[], contexts=[])
        (tmp_path/'harness-dev-observations.json').write_text(json.dumps(dict(initial=before, admitted=held, changed=changed), indent=2), encoding='utf-8')
    finally:
        if lease is not None: await lease.dispose()
        await ctx.fiber.dispose()
