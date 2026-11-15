"""Actual host/provider instruction discovery, bounded reads and scope probes."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.fs.fs_local import FsLocalPlugin
    from dsh.context.agent_instructions import files_authorized as files, config_authorized as config
    base=(workspace or WORKSPACE)/'native-work';home=base/'home';agents=base/'agents';project=base/'project';child=project/'child';collision=project/'agents-global'
    for directory in (home,agents,child,collision):directory.mkdir(parents=True,exist_ok=True)
    for path,text in [(home/'AGENTS.md','global\r\n'),(agents/'AGENTS.md','\ufeff global\r\n '),(project/'.git','marker'),
            (project/'AGENTS.md','project'),(project/'CLAUDE.md',' project '),(project/'AGENTS.local.md','overlay'),
            (child/'AGENTS.md','nested'),(collision/'AGENTS.md','collision')]:path.write_bytes(text.encode('utf-8'))
    options=dict(cwd=str(child),dshHome=str(home),agentsHome=str(agents),maxBytes=2000,maxSourceBytes=128)
    rows=[];ctx=Context()
    try:
        rows.append(dict(name='host-discovery',value=await files.discover_baseline_instruction_files(options)))
        rows.append(dict(name='host-load',value=await files.load_baseline_instruction_set(options)))
        await ctx.plugin(FsLocalPlugin,dict(cwd=str(base)));filesystem=ctx.get('fs')
        rows.append(dict(name='provider-load',value=await files.load_baseline_instruction_set(options,filesystem)))
        bom=base/'bom.txt';bom.write_bytes(b'\xef\xbb\xbf\xef\xbb\xbfvalue')
        target=await filesystem.resolve(str(bom));text=await filesystem.readText(target);chunks=[chunk async for chunk in await filesystem.streamText(target)]
        edited=await filesystem.editText(target,dict(oldString='value',newString='changed'))
        rows.append(dict(name='provider-bom',text=text,stream=''.join(chunks),before=edited.before,after=edited.after,bytes=list(bom.read_bytes())))
        resolved=config.resolve_discovery_config(options)
        for name,scope in [('harness','user-global\0AGENTS.md'),('shared','agents-global\0AGENTS.md'),('project','.\0AGENTS.md'),('collision','.\\agents-global\0AGENTS.md'),('missing','child\0CLAUDE.md')]:
            result=await files.probe_scope_instruction(scope,str(project),resolved,filesystem)
            value=dict(kind=result['kind'])
            if result['kind']=='present':
                file=result['file'];value.update(file={key:file[key] for key in ('absolutePath','displayPath','size') if key in file},read=await files.read_scope_instruction(file,128,filesystem))
            rows.append(dict(name='scope-'+name,value=value))
        rows.append(dict(name='collision-discovery',value=await files.discover_baseline_instruction_files(dict(options,cwd=str(collision)))))
        (child/'AGENTS.md').write_text('x'*129,encoding='utf-8')
        rows.append(dict(name='oversized-source',value=await files.load_baseline_instruction_set(options,filesystem)))
        (home/'not-directory').write_text('file',encoding='utf-8')
        rows.append(dict(name='host-enotdir',value=await files.load_baseline_instruction_set(dict(options,dshHome=str(home/'not-directory'/'child')))))
        rows.append(dict(name='disabled',value=await files.load_baseline_instruction_set(dict(options,maxBytes=0),filesystem)))
        empty=base/'empty';empty.mkdir()
        rows.append(dict(name='empty',value=await files.load_baseline_instruction_set(dict(options,dshHome=str(empty),agentsHome=str(empty),instructionFileCandidates=[],localInstructionFileCandidates=[]))))
        rows.append(dict(name='empty-replacement',value=await files.load_baseline_instruction_set(dict(options,dshHome=str(empty),agentsHome=str(empty),instructionFileCandidates=[],localInstructionFileCandidates=[],replacePreviousBaseline=True))))
        def normalize(value):
            if isinstance(value,str) and str(base) in value:return value.replace(str(base),'<work>')
            if isinstance(value,dict):return {key:'<opaque-version>' if key=='version' else normalize(item) for key,item in value.items()}
            if isinstance(value,list):return [normalize(item) for item in value]
            return value
        return normalize(rows)
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_instruction_files.mts','Actual host files and local ctx.fs: dual-home precedence and BOM/whitespace duplicate suppression, root/overlay/nested candidates, collision paths, host/provider baseline reads, per-scope metadata/read, missing and ENOTDIR, oversized sources, disabled loading and explicit empty replacement. Roots projected to <work>; opaque provider freshness tokens projected by field name, not compared across different physical files. No runtime projection acceptance.',
        [Path(__file__).resolve()]+[ROOT/path for path in ('dsh/context/agent_instructions/files_authorized.py','dsh/context/agent_instructions/config_authorized.py','dsh/context/agent_instructions/scope_authorized.py','dsh/context/agent_instructions/render_authorized.py','dsh/fs/fs_local.py')],prepare=prepare)
