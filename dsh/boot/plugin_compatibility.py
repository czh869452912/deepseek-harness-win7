"""Evaluate plugin metadata without importing plugin code."""
import json
from dsh.boot.semver import parse, satisfies


def _object(value, field):
    if not isinstance(value, dict):
        raise ValueError(field+' must be an object')
    return value


def _runtime(value):
    try:
        parse(value)
    except ValueError:
        raise ValueError('Invalid dsh runtime version: '+json.dumps(value, ensure_ascii=False)+'; expected a semantic version')
    return value


def get_dsh_runtime_version():
    from dsh import __version__
    return _runtime(__version__)


def evaluate_plugin_compatibility(manifest, exemptions=None, runtime_version=None):
    runtime = _runtime(get_dsh_runtime_version() if runtime_version is None else runtime_version)
    fields = _object(manifest, 'Plugin manifest')
    engines = _object(fields['engines'], 'Plugin manifest engines') if 'engines' in fields else {}
    unmet = {}
    if 'dsh' in engines:
        requirement = engines['dsh']
        if not isinstance(requirement, str):
            raise ValueError('Plugin manifest engines.dsh must be a string')
        if not satisfies(runtime, requirement):
            unmet['engines.dsh'] = requirement
    elif 'peerDependencies' in fields:
        peers = _object(fields['peerDependencies'], 'Plugin manifest peerDependencies')
        for name, requirement in peers.items():
            if not isinstance(requirement, str):
                raise ValueError('Plugin manifest peerDependencies['+json.dumps(name)+'] must be a string')
            if name != '@deepseek-ai/dsh' and not name.startswith('@deepseek-ai/dsh-'):
                continue
            effective = runtime if requirement in ('workspace:^', 'workspace:~', 'workspace:*') else requirement
            if not satisfies(runtime, effective):
                unmet[name] = requirement
    if not unmet:
        return None
    for key in ('name', 'version'):
        if not isinstance(fields.get(key), str) or not fields[key].strip():
            raise ValueError('Plugin manifest '+key+' must be a non-empty string when dsh requirements are unmet')
    key = fields['name']+'@'+fields['version']
    versions = (exemptions or {}).get(key, [])
    return dict(name=fields['name'], version=fields['version'], runtimeVersion=runtime,
        requirements=unmet, exempted=runtime in versions)


def plugin_compatibility_warning(issue):
    key = issue['name']+'@'+issue['version']
    runtime = issue['runtimeVersion']
    return ('Plugin '+key+' is incompatible with dsh '+runtime+': requirements '
        +json.dumps(issue['requirements'], ensure_ascii=False, separators=(',', ':'))+'. '
        +'Running it may cause crashes or data loss. '
        +'Update the plugin or install a plugin version compatible with this dsh runtime. '
        +'To accept this risk explicitly, grant the exact-version exemption for '+key+' on dsh '+runtime
        +' with `dsh plugin allow-version` or the plugin manager, then retry the installation or restart dsh. '
        +'Exact-version exemption: '+('active' if issue['exempted'] else 'not active')+'.')


getDshRuntimeVersion = get_dsh_runtime_version
evaluatePluginCompatibility = evaluate_plugin_compatibility
pluginCompatibilityWarning = plugin_compatibility_warning
