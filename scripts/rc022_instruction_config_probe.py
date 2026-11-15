"""Paired instruction config, home roots and collision-safe logical scopes."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.context.agent_instructions import config_authorized as config, scope_authorized as scope
    cases=json.loads((ROOT/'scripts/oracles/rc022_instruction_config_cases.json').read_text(encoding='utf-8'));rows=[]
    for entry in cases['configs']:
        value=config.resolve_config(entry)
        rows.append(dict(kind='config',value=value,identity=config.workspace_baseline_identity(value,'C:/work/child','C:/work')))
    for entry in cases['roots']:
        home=config.resolve_dsh_home(entry.get('configured'),entry.get('env',{}));agents=config.resolve_agents_home(entry.get('configured'),entry.get('env',{}))
        rows.append(dict(kind='roots',home=home,agents=agents,homeDisplay=config.dsh_home_display(home),agentsDisplay=config.agents_home_display(agents)))
    for path in cases['paths']:
        directory=scope.scope_for_display_path(path);key=scope.instruction_scope_key(path)
        rows.append(dict(kind='scope',path=path,directory=directory,key=key,decoded=scope.decode_scope_key(key),group=scope.instruction_candidate_group(directory),globalDirectory=scope.is_user_global_directory(directory),escaped=scope.escape_project_display_path(path)))
    rows.append(dict(kind='decode-old',value=scope.decode_scope_key('old-scope')))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_instruction_config.mts','Pure actual Source/native instruction configuration, independent home resolution/display, empty candidate controls, plugin-row home isolation, serialized baseline identity and project/global scope collisions. Discovery, content rendering and runtime reconciliation are separate work.',
        [Path(__file__).resolve(),ROOT/'scripts/oracles/rc022_instruction_config_cases.json',ROOT/'dsh/context/agent_instructions/config_authorized.py',ROOT/'dsh/context/agent_instructions/scope_authorized.py'])
