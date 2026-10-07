import copy


VALUE_DAMAGES = ('missing-row', 'row-order', 'duplicate-row', 'mux-text', 'mux-value', 'mux-end',
    'rpc-text', 'rpc-status', 'llm-request', 'llm-finish', 'module-bytes', 'missing-module',
    'fixture', 'foreign-root', 'foreign-executable', 'wrong-python')
SOURCE_DAMAGES = ('pin', 'node', 'fixture', 'missing-input', 'changed-input', 'unsafe-input',
    'missing-row', 'row-order', 'duplicate-row')


def damage_runtime(report, damage):
    changed = copy.deepcopy(report)
    rows = {row['name']: row for row in changed['rows']}
    if damage == 'missing-row':
        changed['rows'].pop()
    elif damage == 'row-order':
        changed['rows'].reverse()
    elif damage == 'duplicate-row':
        changed['rows'].append(copy.deepcopy(changed['rows'][0]))
    elif damage == 'mux-text':
        rows['read/mux']['value'][0]['text'] += ' '
    elif damage == 'mux-value':
        rows['high/mux']['value'][0]['value']['value'] = 'replacement'
    elif damage == 'mux-end':
        rows['low/mux']['value'].pop()
    elif damage == 'rpc-text':
        rows['keys/rpc']['value']['text'] += ' '
    elif damage == 'rpc-status':
        rows['read/rpc']['value']['status'] = 400
    elif damage == 'llm-request':
        rows['pair/llm']['value']['requests'][0]['body']['messages'][0]['content'] = 'replacement'
    elif damage == 'llm-finish':
        rows['high/llm']['value']['chunks'].pop()
    elif damage == 'module-bytes':
        changed['imports']['dsh/cordis/json_text.py'] = '0' * 64
    elif damage == 'missing-module':
        changed['imports'].pop('dsh/cordis/json_text.py')
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'foreign-root':
        changed['root'] += '-foreign'
    elif damage == 'foreign-executable':
        changed['executable'] += '-foreign'
    elif damage == 'wrong-python':
        changed['python'] = '3.9.0 foreign'
    else:
        raise ValueError('Unknown Unicode carrier damage: ' + damage)
    return changed


def damage_source(report, damage):
    changed = copy.deepcopy(report)
    path = 'reference/packages/api/gateway/src/stream-server.ts'
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
        raise ValueError('Unknown Unicode carrier Source damage: ' + damage)
    return changed
