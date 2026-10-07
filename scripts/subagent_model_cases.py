import copy


VALUE_DAMAGES = ('missing-row', 'row-order', 'schema-missing', 'schema-description',
    'route-description', 'inheritance-guidance', 'policy-mode', 'clock', 'discovery-value',
    'discovery-content', 'discovery-error', 'module-bytes', 'missing-module', 'fixture',
    'foreign-root', 'foreign-executable', 'wrong-python')
SOURCE_DAMAGES = ('pin', 'node', 'fixture', 'missing-input', 'changed-input', 'unsafe-input',
    'missing-row', 'row-order', 'duplicate-row')


def damage_runtime(report, damage):
    changed = copy.deepcopy(report)
    rows = {row['name']:row for row in changed['rows']}
    selected = rows['true/false/false/one-shot/schema']
    if damage == 'missing-row':
        changed['rows'].pop()
    elif damage == 'row-order':
        changed['rows'].reverse()
    elif damage == 'schema-missing':
        selected['schemas'].pop()
    elif damage == 'schema-description':
        selected['schemas'][0]['description'] = 'other'
    elif damage == 'route-description':
        selected['schemas'][1]['parameters']['properties']['provider']['description'] = 'other'
    elif damage == 'inheritance-guidance':
        rows['true/true/false/one-shot/schema']['schemas'][1]['description'] = 'other'
    elif damage == 'policy-mode':
        selected['events'][0]['data']['allowedModels'][0]['model'] = 'other'
    elif damage == 'clock':
        selected['events'][0]['time'] += 1
    elif damage == 'discovery-value':
        rows['true/false/false/one-shot/call/0']['result']['value'] = 'other'
    elif damage == 'discovery-content':
        rows['true/false/false/one-shot/call/2']['result']['content'][0]['text'] = 'other'
    elif damage == 'discovery-error':
        rows['true/false/false/one-shot/call/5']['result']['error']['message'] = 'other'
    elif damage == 'module-bytes':
        changed['imports']['dsh/subagent/canonical_tools.py'] = '0' * 64
    elif damage == 'missing-module':
        changed['imports'].pop('dsh/subagent/canonical_tools.py')
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'foreign-root':
        changed['root'] += '-foreign'
    elif damage == 'foreign-executable':
        changed['executable'] += '-foreign'
    elif damage == 'wrong-python':
        changed['python'] = '3.9.0 foreign'
    else:
        raise ValueError('Unknown subagent model damage: ' + damage)
    return changed


def damage_source(report, damage):
    changed = copy.deepcopy(report)
    path = 'reference/packages/subagent/tool-subagent/src/index.ts'
    if damage == 'pin':
        changed['sourceCommit'] = '0' * 40
    elif damage == 'node':
        changed['node'] = 'v20.0.0'
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'missing-input':
        changed['inputs'].pop(path)
    elif damage == 'changed-input':
        changed['inputs'][path] = '0' * 64
    elif damage == 'unsafe-input':
        changed['inputs']['reference/../foreign.py'] = '0' * 64
    elif damage == 'missing-row':
        changed['rows'].pop()
    elif damage == 'row-order':
        changed['rows'].reverse()
    elif damage == 'duplicate-row':
        changed['rows'].append(copy.deepcopy(changed['rows'][-1]))
    else:
        raise ValueError('Unknown subagent model Source damage: ' + damage)
    return changed
