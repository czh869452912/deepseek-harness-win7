import copy


LIFECYCLE_DAMAGES = ('default', 'label', 'schema-alias', 'schema-extra', 'schema-reference', 'schema-reallocated', 'refusal',
    'view-extra', 'command-result', 'command-knobs', 'approval-global', 'narration', 'message-id',
    'live-default', 'future-default', 'detach', 'unload', 'tail', 'order', 'raw-missing', 'raw-carrier',
    'root', 'python', 'executable', 'module-missing', 'module-bytes')
DOMAIN_DAMAGES = ('domain-tail', 'domain-order', 'domain-clock', 'domain-raw-clock', 'domain-seed',
    'domain-noop', 'domain-global', 'domain-empty', 'domain-numeric', 'domain-error', 'domain-raw-tail')
GROUP_DAMAGES = ('group-missing', 'child-root', 'child-python', 'child-executable', 'child-module',
    'aggregate-extra', 'child-extra', 'relative-root', 'unowned-executable', 'module-alias', 'module-extra', 'child-module-extra')
VALUE_DAMAGES = LIFECYCLE_DAMAGES + DOMAIN_DAMAGES + GROUP_DAMAGES
SOURCE_DAMAGES = ('pin', 'node', 'inputs', 'bytes', 'input-shape', 'child-pin', 'child-node', 'source-tail',
    'source-extra', 'child-extra', 'input-alias', 'input-upper-sha')


def damage_lifecycle(original, damage, foreign_root):
    altered = copy.deepcopy(original)
    indexed = {row['name']: row for row in altered['rows']}
    graph = indexed['settings-labels']['value'][0]['schema']
    if damage == 'default':
        graph['refs'][str(graph['uid'])]['meta']['default'] = dict(defaultPreset='foreign')
    elif damage == 'label':
        next(node for node in graph['refs'].values() if node['type'] == 'const')['meta']['description'] = 'foreign'
    elif damage == 'schema-alias':
        choices = next(node for node in graph['refs'].values() if node['type'] == 'union')['list']
        choices[-1] = choices[0]
    elif damage == 'schema-extra':
        graph['refs']['99999999'] = dict(type='const', value='foreign', meta={})
    elif damage == 'schema-reference':
        graph['uid'] = True
    elif damage == 'schema-reallocated':
        current = indexed['live-default']['descriptors'][0]['schema']
        identifiers = {int(key): int(key) + 1000000 for key in current['refs']}
        changed = {}
        for key, node in current['refs'].items():
            if node['type'] == 'object':
                node['dict'] = {name: identifiers[value] for name, value in node['dict'].items()}
            elif node['type'] == 'union':
                node['list'] = [identifiers[value] for value in node['list']]
            changed[str(identifiers[int(key)])] = node
        current['uid'], current['refs'] = identifiers[current['uid']], changed
    elif damage == 'refusal':
        indexed['state-2'] = dict(name='state-2', value={})
        altered['rows'] = [indexed[row['name']] for row in altered['rows']]
    elif damage == 'view-extra':
        indexed['view-1']['value']['foreign'] = True
    elif damage == 'command-result':
        indexed['command-2']['value']['text'] += ' foreign'
    elif damage == 'command-knobs':
        indexed['command-2']['knobs'].reverse()
    elif damage == 'approval-global':
        indexed['command-2']['approvalConfig']['policy'] = 'never'
    elif damage == 'narration':
        indexed['command-2']['injected'][0]['content'][0]['text'] += ' foreign'
    elif damage == 'message-id':
        indexed['command-2']['injected'][0]['id'] = 'invalid'
    elif damage == 'live-default':
        indexed['live-default']['value'] = 'workspace-write'
    elif damage == 'future-default':
        indexed['future-default']['value']['values']['permissions']['currentValue'] = 'workspace-write'
    elif damage == 'detach':
        indexed['settings-detach']['value'] = 'danger-full-access'
    elif damage == 'unload':
        indexed['permission-unload']['value']['values']['permissions'] = {}
    elif damage == 'tail':
        altered['rows'].pop()
    elif damage == 'order':
        altered['rows'].reverse()
    elif damage == 'raw-missing':
        altered['rawErrors'].pop()
    elif damage == 'raw-carrier':
        altered['rawErrors'][0]['error']['name'] = 'Error'
    elif damage == 'root':
        altered['root'] = str(foreign_root)
    elif damage == 'python':
        altered['python'] = '3.9.0 foreign'
    elif damage == 'executable':
        altered['executable'] = str(foreign_root / 'python.exe')
    elif damage == 'module-missing':
        del altered['modules']['dsh/interaction/permission_presets.py']
    elif damage == 'module-bytes':
        altered['modules']['dsh/interaction/permission_presets.py'] = '0' * 64
    else:
        raise ValueError('Unknown permission lifecycle damage')
    return altered


def damage_runtime(original, damage, foreign_root):
    altered = copy.deepcopy(original)
    if damage in LIFECYCLE_DAMAGES:
        if damage in ('root', 'python', 'executable', 'module-missing', 'module-bytes'):
            base = dict(altered, **altered['groups']['lifecycle'])
            base.update({key: altered[key] for key in ('root', 'python', 'executable', 'modules')})
            changed = damage_lifecycle(base, damage, foreign_root)
            for key in ('root', 'python', 'executable', 'modules'):
                altered[key] = changed[key]
        else:
            altered['groups']['lifecycle'] = damage_lifecycle(altered['groups']['lifecycle'], damage, foreign_root)
    elif damage in DOMAIN_DAMAGES:
        group = altered['groups']['domain']
        indexed = {row['name']: row for row in group['rows']}
        if damage == 'domain-tail':
            group['rows'].pop()
        elif damage == 'domain-order':
            group['rows'].reverse()
        elif damage == 'domain-clock':
            group['observedClock'] += 1
        elif damage == 'domain-raw-clock':
            indexed['fresh']['rawEvents'][0]['time'] += 1
        elif damage == 'domain-seed':
            indexed['seed-empty']['result']['current'] = 'foreign'
        elif damage == 'domain-noop':
            indexed['set-noop']['result']['events'].append(dict(type='permission/preset', data=dict(preset='workspace-write')))
        elif damage == 'domain-global':
            indexed['set-danger']['result']['approvalConfig']['policy'] = 'never'
        elif damage == 'domain-empty':
            indexed['empty-key']['result']['defaultPreset'] = 'alias'
        elif damage == 'domain-numeric':
            indexed['numeric-first']['result']['names'].reverse()
        elif damage == 'domain-error':
            indexed['unknown-default']['error']['message'] += ' foreign'
        else:
            indexed['fresh']['rawEvents'].pop()
    elif damage == 'group-missing':
        del altered['groups']['domain']
    elif damage == 'child-root':
        altered['groups']['domain']['root'] = str(foreign_root)
    elif damage == 'child-python':
        altered['groups']['domain']['python'] = '3.9.0 foreign'
    elif damage == 'child-executable':
        altered['groups']['domain']['executable'] = str(foreign_root / 'python.exe')
    elif damage == 'child-module':
        del altered['groups']['domain']['modules']['dsh/interaction/permission_presets.py']
    elif damage == 'aggregate-extra':
        altered['foreign'] = True
    elif damage == 'child-extra':
        altered['groups']['domain']['foreign'] = True
    elif damage == 'relative-root':
        altered['root'] = '.'
    elif damage == 'unowned-executable':
        altered['executable'] = str(foreign_root / 'python.exe')
        for child in altered['groups'].values():
            child['executable'] = altered['executable']
    elif damage == 'module-alias':
        altered['modules']['dsh/interaction/./permission_presets.py'] = altered['modules']['dsh/interaction/permission_presets.py']
    elif damage == 'module-extra':
        altered['modules']['dsh/foreign.py'] = '0' * 64
    elif damage == 'child-module-extra':
        altered['groups']['domain']['modules']['dsh/foreign.py'] = '0' * 64
    else:
        raise ValueError('Unknown Permission aggregate damage')
    return altered


def damage_source(original, damage):
    altered = copy.deepcopy(original)
    provider = 'reference/packages/interaction/permission-presets/src/index.ts'
    if damage == 'pin':
        altered['sourceCommit'] = '0' * 40
    elif damage == 'node':
        altered['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del altered['inputs'][provider]
    elif damage == 'bytes':
        altered['inputs'][provider] = '0' * 64
    elif damage == 'input-shape':
        altered['inputs'][provider] = True
    elif damage == 'child-pin':
        altered['groups']['domain']['sourceCommit'] = '0' * 40
    elif damage == 'child-node':
        altered['groups']['domain']['node'] = 'v22.20.0'
    elif damage == 'source-tail':
        altered['groups']['lifecycle']['rows'].pop()
    elif damage == 'source-extra':
        altered['foreign'] = True
    elif damage == 'child-extra':
        altered['groups']['domain']['foreign'] = True
    elif damage == 'input-alias':
        altered['inputs']['reference/./packages/interaction/permission-presets/src/index.ts'] = altered['inputs'][provider]
    elif damage == 'input-upper-sha':
        altered['inputs'][provider] = 'A' * 64
    else:
        raise ValueError('Unknown Permission Source damage')
    return altered
