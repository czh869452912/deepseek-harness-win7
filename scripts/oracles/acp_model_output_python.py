import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from dsh.acp.model_control import AcpModelControl
from dsh.acp.updates import assistant_updates, tool_call_update, tool_result_update
from dsh.core.model_selection import ModelSelection
from dsh.cordis.context import Context
from test_acp_model_output import ModelRuntime, ImageStore


def snapshot(control):
    value = control.snapshot()
    return None if value is None else value.to_dict()


async def main():
    observations = []
    runtime = ModelRuntime()
    control = AcpModelControl(runtime)
    errors = []
    for value in (False, 'missing'):
        try:
            await control.set('model', value)
        except ValueError as error:
            errors.append(str(error))
    observations.append(dict(mode='absent', options=await control.options(), snapshot=snapshot(control), errors=errors, calls=list(runtime.calls)))
    control = AcpModelControl(runtime, ModelSelection('mock', 'first'))
    observations.append(dict(mode='catalog', initial=await control.options(), changed=await control.set('model', '["other","next"]'), snapshot=snapshot(control)))
    runtime = ModelRuntime()
    runtime.catalog_available = False
    control = AcpModelControl(runtime, ModelSelection('private', '模型"'))
    observations.append(dict(mode='unlisted', options=await control.options(), snapshot=snapshot(control)))
    defaults = []
    for provider_default in (True, False):
        control = AcpModelControl(ModelRuntime(None if provider_default else 'high'), ModelSelection('mock', 'first'))
        initial = await control.options()
        try:
            await control.set('reasoning_effort', 'extreme')
        except ValueError as error:
            rejected = str(error)
        changed = await control.set('reasoning_effort', 'low')
        reset = await control.set('reasoning_effort', '' if provider_default else 'high')
        defaults.append(dict(providerDefault=provider_default, initial=initial, rejected=rejected, changed=changed, reset=reset, snapshot=snapshot(control)))
    observations.append(dict(mode='defaults', defaults=defaults))
    runtime = ModelRuntime()
    control = AcpModelControl(runtime, ModelSelection('mock', 'first'))
    initial = await control.options()
    runtime.available = runtime.catalog_available = False
    unavailable = await control.options()
    runtime.available = runtime.catalog_available = True
    observations.append(dict(mode='outage', initial=initial, unavailable=unavailable, restored=await control.options(), snapshot=snapshot(control)))
    runtime = ModelRuntime()
    runtime.gate = asyncio.Event()
    control = AcpModelControl(runtime, ModelSelection('mock', 'first'))
    pending = asyncio.create_task(control.set('model', 'invalid'))
    await runtime.entered.wait()
    following = asyncio.create_task(control.set('reasoning_effort', 'low'))
    await asyncio.sleep(0)
    blocked = not following.done()
    runtime.gate.set()
    try:
        await pending
    except ValueError as error:
        rejected = str(error)
    observations.append(dict(mode='serialized', blocked=blocked, rejected=rejected, next=await following, calls=runtime.calls, snapshot=snapshot(control)))
    control = AcpModelControl(ModelRuntime(), ModelSelection('mock', 'first'))
    await control.options()
    admitted = control.snapshot()
    control.pin_turn(3, admitted)
    admitted.model = 'external mutation'
    await control.set('model', '["other","next"]')
    pinned = control.selection.current.to_dict()
    control.release_turn(2)
    wrong_turn = control.selection.current.to_dict()
    control.release_turn(3)
    observations.append(dict(mode='pin', pinned=pinned, wrongTurn=wrong_turn, released=control.selection.current.to_dict(), future=snapshot(control)))
    ctx = Context()
    ctx.provide('attachments', ImageStore())
    ctx.provide('tokenMeter', SimpleNamespace(measure=lambda session: {'totalTokens': 7}))
    event = {'type': 'assistant/message', 'data': {'usage': {}, 'message': {'id': 'message-1', 'content': [
        {'type': 'reasoning', 'text': ''}, {'type': 'reasoning', 'text': 'thought'}, {'type': 'text', 'text': 'answer'},
        {'type': 'image', 'attachment': {'mediaType': 'image/png'}}, {'type': 'tool-call', 'id': 'hidden', 'name': 'hidden', 'arguments': '{}'}]}}}
    calls = [tool_call_update({'data': {'callId': 'call', 'name': 'echo', 'arguments': value}}) for value in ['{', 'NaN', 'Infinity', 'null', '{"value":[1,"中文"]}']]
    result = await tool_result_update(ctx, {'data': {'message': {'content': [{'toolCallId': 'call', 'isError': True,
        'content': [{'type': 'reasoning', 'text': 'hidden'}, {'type': 'text', 'text': 'failed'}, {'type': 'image', 'attachment': {'mediaType': 'image/png'}}]}]}}})
    observations.append(dict(mode='updates', assistant=await assistant_updates(ctx, SimpleNamespace(request_context=lambda: {'contextWindow': 100}), event), calls=calls, result=result))
    Path(sys.argv[1]).write_text(json.dumps(observations, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


asyncio.run(main())
