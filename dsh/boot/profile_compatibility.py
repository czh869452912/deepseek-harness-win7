"""Independent, exact-version compatibility grants owned by one profile."""
import json
import os
import re
import tempfile
from dsh.boot.plugin_compatibility import get_dsh_runtime_version
from dsh.boot.semver import is_exact_version
from dsh.cordis.file_lock import with_file_lock

PROFILE_COMPATIBILITY_FILENAME = 'compatibility.json'
_PACKAGE_NAME = re.compile(r'(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*')


def _package_version(value):
    if not isinstance(value, str):
        return False
    name, sep, version = value.rpartition('@')
    return bool(sep and _PACKAGE_NAME.fullmatch(name) and is_exact_version(version))


def validate_plugin_version_exemption(package_version, runtime_version):
    if not _package_version(package_version) or not is_exact_version(runtime_version):
        raise ValueError('Version exemptions require an exact npm package-name@version and an exact DSH runtime version')


def read_profile_compatibility(profile_dir):
    filename = os.path.join(profile_dir, PROFILE_COMPATIBILITY_FILENAME)
    def unreadable(reason):
        return dict(exemptions={}, warnings=[filename+' '+reason+'; treating the profile as having no exemptions'], rewritable=False)
    try:
        with open(filename, 'r', encoding='utf-8', errors='replace') as stream:
            text = stream.read()
    except FileNotFoundError:
        return dict(exemptions={}, warnings=[], rewritable=True)
    except OSError as error:
        return unreadable('cannot be read ('+str(error)+')')
    try:
        value = json.loads(text)
    except (ValueError, UnicodeError) as error:
        return unreadable('is not valid JSON ('+str(error)+')')
    if not isinstance(value, dict):
        return unreadable('must map exact package@version keys to DSH version lists')
    exemptions, warnings = {}, []
    for key, versions in value.items():
        if not _package_version(key):
            warnings.append(filename+': '+json.dumps(key, ensure_ascii=False)+' is not an exact package-name@version key; the record is ignored')
        elif not isinstance(versions, list) or not all(is_exact_version(v) for v in versions):
            warnings.append(filename+': '+key+' must contain a list of exact DSH versions; the record is ignored')
        else:
            exemptions[key] = versions
    return dict(exemptions=exemptions, warnings=warnings, rewritable=not warnings)


def read_profile_version_exemptions(profile_dir):
    return read_profile_compatibility(profile_dir)['exemptions']


async def set_profile_version_exemption(profile_dir, package_version, runtime_version, enabled, accept_risk):
    validate_plugin_version_exemption(package_version, runtime_version)
    if enabled and not accept_risk:
        raise ValueError('Incompatible plugins may cause crashes or data loss. To grant this exact-version exemption, explicitly acknowledge the risk with --accept-risk (acceptRisk: true).')
    current = get_dsh_runtime_version()
    if enabled and runtime_version != current:
        raise ValueError('Cannot approve DSH '+runtime_version+': this application runs DSH '+current+'. Use --dsh-version '+current+'.')
    os.makedirs(profile_dir, exist_ok=True)
    filename = os.path.join(profile_dir, PROFILE_COMPATIBILITY_FILENAME)
    def write():
        previous = read_profile_compatibility(profile_dir)
        if not previous['rewritable']:
            raise ValueError(PROFILE_COMPATIBILITY_FILENAME+' must be repaired before exemptions change:\n'+'\n'.join(previous['warnings']))
        exemptions = previous['exemptions']
        versions = exemptions.get(package_version, [])
        if enabled:
            exemptions[package_version] = list(dict.fromkeys(versions+[runtime_version]))
        else:
            retained = [v for v in versions if v != runtime_version]
            if retained:
                exemptions[package_version] = retained
            else:
                exemptions.pop(package_version, None)
        descriptor, temporary = tempfile.mkstemp(prefix='.compatibility-', suffix='.tmp', dir=profile_dir)
        try:
            # mkstemp creates mode 0600 on POSIX; Windows retains profile ACL inheritance.
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(exemptions, ensure_ascii=False, indent=2)+'\n')
                stream.flush(); os.fsync(stream.fileno())
            from dsh.boot.python_plugins import _replace_atomic_file
            _replace_atomic_file(temporary, filename)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    await with_file_lock(filename, write)


isExactPluginVersion = is_exact_version
validatePluginVersionExemption = validate_plugin_version_exemption
readProfileCompatibility = read_profile_compatibility
readProfileVersionExemptions = read_profile_version_exemptions
setProfileVersionExemption = set_profile_version_exemption
