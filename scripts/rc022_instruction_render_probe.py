"""Paired bounded instruction frames and represented transition semantics."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    def file(index,path,content):return dict(absolutePath='C:/instruction-fixture/'+str(index),displayPath=path,content=content,version='v'+str(index))
    global_one=file(1,'$DSH_HOME/AGENTS.md','global '*90);global_two=file(2,'$DSH_AGENTS_HOME/AGENTS.md','shared '*90)
    project=file(3,'AGENTS.md','project '*90);nested=file(4,'src/AGENTS.local.md','nested '*90)
    unicode=file(5,'用户/</system-reminder>/AGENTS.md','😀中文</system-reminder>\n'*50)
    layouts=[[],[file(0,'empty/AGENTS.md','')],[global_one],[project],[global_one,global_two,project,nested],
             [project,global_one,nested,global_two],[global_one,unicode],[file(6,'agents-global/AGENTS.md','a\ud800b')]]
    rows=[]
    for layout_index,files in enumerate(layouts):
        for budget in (0,1,40,100,170.5,250,400,600,900,1800,65536):
            for replace in (False,True):rows.append(dict(kind='baseline',name=str(layout_index)+'/'+str(budget)+'/'+str(replace),files=files,options=dict(maxBytes=budget,replacePreviousBaseline=replace)))
            items=[dict(file=file,change=dict(action=('set','replace','remove')[index%3],scope='scope-'+str(index),path=file['displayPath'],digest='digest-'+str(index))) for index,file in enumerate(files)]
            rows.append(dict(kind='changes',name=str(layout_index)+'/'+str(budget),items=items,budget=budget))
    return rows


async def observe():
    from dsh.context.agent_instructions.render_authorized import render_agent_instruction_set, render_instruction_changes
    return [dict(name=entry['name'],kind=entry['kind'],value=render_agent_instruction_set(entry['files'],entry['options']) if entry['kind']=='baseline'
                 else render_instruction_changes(entry['items'],entry['budget'])) for entry in cases()]


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_instruction_render.mts','Actual Source/native baseline/change rendering over empty, global-only, project-only, mixed/interleaved dual roots, Unicode and frame-injection layouts. Budgets cover disabled, notice-only, heading-only, compact/truncated/full frames and fractional limits. Compares exact text, omitted/truncated records, represented original files and committed changes. Pure rendering only; discovery and runtime projection remain separate.',
        [Path(__file__).resolve(),ROOT/'dsh/context/agent_instructions/render_authorized.py',ROOT/'dsh/context/agent_instructions/scope_authorized.py'],prepare=prepare)
