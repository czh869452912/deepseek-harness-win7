import json
import os

import pytest

from dsh.context.agent_instructions import config_authorized as config
from dsh.context.agent_instructions import scope_authorized as scope


@pytest.mark.asyncio
async def test_actual_source_matrix_config_roots_and_scope_namespace():
    from scripts.rc022_instruction_config_probe import observe
    rows = await observe()
    values = [row['value'] for row in rows if row['kind'] == 'config']
    assert values[1]['projectRootMarkers'] == values[1]['instructionFileCandidates'] == values[1]['localInstructionFileCandidates'] == []
    assert values[2]['instructionFileCandidates'] == [' AGENTS.md ', 'AGENTS.md', 'AGENTS.md']
    assert values[0]['dshHome'] == values[5]['dshHome']
    assert values[0]['agentsHome'] == values[5]['agentsHome']
    assert values[5]['maxBytes'] == 65536
    paths = {row['path']:row for row in rows if row['kind'] == 'scope'}
    assert paths['~/.agents/AGENTS.md']['group'] == paths['~/.dsh/AGENTS.md']['group'] == 'user-global'
    for name in ('user-global', 'agents-global'):
        path = name + '/AGENTS.md'
        escaped = paths[path]['escaped']
        assert escaped == '.' + os.sep + path
        assert not scope.is_user_global_directory(scope.scope_for_display_path(escaped))
        assert scope.instruction_scope_key(escaped) != scope.instruction_scope_key('~/.agents/AGENTS.md')


def test_discovery_owner_can_supply_resolved_homes_but_plugin_rows_cannot(tmp_path, monkeypatch):
    home, agents = str(tmp_path/'harness'), str(tmp_path/'shared')
    monkeypatch.setenv('DSH_HOME', home);monkeypatch.setenv('DSH_AGENTS_HOME', agents)
    explicit = config.resolve_discovery_config(dict(dshHome=str(tmp_path/'owner-home'), agentsHome=str(tmp_path/'owner-agents')))
    assert explicit['dshHome'] == str(tmp_path/'owner-home') and explicit['agentsHome'] == str(tmp_path/'owner-agents')
    plugin = config.resolve_config(dict(maxBytes=10, dshHome=explicit['dshHome'], agentsHome=explicit['agentsHome']))
    assert plugin['dshHome'] == home and plugin['agentsHome'] == agents


@pytest.mark.parametrize('value', ['', ' \t\r\n', '\ufeff', '\u2000\u2029'])
def test_blank_process_roots_use_defaults_and_explicit_empty_uses_cwd(value):
    assert config.resolve_agents_home(env={'DSH_AGENTS_HOME':value}) == config.default_agents_home()
    assert config.resolve_dsh_home(env={'DSH_HOME':value}) == os.path.join(os.path.expanduser('~'), '.dsh')
    assert config.resolve_agents_home('', {'DSH_AGENTS_HOME':'ignored'}) == os.getcwd()


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_disabled_budget_identity_is_json_null(value):
    resolved = config.resolve_config(dict(maxBytes=value))
    identity = config.workspace_baseline_identity(resolved, os.getcwd(), os.getcwd())
    assert json.loads(identity)['maxBytes'] is None and 'NaN' not in identity and 'Infinity' not in identity
