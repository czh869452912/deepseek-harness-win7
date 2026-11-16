"""Current Loader and optional preset compositions without an inventory cache."""
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.typert.remote import Remote, TypertRemoteService

FIBER_PHASE = {0:'pending', 1:'loading', 2:'active', 3:'failed', 4:None, 5:'unloading'}


async def read_plugin_inventory(ctx):
    entries = []
    packages = ctx.get('pluginPackages')
    for entry in ctx.loader.entries():
        if entry.options.get('group'):
            continue
        base = getattr(entry.parent.tree.ctx, 'baseUrl', None)
        meta = packages.metaOf(entry.options['name'], base) if base is not None and packages is not None else None
        fiber = entry.fiber
        phase = None if fiber is None else FIBER_PHASE[fiber.state]
        row = dict(entryId=entry.id, moduleName=entry.options['name'], enabled=not entry.disabled, fiberPhase=phase)
        if fiber is not None and phase == 'failed':
            try:
                await fiber
            except Exception as error:
                row['diagnostic'] = js_to_string(error.value) if isinstance(error, ThrownValueError) else getattr(error, 'message', str(error))
        if meta is not None:
            row['meta'] = meta
        entries.append(row)
    presets = ctx.get('agentPresets')
    result = dict(entries=entries)
    if ctx.get('pluginManager') is not None:
        result['managementAvailable'] = True
    if presets is None:
        return result
    groups = []
    for composition in await await_callback_result(presets.compositionInventory()):
        rows = []
        for source in composition['rows']:
            row = {key:value for key,value in source.items() if key != 'fiberState'}
            row['fiberPhase'] = FIBER_PHASE[source['fiberState']] if 'fiberState' in source else None
            base = getattr(ctx, 'baseUrl', None)
            meta = packages.metaOf(source['moduleName'], base) if base is not None and packages is not None else None
            if meta is not None:
                row['meta'] = meta
            rows.append(row)
        groups.append(dict(composition, rows=rows))
    result['agentPresets'] = groups
    return result


class CurrentPluginInventory(TypertRemoteService):
    inject = ['loader']

    def __init__(self, ctx):
        super().__init__(ctx, 'pluginInventory')

    @Remote('list')
    async def list(self):
        return await read_plugin_inventory(self.ctx)
