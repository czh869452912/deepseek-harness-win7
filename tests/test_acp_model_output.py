import asyncio
import base64
from types import SimpleNamespace

import pytest

from dsh.acp.model_control import AcpModelControl, AcpModelConfigError, model_value, selection_for
from dsh.acp.content import AcpContentError, admit_acp_prompt, assistant_block_to_acp, supports_acp_image_prompts
from dsh.acp.updates import assistant_updates, tool_call_update, tool_result_update
from dsh.attachment.error import AttachmentError
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.model_selection import ModelSelection


class ModelRuntime:
    def __init__(self, default='high'):
        self.default = default
        self.available = True
        self.catalog_available = True
        self.modalities = ['text', 'image']
        self.calls = []
        self.gate = None
        self.entered = asyncio.Event()

    def listProviders(self):
        return [{'id': 'mock', 'name': 'Mock'}, {'id': 'other', 'name': 'Other'}]

    async def list_models(self, provider):
        if not self.catalog_available:
            raise RuntimeError('catalog missing')
        return [{'provider': provider, 'id': 'first', 'name': 'First'},
                {'provider': provider, 'id': 'next', 'name': 'Next', 'description': 'A different route'}]

    async def resolve_model_info(self, provider, model, signal=None):
        if not self.available:
            raise RuntimeError('route missing')
        reasoning = {'efforts': [{'id': 'low', 'name': 'Low', 'description': 'Less thought.'}, {'id': 'high', 'name': 'High'}]}
        if self.default is not None:
            reasoning['defaultEffort'] = self.default
        return {'provider': provider, 'id': model, 'name': model, 'reasoning': reasoning, 'inputModalities': self.modalities}

    async def resolveCallConfig(self, selection, signal=None):
        self.calls.append(dict(selection))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if not self.available:
            raise RuntimeError('route missing')
        config = dict(selection)
        if config.get('reasoningEffort') is None and self.default is not None:
            config['reasoningEffort'] = self.default
        return config


@pytest.mark.asyncio
async def test_absent_route_rejects_invalid_mutations_without_discovering_catalog():
    runtime = ModelRuntime()
    control = AcpModelControl(runtime)
    assert await control.options() == []
    with pytest.raises(AcpModelConfigError, match='requires a select value'):
        await control.set('model', False)
    with pytest.raises(AcpModelConfigError, match='no model selection'):
        await control.set('model', 'missing')
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_grouped_options_keep_full_route_identity_and_reasoning_defaults():
    control = AcpModelControl(ModelRuntime(), ModelSelection('mock', 'first'))
    options = await control.options()
    assert options[0]['currentValue'] == '["mock","first"]'
    assert [item['group'] for item in options[0]['options']] == ['mock', 'other']
    assert options[1]['currentValue'] == 'high'
    assert options[1]['options'] == [{'value': 'low', 'name': 'Low', 'description': 'Less thought.'}, {'value': 'high', 'name': 'High'}]
    switched = await control.set('model', model_value('other', 'next'))
    assert switched[0]['currentValue'] == '["other","next"]'
    with pytest.raises(AcpModelConfigError, match='unknown model'):
        await control.set('model', 'next')
    assert control.snapshot().provider == 'other'


@pytest.mark.asyncio
async def test_unlisted_route_and_catalog_failure_do_not_drop_selection():
    runtime = ModelRuntime()
    runtime.catalog_available = False
    control = AcpModelControl(runtime, ModelSelection('private', '模型"'))
    options = await control.options()
    assert options[0]['options'] == [{'group': 'private', 'name': 'private', 'options': [{'value': '["private","模型\\\""]', 'name': '模型"'}]}]
    runtime.available = False
    degraded = await control.options()
    assert [item['id'] for item in degraded] == ['model']
    assert control.snapshot().to_dict() == {'provider': 'private', 'model': '模型"'}
    runtime.available = True
    assert len(await control.options()) == 2


@pytest.mark.asyncio
async def test_first_unresolvable_route_rejects_instead_of_inventing_options():
    runtime = ModelRuntime()
    runtime.available = False
    control = AcpModelControl(runtime, ModelSelection('mock', 'first'))
    with pytest.raises(RuntimeError, match='route missing'):
        await control.options()
    runtime.available = True
    assert (await control.options())[0]['currentValue'] == '["mock","first"]'


@pytest.mark.asyncio
@pytest.mark.parametrize('default', [None, 'high'])
async def test_reasoning_validation_releases_serialized_mutation_slot(default):
    control = AcpModelControl(ModelRuntime(default), ModelSelection('mock', 'first'))
    initial = await control.options()
    assert initial[1]['currentValue'] == (default or '')
    with pytest.raises(AcpModelConfigError, match='unknown reasoning effort'):
        await control.set('reasoning_effort', 'extreme')
    assert (await control.set('reasoning_effort', 'low'))[1]['currentValue'] == 'low'
    if default is None:
        assert (await control.set('reasoning_effort', ''))[1]['currentValue'] == ''
        assert 'reasoningEffort' not in control.snapshot().to_dict()
    else:
        with pytest.raises(AcpModelConfigError):
            await control.set('reasoning_effort', '')


@pytest.mark.asyncio
async def test_mutations_are_serialized_and_failed_predecessor_does_not_wedge_successor():
    runtime = ModelRuntime()
    control = AcpModelControl(runtime, ModelSelection('mock', 'first'))
    runtime.gate = asyncio.Event()
    pending = asyncio.create_task(control.set('model', 'invalid'))
    await runtime.entered.wait()
    following = asyncio.create_task(control.set('reasoning_effort', 'low'))
    await asyncio.sleep(0)
    assert not following.done()
    runtime.gate.set()
    with pytest.raises(AcpModelConfigError):
        await pending
    assert (await following)[1]['currentValue'] == 'low'


@pytest.mark.asyncio
async def test_turn_selection_is_detached_and_survives_mutation_until_exact_release():
    control = AcpModelControl(ModelRuntime(), ModelSelection('mock', 'first'))
    await control.options()
    admitted = control.snapshot()
    control.pin_turn(3, admitted)
    admitted.model = 'external mutation'
    await control.set('model', model_value('other', 'next'))
    assert control.selection.current.to_dict() == {'provider': 'mock', 'model': 'first'}
    control.release_turn(2)
    assert control.selection.current.model == 'first'
    control.release_turn(3)
    assert control.selection.current.model == 'next'


def test_logged_route_restores_explicit_effort_and_leaves_adapter_defaults_owned_by_provider():
    fallback = ModelSelection('fallback', 'unused')
    logged = {'config': {'provider': 'saved', 'model': 'model', 'reasoningEffort': 'low'}}
    assert selection_for(logged, fallback).to_dict() == logged['config']
    assert selection_for(dict(logged, adapterDefaults={'reasoningEffort': True}), fallback).to_dict() == {'provider': 'saved', 'model': 'model'}
    assert selection_for(None, fallback).to_dict() == fallback.to_dict()


class ImageStore:
    image_limits = {'mediaTypes': ['image/png']}

    def __init__(self):
        self.batches = []
        self.failure = None
        self.gate = None
        self.entered = asyncio.Event()

    async def save_images(self, images):
        self.batches.append(images)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.failure is not None:
            raise self.failure
        return [{'sha256': 'image-' + str(index), 'mediaType': image['mediaType']} for index, image in enumerate(images)]

    async def read_image(self, ref):
        if self.failure is not None:
            raise self.failure
        return {'ref': ref, 'data': b'image'}


def image_fixture():
    ctx = Context()
    runtime, store = ModelRuntime(), ImageStore()
    ctx.provide('llm', runtime)
    ctx.provide('attachments', store)
    return ctx, runtime, store


def image_block(data=b'image'):
    return {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(data).decode('ascii')}


@pytest.mark.asyncio
async def test_image_advertisement_requires_both_exact_route_and_deployment_media_support():
    ctx, runtime, store = image_fixture()
    assert not await supports_acp_image_prompts(ctx)
    assert await supports_acp_image_prompts(ctx, 'mock', 'first')
    runtime.modalities = ['text']
    assert not await supports_acp_image_prompts(ctx, 'mock', 'first')
    runtime.modalities = ['image']
    store.image_limits = {'mediaTypes': []}
    assert not await supports_acp_image_prompts(ctx, 'mock', 'first')


@pytest.mark.asyncio
@pytest.mark.parametrize('late_invalid', [{'type': 'audio'}, {'type': 'unexpected'}, {'type': 'image', 'mimeType': 'image/png', 'data': 'aA==\n'}, {'type': 'image', 'mimeType': 'image/png', 'data': 'aB=='}])
async def test_entire_prompt_is_validated_before_first_image_write(late_invalid):
    ctx, runtime, store = image_fixture()
    with pytest.raises(AcpContentError):
        await admit_acp_prompt(ctx, ModelSelection('mock', 'first'), [image_block(), late_invalid], True)
    assert store.batches == []


@pytest.mark.asyncio
async def test_images_use_one_batch_and_keep_wire_text_image_order():
    ctx, runtime, store = image_fixture()
    blocks = [{'type': 'text', 'text': 'before'}, image_block(), image_block(b'next'), {'type': 'text', 'text': 'after'}]
    content = await admit_acp_prompt(ctx, ModelSelection('mock', 'first'), blocks, True)
    assert [item['type'] for item in content] == ['text', 'image', 'image', 'text']
    assert len(store.batches) == 1 and len(store.batches[0]) == 2
    assert content[1]['attachment']['sha256'] == 'image-0'
    assert content[2]['attachment']['sha256'] == 'image-1'
    assert await assistant_block_to_acp(ctx, content[1]) == image_block()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,kind', [(AttachmentError('invalid bytes', 'INVALID_IMAGE'), 'invalid'), (OSError('disk fault'), 'internal')])
async def test_image_storage_failures_preserve_admission_category_without_fake_image_success(failure, kind):
    ctx, runtime, store = image_fixture()
    store.failure = failure
    with pytest.raises(AcpContentError) as caught:
        await admit_acp_prompt(ctx, ModelSelection('mock', 'first'), [image_block()], True)
    assert caught.value.kind == kind and caught.value.__cause__ is failure
    with pytest.raises(AcpContentError, match='unavailable or corrupt') as output:
        await assistant_block_to_acp(ctx, {'type': 'image', 'attachment': {'mediaType': 'image/png'}})
    assert output.value.kind == 'internal'


@pytest.mark.asyncio
async def test_cancelled_image_write_never_reconstructs_late_prompt_content():
    ctx, runtime, store = image_fixture()
    controller = AbortController()
    store.gate = asyncio.Event()
    pending = asyncio.create_task(admit_acp_prompt(ctx, ModelSelection('mock', 'first'), [image_block()], True, controller.signal))
    await store.entered.wait()
    controller.abort(RuntimeError('cancelled image admission'))
    store.gate.set()
    with pytest.raises(RuntimeError, match='cancelled image admission'):
        await pending


@pytest.mark.asyncio
async def test_committed_assistant_updates_preserve_block_order_and_real_usage_capacity():
    ctx = Context()
    ctx.provide('tokenMeter', SimpleNamespace(measure=lambda session: {'totalTokens': 7}))
    session = SimpleNamespace(request_context=lambda: {'contextWindow': 100})
    event = {'type': 'assistant/message', 'data': {'usage': {}, 'message': {'id': 'message-1', 'content': [
        {'type': 'reasoning', 'text': ''}, {'type': 'reasoning', 'text': 'thought'}, {'type': 'text', 'text': 'answer'},
        {'type': 'tool-call', 'id': 'hidden', 'name': 'hidden', 'arguments': '{}'}]}}}
    assert await assistant_updates(ctx, session, event) == [
        {'sessionUpdate': 'agent_thought_chunk', 'messageId': 'message-1', 'content': {'type': 'text', 'text': 'thought'}},
        {'sessionUpdate': 'agent_message_chunk', 'messageId': 'message-1', 'content': {'type': 'text', 'text': 'answer'}},
        {'sessionUpdate': 'usage_update', 'used': 7, 'size': 100}]


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', ['{', 'NaN', 'Infinity'])
async def test_tool_updates_preserve_malformed_json_and_failed_result_without_hidden_reasoning(arguments):
    ctx = Context()
    assert tool_call_update({'data': {'callId': 'bad', 'name': 'broken', 'arguments': arguments}})['rawInput'] == arguments
    event = {'data': {'message': {'content': [{'toolCallId': 'bad', 'isError': True,
             'content': [{'type': 'reasoning', 'text': 'hidden'}, {'type': 'text', 'text': 'failed'}]}]}}}
    assert await tool_result_update(ctx, event) == {'sessionUpdate': 'tool_call_update', 'toolCallId': 'bad',
        'status': 'failed', 'content': [{'type': 'content', 'content': {'type': 'text', 'text': 'failed'}}]}
