"""Current ACP controls persist Agent selections and project v4 tool results."""
from pathlib import Path
import json
import sys
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


class Runtime:
    def __init__(self, default):
        self.default = default

    def listProviders(self):
        return [dict(id='mock', name='Mock'), dict(id='other', name='Other')]

    async def list_models(self, provider):
        return [dict(id='first', name='First'), dict(id='next', name='Next')]

    async def resolve_model_info(self, provider, model, signal=None):
        return dict(reasoning=dict(efforts=[dict(id='low', name='Low'), dict(id='high', name='High')],
            **({} if self.default is None else dict(defaultEffort=self.default))))

    async def resolveCallConfig(self, selection, signal=None):
        return dict(selection, **(dict(reasoningEffort=self.default)
            if 'reasoningEffort' not in selection and self.default is not None else {}))


async def observe():
    from dsh.cordis import Context
    from dsh.core.runtime_v4 import SessionV4Plugin, SessionProjectionsV4Plugin
    from dsh.core.model_selection import AgentModel, MODEL_SELECTION_PROJECTION_DEFINITION
    from dsh.core.session.current_session import CurrentSession
    from dsh.acp.model_control import AcpModelControl
    from dsh.acp.updates import tool_result_update
    rows = []
    for default in (None, 'high'):
        ctx = Context()
        try:
            await ctx.plugin(SessionV4Plugin)
            await ctx.plugin(SessionProjectionsV4Plugin)
            projection = await ctx.get('sessionProjections').register(MODEL_SELECTION_PROJECTION_DEFINITION)
            session = ctx.get('sessions').create('acp-model')
            model = AgentModel(projection.readerFor(session), session, dict(provider='mock', model='first'))
            control = AcpModelControl(Runtime(default))
            control.install(ctx, NS(model=model))
            row = dict(default=default, initial=await control.options())
            row['switched'] = await control.set('model', '["other","next"]')
            row['effort'] = await control.set('reasoning_effort', 'low')
            row['reset'] = await control.set('reasoning_effort', '' if default is None else 'high')
            errors = []
            for key, value in [('model', False), ('model', 'missing'), ('reasoning_effort', 'extreme')]:
                try:
                    await control.set(key, value)
                except ValueError as error:
                    errors.append(str(error))
            row['errors'] = errors
            row['selected'] = model.current()
            events = session.snapshotEvents()
            row['selections'] = [event['data'] for event in events]
            restored = CurrentSession.create('restored', events, format_version=4)
            row['restored'] = AgentModel(projection.readerFor(restored), restored, {}).current()
            rows.append(row)
        finally:
            await ctx.fiber.dispose()
    ctx = Context()
    async def read_image(ref):
        return dict(ref=ref, data=b'image')
    ctx.set_service('attachments', NS(read_image=read_image))
    try:
        for failed in (False, True):
            message = dict(toolCallId='echo', isError=failed, content=[dict(type='text', text='result'),
                dict(type='image', attachment=dict(mediaType='image/png'))])
            rows.append(dict(update=await tool_result_update(ctx, dict(data=dict(message=message)))))
    finally:
        await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_acp_model.mts',
        'Actual current ACP model control over the real AgentModel/session projection: provider defaults, exact route changes, reasoning reset, rejected selections and cold restoration of pending durable selection; actual v4 success/failure tool-result updates.',
        [Path(__file__).resolve(), ROOT / 'dsh/acp/model_control.py', ROOT / 'dsh/acp/updates.py',
         ROOT / 'dsh/core/model_selection.py', ROOT / 'reference/packages/acp/acp/src/model-control.ts',
         ROOT / 'reference/packages/acp/acp/src/updates.ts'])
