"""Pair current client graph/restart state over shared byte/stat fixtures."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';directory=WORKSPACE/'node_modules'/'fixture-client';directory.mkdir(parents=True)
    (directory/'host.js').write_text('export default () => {}',encoding='utf-8')
    (directory/'client.js').write_text('module.exports = { value: 1 };',encoding='utf-8')
    (directory/'next.js').write_text('module.exports = { value: 200 };',encoding='utf-8')
    path=output/'inputs.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE))),encoding='utf-8');return [path]


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.host.client_modules.current import CurrentClientModuleRegistry
    workspace=workspace or WORKSPACE;directory=workspace/'node_modules'/'fixture-client';ctx=Context();rows=[]
    entry=NS(options=dict(name='fixture-client'),fiber=NS(),disabled=False,parent=NS(tree=NS(ctx=NS(baseUrl=workspace.as_uri()+'/'))))
    entries=[entry];ctx.provide('loader',NS(entries=lambda:iter(entries)))
    def write(declaration=True,target='client.js',external=None):
        value=dict(name='fixture-client',version='1.0.0',type='module',exports={'.':'./host.js','./client':'./'+target})
        if declaration:value['dsh']=dict(client=dict(platform='web',**(dict(external=external) if external else {})))
        (directory/'package.json').write_text(json.dumps(value),encoding='utf-8')
    write()
    try:
        import dsh
        with patch.object(dsh,'__version__','0.2.2-rc.3'):registry=CurrentClientModuleRegistry(ctx)
        notifications=[];registry.on_graph_changed(lambda:notifications.append(True))
        def row(stage):rows.append(dict(stage=stage,graph=registry.graph(),notifications=len(notifications)))
        def refresh():registry.dirty['fixture-client']=None;registry.reconcile(activation=True)
        row('initial');refresh();row('unchanged')
        write(target='next.js');refresh();row('export-replaced')
        write(target='next.js',external=['fixture-dependency']);refresh();row('metadata-replaced')
        entry.disabled=True;refresh();row('disabled');entry.disabled=False;refresh();row('enabled')
        write(False);refresh();row('declaration-removed');write();refresh();row('declaration-added')
        before=registry.graph();rev=registry.rebuilt('fixture-client');rows.append(dict(stage='unchanged-rebuilt',rev=rev,graphSame=registry.graph() is before,notifications=len(notifications)))
        entries.clear();refresh();row('removed')
        return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_client_registry.mts',prepare=prepare,
        scope='Actual current Source/Native registry initial graph and stable stat revisions, unchanged restart/no publication, client export/metadata changes, disabled/removed source, negative declaration refresh and unchanged rebuilt. Shared immutable fixture bundles give both sides the exact same actual OS stat identity.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/host/client_modules/current.py'])
