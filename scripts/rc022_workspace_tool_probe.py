"""Mounted workspace dependency tool and descriptor observations."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.cordis import Context
from dsh.core.tools import CurrentToolsPlugin
from dsh.core.system_prompt.current import CurrentSystemPrompt
from dsh.host.workspace_dependencies_current import CurrentWorkspaceDependencies
from dsh.host import workspace_runtime_files_current as files
from dsh.host.workspace_runtime_manifest_current import workspaceDependencyPaths

WORKSPACE=None


def cases():
    rows=[dict(action=action) for action in ['resolve','install','retry','cached']]
    for field in ['source','root']:
        for value in [None,False,1,'',[],{},'relative','C:relative']:
            rows.append(dict(action='config',field=field,value=value))
    rows.append(dict(action='config',field='source',omit=True))
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=Path(tempfile.mkdtemp(prefix='g-')).resolve()
    (output/'pytest-workspace-mapping.json').write_text(json.dumps(dict(format='dsh-release-workspace@2',
        temporary_parent=str(WORKSPACE.parent),execution_path=str(WORKSPACE),retained_path=str(output/'files'),scope='Owned paired tool filesystem workspace')),encoding='utf-8')
    path=output/'inputs.json';path.write_text(json.dumps(dict(directory=str(WORKSPACE/'source'),cases=cases())),encoding='utf-8')
    return [path]


def payload(source):
    source.mkdir(parents=True)
    manifest=dict(desktopVersion='fixture',platform=files._platform(),arch=files._arch(),python='3.8.10',pythonPackages={'Pillow':'10.4.0'})
    paths=workspaceDependencyPaths(str(source),manifest)
    Path(paths['python']).parent.mkdir(parents=True,exist_ok=True);Path(paths['python']).write_bytes(b'interpreter')
    Path(paths['pythonPackages']).mkdir(parents=True)
    raw=json.dumps(manifest);(source/'runtime.json').write_text(raw,encoding='utf-8')
    return raw


async def observe(directory=None):
    base=Path(directory or WORKSPACE/'native');rows=[]
    for index,case in enumerate(cases()):
        directory=base/str(index);source=directory/'payload';root=directory/'installed';raw=payload(source)
        config=dict(source=str(source))
        if case['action'] in ['install','retry']:config['root']=str(root)
        if case['action']=='config':
            if case.get('omit'):config.pop(case['field'],None)
            else:config[case['field']]=case['value']
        ctx=Context();row=dict(action=case['action']);stage='schema'
        try:
            CurrentWorkspaceDependencies.Config(config);stage='mount'
            await ctx.plugin(CurrentSystemPrompt);await ctx.plugin(CurrentToolsPlugin)
            fiber=await ctx.plugin(CurrentWorkspaceDependencies,config)
            tool=ctx.tools.get('load_workspace_dependencies');stage='execute'
            row.update(description=tool.description,parameters=tool.parameters,output=tool.output['schema'],presentation=tool.present_call({}))
            if case['action']=='retry':
                (source/'runtime.json').unlink()
                try:await tool.handler({})
                except FileNotFoundError:row['firstFailed']=True
                (source/'runtime.json').write_text(raw,encoding='utf-8')
            first=await tool.handler({});second=await tool.handler({});row['sameValue']=first is second
            if case['action']=='cached':
                (source/'runtime.json').unlink();assert await tool.handler({}) is first
                row['cachedAfterRemoval']=True
            row['value']=first;row['render']=tool.output['render']({},first)
            await fiber.dispose();row['removed']=ctx.tools.get('load_workspace_dependencies') is None
            stage='done'
        except Exception as error:
            if stage not in ['schema','mount']:raise
            if stage=='mount' and not isinstance(error,TypeError) and str(error)!='workspace dependencies: source and root must be absolute paths':raise
            row['error']='schema' if stage=='schema' else 'type' if isinstance(error,TypeError) else str(error)
        finally:await ctx.fiber.dispose()
        def normalize(value):
            if isinstance(value,str):return value.replace(str(directory).replace('\\','\\\\'),'<base>').replace(str(directory),'<base>').replace('\\','/')
            if isinstance(value,list):return [normalize(item) for item in value]
            if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
            return value
        rows.append(normalize(dict(row,stage=stage)))
    return rows


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_workspace_tool.mts',scope='Actual Cordis tools registration and Source defineTool normalized schema; in-place/install/retry/cache, config rejection and disposal.',prepare=prepare,
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/host/workspace_dependencies_current.py',ROOT/'packages/skill/tool-workspace-dependencies/package.json'])
    finally:
        if WORKSPACE is not None:
            from scripts.verify_release import retain_regression_workspace
            retain_regression_workspace(WORKSPACE,Path(sys.argv[sys.argv.index('--output')+1]).resolve()/'files')
