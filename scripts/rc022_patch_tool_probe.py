"""Model values and replayed patch presentations from actual paired disk reports."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe,rc022_patch_execution_probe as engine


def project(row):
    from dsh.fs.apply_patch_tool import patch_tool_value,render_patch,patch_presentation_meta,present_patch_result
    try:
        value=patch_tool_value(row['report']);meta=patch_presentation_meta(value)
        return dict(name=row['name'],value=value,render=render_patch(value),meta=meta,presentation=present_patch_result(dict(isError=False,meta=meta)))
    except Exception as error:return dict(name=row['name'],error=dict(name=getattr(error,'name',type(error).__name__),code=getattr(error,'code',None),message=getattr(error,'message',str(error))))


async def observe():
    from dsh.fs.apply_patch_tool import present_patch_call,present_patch_result
    rows=[project(row) for row in await engine.observe() if 'thrown' not in row['report']]
    rows += [dict(name='preview-'+case['name'],value=present_patch_call(case['patch'])) for case in engine.corpus()]
    for meta in [None,{},dict(diffs=[]),dict(diffs=[dict(path='a',oldText=None,newText='new')]),dict(diffs=[dict(path='a',oldText='old',newText='new')],stopped=True),dict(diffs=[dict(path='a',oldText='old',newText='new')],stopped=1),dict(diffs=[dict(path='a',newText='new')]),dict(diffs=[dict(path='a',oldText=1,newText='new')])]:
        rows.append(dict(name='replay',meta=meta,value=present_patch_result(dict(isError=False,meta=meta)),error=present_patch_result(dict(isError=True,meta=meta))))
    with (ROOT/'dsh/fs/patch_tool_current.json').open(encoding='utf-8') as source:rows.append(dict(name='definitions',value=json.load(source)))
    return rows


def prepare(output):return engine.prepare(output)


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_patch_tool.mts','Model value/error routing, lossless partial effects, exact compact rendering, bounded diff metadata, pure call preview and replay fallbacks over 27 real paired execution scenarios; actual Source defineTool schema extraction.',[Path(__file__).resolve(),ROOT/'dsh/fs/apply_patch_tool.py',ROOT/'dsh/fs/patch_tool_current.json',ROOT/'scripts/rc022_patch_execution_probe.py',ROOT/'scripts/oracles/rc022_patch_execution.mts'],prepare=prepare)
