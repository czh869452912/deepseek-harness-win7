"""Current default model Config references and ordered profile-editor saves."""
import asyncio

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED, js_to_string


class CurrentAgentDefaultModelConfig(Service):
    Config=Schema.object(dict(provider=Schema.string().required().volatile(),model=Schema.string().required().volatile(),reasoningEffort=Schema.string().volatile()))

    def __init__(self,ctx,config):
        super().__init__(ctx,'agentDefaultModel')
        self.owner_context=ctx;self.selection_config=config
        self.saves=asyncio.get_running_loop().create_future();self.saves.set_result(None)
        def settings(child):child.effect(lambda:child.settings.configure(dict(auto=False),ctx.fiber))
        ctx.inject(['settings'],settings)

    def currentSelection(self):
        value=dict(provider=self.selection_config['provider'].get(),model=self.selection_config['model'].get())
        effort=self.selection_config['reasoningEffort'].get()
        if effort is not _UNDEFINED:value['reasoningEffort']=effort
        return value

    current_selection=currentSelection

    def saveSelection(self,next_selection):
        entry=self.owner_context.fiber.entry;editor=self.ctx.get('configEditor')
        if entry is None or editor is None:
            future=asyncio.get_running_loop().create_future();future.set_result(None);return future
        config=dict(provider=next_selection['provider'],model=next_selection['model'])
        effort=next_selection.get('reasoningEffort',_UNDEFINED)
        if effort is not _UNDEFINED:config['reasoningEffort']=js_to_string(effort)
        previous=self.saves
        async def save():
            await asyncio.shield(previous)
            return await await_callback_result(editor.edit(entry,lambda *_:config))
        pending=asyncio.create_task(save())
        async def contain():
            try:await asyncio.shield(pending)
            except BaseException:pass
        self.saves=asyncio.create_task(contain())
        return asyncio.shield(pending)

    save_selection=saveSelection
