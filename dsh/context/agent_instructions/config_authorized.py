"""Current instruction discovery controls and independent shared-agent home."""
import os

from dsh.cordis.environment import default_dsh_home, expand_home_path
from dsh.cordis.json_text import stringify_json

AGENTS_HOME_ENV = 'DSH_AGENTS_HOME'
DEFAULT_AGENTS_HOME_DISPLAY = '~/.agents'
JS_WHITESPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def default_agents_home():
    return os.path.join(os.path.expanduser('~'), '.agents')


def _resolve_root(configured, env, variable, default):
    environment = os.environ if env is None else env
    value = environment.get(variable)
    selected = configured if configured is not None else value if value is not None and value.strip(JS_WHITESPACE) else default()
    return os.path.abspath(expand_home_path(selected))


def resolve_agents_home(configured=None, env=None):
    return _resolve_root(configured, env, AGENTS_HOME_ENV, default_agents_home)


def resolve_dsh_home(configured=None, env=None):
    return _resolve_root(configured, env, 'DSH_HOME', default_dsh_home)


def dsh_home_display(resolved):
    return '~/.dsh' if resolved == os.path.abspath(default_dsh_home()) else '$DSH_HOME'


def agents_home_display(resolved):
    return DEFAULT_AGENTS_HOME_DISPLAY if resolved == os.path.abspath(default_agents_home()) else '$' + AGENTS_HOME_ENV


def candidates(value, defaults):
    values = defaults if value is None else value
    return [item for item in values if item not in ('', '.', '..') and '/' not in item and '\\' not in item]


def resolve_discovery_config(config=None):
    config = config or {}
    return dict(dshHome=resolve_dsh_home(config.get('dshHome')), agentsHome=resolve_agents_home(config.get('agentsHome')),
                projectRootMarkers=list(config['projectRootMarkers'] if config.get('projectRootMarkers') is not None else ['.git']),
                instructionFileCandidates=candidates(config.get('instructionFileCandidates'), ['AGENTS.md', 'CLAUDE.md']),
                localInstructionFileCandidates=candidates(config.get('localInstructionFileCandidates'), ['AGENTS.local.md', 'CLAUDE.local.md']))


def resolve_config(config):
    # Plugin rows cannot redirect the process homes through undeclared fields.
    resolved = resolve_discovery_config({key:config[key] for key in
        ('projectRootMarkers', 'instructionFileCandidates', 'localInstructionFileCandidates') if key in config})
    resolved.update(maxBytes=config['maxBytes'], maxSourceBytes=config.get('maxSourceBytes') if config.get('maxSourceBytes') is not None else 1048576)
    return resolved


def workspace_baseline_identity(config, cwd, project_root):
    try:relative = os.path.relpath(project_root, cwd)
    except ValueError:relative = project_root
    values = dict(projectRoot='' if relative == '.' else relative)
    for key in ('projectRootMarkers', 'maxBytes', 'maxSourceBytes', 'instructionFileCandidates', 'localInstructionFileCandidates'):
        values[key] = config[key]
    return stringify_json(values)
