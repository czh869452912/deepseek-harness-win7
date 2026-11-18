"""Pair metadata and independent profile permission decisions with fixed Source."""
import asyncio
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
RUNTIME = '0.2.2-rc.3'


def cases():
    versions = ['0.0.0-0', '0.0.0', '0.0.1-alpha.1', '0.0.1', '0.1.0-0', '0.1.0', '0.1.7-alpha.1',
        '0.1.7', '0.1.9', '0.2.0-0', '0.2.0', RUNTIME, '0.2.2', '0.3.0-alpha', '0.3.0',
        '1.0.0-alpha', '1.0.0', '1.2.0-alpha', '1.2.3-0', '1.2.3-alpha.2', '1.2.3-alpha.10',
        '1.2.3-beta', '1.2.3', '1.2.3+build.1', '1.2.4-0', '1.3.0-alpha', '1.3.0', '2.0.0-0',
        '2.0.0', '10.1.2', 'v1.2.3', ' 1.2.3 ', '01.2.3', '1.2.3-01', '9007199254740992.0.0']
    ranges = ['', ' ', '*', 'x', 'X', '>=0.0.0', '>=0.0.0-0', '<*', '>*', '<=x', '>=X',
        '^0.1.0 || ^1.2.0', '||', '1 ||', '* || broken', 'broken', 'workspace:^', 'file:../a',
        'npm:dsh@*', '1.2.3, 2', '1.2.3 || broken', '= 1.2.3', '>= 1.2.3 < 2',
        '1.2 - 1.3', '1.2.3 - 1.2.3', '0 - 1', '* - 1.2', '1.2.3-alpha.1 - 1.2.3-beta',
        'x.1', '1.x.1', '01.2', '1.2.3-01', '1.2.3.4', 'v=1.2.3', '~>', '^', '>', '1.2-beta']
    for base in ['0', '0.0', '0.0.1', '0.1', '0.1.7-alpha.1', '0.2.2-rc.3',
                 '1', '1.2', '1.2.3', '1.2.3-beta', '1.2.3+build', '1.2.x', '2.x', '*']:
        for prefix in ['', '=', '>', '>=', '<', '<=', '~', '~>', '^']:
            ranges.append(prefix+base)
    result = [dict(kind='range', version=v, requirement=r) for v in versions for r in ranges]
    for version in versions + ['=1.2.3', '1.2.3+01', '1.2.3-alpha+build', '', None, 1]:
        result.append(dict(kind='exact', value=version))
    identity = dict(name='@example/plugin', version='2.0.0')
    for fields in [{}, {'engines': {}}, {'engines': {'node': '>=99'}},
                   {'engines': {'dsh': '*'}, 'peerDependencies': None}]:
        result.append(dict(kind='manifest', value=fields))
    for field in ('engines', 'peerDependencies'):
        for value in (None, [], 'bad', 1, False):
            result.append(dict(kind='manifest', value=dict(identity, **{field: value})))
    for requirement in ['', ' ', '*', '^0.2', '^0.3', 'workspace:^', 'workspace:~', 'workspace:*',
                        'workspace:>=0.3', 'broken', None, 1, [], {}]:
        for field in ('engines', 'peerDependencies'):
            key = 'dsh' if field == 'engines' else '@deepseek-ai/dsh'
            for exempt in (False, True):
                result.append(dict(kind='manifest', value=dict(identity, **{field: {key: requirement}}), exempt=exempt))
    for identity_value in ({}, {'name': ' '}, {'name': '@example/plugin'}, {'name': '@example/plugin', 'version': ''}):
        result.append(dict(kind='manifest', value=dict(identity_value, engines={'dsh': '^99'})))
    for value in [[], None, 'text', 1, {}, {'good@1.2.3': [RUNTIME]},
                  {'@scope/plugin@1.2.3+build': [RUNTIME, '1.0.0-alpha+runtime']},
                  {'good@1.2.3': [RUNTIME], 'bad@^1.0.0': [RUNTIME], 'also-good@2.0.0': []},
                  {'plugin@1.2.3': '1.2.3'}, {'plugin@1.2.3': [1]}, {'plugin@1.2.3': ['v1.2.3']}]:
        result.append(dict(kind='permissions', value=value))
    return result


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'; path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


async def native():
    from dsh.boot import plugin_compatibility as plugin, profile_compatibility as profile
    from dsh.boot.semver import satisfies, is_exact_version
    results = []
    for i, case in enumerate(cases()):
        kind = case['kind']
        if kind == 'range':
            results.append(satisfies(case['version'], case['requirement']))
        elif kind == 'exact':
            results.append(is_exact_version(case['value']))
        elif kind == 'manifest':
            try:
                issue = plugin.evaluate_plugin_compatibility(case['value'], {'@example/plugin@2.0.0': [RUNTIME]} if case.get('exempt') else {}, RUNTIME)
                results.append(dict(issue=issue, warning=None if issue is None else plugin.plugin_compatibility_warning(issue)))
            except ValueError as error:
                results.append(dict(error=str(error)))
        else:
            directory = OUTPUT/'files'/'native'/str(i); directory.mkdir(parents=True)
            (directory/'compatibility.json').write_text(json.dumps(case['value']), encoding='utf-8')
            read = profile.read_profile_compatibility(str(directory))
            read['warnings'] = [s.replace(str(directory), '$PROFILE') for s in read['warnings']]
            results.append(read)
    current = profile.get_dsh_runtime_version
    profile.get_dsh_runtime_version = lambda: RUNTIME
    try:
        directory = OUTPUT/'files'/'native'/'writes'; directory.mkdir(parents=True)
        observations = []
        for name, version, enabled, accept in [('plugin@1.0.0', RUNTIME, True, False),
            ('plugin@1.0.0', '9.9.9', True, True), ('plugin@1.0.0', RUNTIME, True, True),
            ('other@2.0.0', RUNTIME, True, True), ('plugin@1.0.0', RUNTIME, True, True),
            ('plugin@1.0.0', '0.0.1', False, False), ('plugin@1.0.0', RUNTIME, False, False)]:
            try:
                await profile.set_profile_version_exemption(str(directory), name, version, enabled, accept)
                error = None
            except ValueError as failure:
                error = str(failure)
            observations.append(dict(error=error, read=profile.read_profile_compatibility(str(directory))))
        results.append(observations)
    finally:
        profile.get_dsh_runtime_version = current
    return results


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'reference'
    probe.main('rc022_compatibility.mts', 'Npm prerelease ranges, metadata precedence and independent exact-version permission read/grant/revoke.',
        [Path(__file__).resolve(), *[ROOT/'dsh/boot'/name for name in ('semver.py', 'plugin_compatibility.py', 'profile_compatibility.py')],
         *[source/'packages/boot/app-boot/src'/name for name in ('plugin-compatibility.ts', 'profile-compatibility.ts')],
         source/'node_modules/semver/classes/range.js'], prepare)
