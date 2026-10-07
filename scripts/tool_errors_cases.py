import copy


VALUE_DAMAGES = ('missing-row', 'row-order', 'typed-extra-alias', 'typed-code',
                 'abort-body-called', 'unknown-content', 'before-prompt', 'prompt-disposal',
                 'prompt-restoration',
                 'module-bytes', 'missing-module', 'fixture', 'foreign-root',
                 'foreign-executable', 'wrong-python')
SOURCE_DAMAGES = ('pin', 'node', 'fixture', 'missing-input', 'changed-input', 'unsafe-input',
                  'missing-row', 'row-order', 'duplicate-row')


def damage_runtime(report, damage):
    changed = copy.deepcopy(report)
    rows = {row['name']: row for row in changed['rows']}
    if damage == 'missing-row':
        changed['rows'].pop()
    elif damage == 'row-order':
        changed['rows'].reverse()
    elif damage == 'typed-extra-alias':
        rows['typed']['result']['error']['code'] = 'CONTROLLED_TYPED'
    elif damage == 'typed-code':
        rows['typed']['result']['error']['info']['code'] = 'OTHER'
    elif damage == 'abort-body-called':
        rows['pre-aborted']['calls'] = 1
    elif damage == 'unknown-content':
        rows['unknown']['result']['content'][0]['text'] = 'other'
    elif damage == 'before-prompt':
        changed['rows'][0]['present'] = True
    elif damage == 'prompt-disposal':
        changed['rows'][2]['present'] = True
    elif damage == 'prompt-restoration':
        rows['after-prompt-restore']['present'] = False
    elif damage == 'module-bytes':
        changed['imports']['dsh/core/tools.py'] = '0' * 64
    elif damage == 'missing-module':
        changed['imports'].pop('dsh/core/tools.py')
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'foreign-root':
        changed['root'] += '-foreign'
    elif damage == 'foreign-executable':
        changed['executable'] += '-foreign'
    elif damage == 'wrong-python':
        changed['python'] = '3.9.0 foreign'
    else:
        raise ValueError('Unknown Tools damage: ' + damage)
    return changed


def damage_source(report, damage):
    changed = copy.deepcopy(report)
    if damage == 'pin':
        changed['sourceCommit'] = '0' * 40
    elif damage == 'node':
        changed['node'] = 'v20.0.0'
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'missing-input':
        changed['inputs'].pop('reference/packages/core/tools/src/index.ts')
    elif damage == 'changed-input':
        changed['inputs']['reference/packages/core/tools/src/index.ts'] = '0' * 64
    elif damage == 'unsafe-input':
        changed['inputs']['reference/../foreign.py'] = '0' * 64
    elif damage == 'missing-row':
        changed['rows'].pop()
    elif damage == 'row-order':
        changed['rows'].reverse()
    elif damage == 'duplicate-row':
        changed['rows'].append(copy.deepcopy(changed['rows'][-1]))
    else:
        raise ValueError('Unknown Tools Source damage: ' + damage)
    return changed
