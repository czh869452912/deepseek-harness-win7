import json

import pytest

from dsh.compaction.current import CurrentCompactionEngine
from dsh.compaction.engine import ManualCompactionError
from dsh.llm.llm_service import LlmError
from scripts import rc022_image_offload_probe as corpus
from scripts.rc022_candidate_fixture import setup


class ImageAdapter:
    def __init__(self, mode='success'):
        self.requests = []
        self.mode = mode

    async def resolve_model(self, provider, model, signal=None):
        return dict(provider=provider, id=model, name=model, inputModalities=['text', 'image'])

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1 or self.mode == 'exhausted':
            raise LlmError('image budget exceeded', 'IMAGE_OFFLOAD_REQUIRED', offloadImages=1)
        if self.mode == 'terminal':
            raise LlmError('provider outage', 'SERVER')
        yield dict(type='block-start', index=0, blockType='text')
        yield dict(type='block-end', index=0, block=dict(type='text', text='checkpoint'))
        yield dict(type='finish', reason=dict(kind='stop'))


def omitted(request):
    return [block['attachment']['name'] for message in request['messages'] for block in message['content']
            if block['type'] == 'image' and block.get('offloaded') is True]


@pytest.mark.asyncio
async def test_original_selection_listener_and_failure_snapshot_corpus(tmp_path):
    rows = await corpus.observe()
    assert len(rows) == 33
    assert rows[2]['decisions'][0]['targets'] == [dict(seq=0, imageIndexes=[0])]
    assert rows[3]['decisions'][0]['targets'] == [dict(seq=1, imageIndexes=[0])]
    assert rows[14]['result'] == dict(kind='retry')
    assert rows[21]['decisions'] == []  # missing summary budget
    assert rows[22]['result']['same']
    assert all(row['projections'] == 0 and row['after'] == 'unloaded' for row in rows[:23])
    (tmp_path/'image-offload-observations.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')


@pytest.mark.asyncio
async def test_real_agent_retries_after_durable_image_repair_without_provider_retry(tmp_path):
    ctx = await setup(tmp_path, extra=[('compaction-image-offload', {})])
    adapter = ImageAdapter()
    ctx.llm.registerAdapter(['images'], adapter)
    handle = await ctx.agents.create(dict(sessionId='agent', agentOptions=dict(provider='images', model='m')))
    try:
        handle.agent.followup(corpus.message('input', [corpus.image('first'), corpus.image('second')]))
        await handle.agent.whenIdle()
        assert len(adapter.requests) == 2
        assert [omitted(request) for request in adapter.requests] == [[], ['first']]
        events = handle.agent.session.snapshotEvents()
        assert len([event for event in events if event['type'] == 'image/offload']) == 1
        assert not any(event['type'] == 'llm/retry' for event in events)
        (tmp_path/'agent-offload-observations.json').write_text(json.dumps(dict(
            omissions=[omitted(request) for request in adapter.requests], events=[event['type'] for event in events]), indent=2), encoding='utf-8')
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'terminal', 'exhausted'])
async def test_summary_repairs_only_selected_nodes_and_reprices_before_commit(tmp_path, mode):
    ctx = await setup(tmp_path, extra=[('compaction-image-offload', {})])
    adapter = ImageAdapter(mode)
    ctx.llm.registerAdapter(['images'], adapter)
    handle = await ctx.agents.create(dict(sessionId='summary', agentOptions=dict(provider='images', model='m')))
    session = handle.agent.session
    measurements = []
    class Meter:
        def measure(self, subject):
            nodes = []
            for seq in subject.surface.nodes:
                message = subject.deriveEventMessage(subject.eventAt(seq))
                count = sum(block.get('offloaded') is True for block in message['content'] if block['type'] == 'image')
                nodes.append(dict(seq=seq, tokens=10000-count*100, heuristicTokens=10000-count*100))
            measurements.append(nodes)
            return dict(nodes=nodes)

        def estimate_message(self, value):
            return 1
    ctx.set_service('tokenMeter', Meter())
    try:
        selected = session.append('user/message', corpus.message('selected', [corpus.image('first'), corpus.image('second')]), surface_op='append')
        outside = session.append('user/message', corpus.message('outside', [corpus.image('outside')]), surface_op='append')
        engine = CurrentCompactionEngine(config=dict(auto=False), ctx=ctx)
        if mode == 'success':
            result = await engine.compact_region(session, selected['seq'], selected['seq'], agent=handle.agent, manual=True)
            assert result['shadowedTokenCount'] == 9900
            assert selected['seq'] not in session.surface.nodes
            assert outside['seq'] in session.surface.nodes
        else:
            with pytest.raises(ManualCompactionError) as raised:
                await engine.compact_region(session, selected['seq'], selected['seq'], agent=handle.agent, manual=True)
            assert raised.value.cause.code == ('SERVER' if mode == 'terminal' else 'IMAGE_OFFLOAD_REQUIRED')
            assert list(session.surface.nodes) == [selected['seq'], outside['seq']]
        assert [omitted(request) for request in adapter.requests] == ([[], ['first'], ['first', 'second']] if mode == 'exhausted' else [[], ['first']])
        decisions = [event for event in session.snapshotEvents() if event['type'] == 'image/offload']
        assert all(target['seq'] == selected['seq'] for event in decisions for target in event['data']['targets'])
        assert session.deriveEventMessage(session.eventAt(outside['seq']))['content'][0].get('offloaded') is not True
        (tmp_path/'summary-offload-observations.json').write_text(json.dumps(dict(
            mode=mode, decisions=decisions, measurements=measurements,
            omissions=[omitted(request) for request in adapter.requests]), indent=2), encoding='utf-8')
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()
