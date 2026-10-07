import copy


VALUE_DAMAGES = ('missing', 'order', 'value', 'render', 'description', 'null-success',
    'selected-success', 'disposal', 'question-extra', 'signal', 'root', 'python', 'executable',
    'closure-missing', 'closure-tail', 'module-hash', 'fixture')
SOURCE_DAMAGES = ('missing', 'order', 'description', 'pin', 'node', 'fixture',
    'inputs-missing', 'inputs-hash', 'inputs-foreign', 'inputs-path')


def damage_runtime(report, damage):
    changed = copy.deepcopy(report)
    rows = {row['name']: row for row in changed['rows']}
    if damage == 'missing':
        changed['rows'].pop()
    elif damage == 'order':
        changed['rows'].reverse()
    elif damage == 'value':
        rows['answers']['result'].pop('value')
    elif damage == 'render':
        rows['answers']['result']['content'][0]['text'] += ' '
    elif damage == 'description':
        rows['with-questions']['schema']['parameters']['properties']['questions'].pop('description')
    elif damage == 'null-success':
        rows['custom-null']['result']['isError'] = False
    elif damage == 'selected-success':
        rows['selected-invalid']['result']['isError'] = False
    elif damage == 'disposal':
        rows['questions-disposed']['schemas'] = [rows['with-questions']['schema']]
    elif damage == 'question-extra':
        rows['answers']['requests'][0]['questions'][0]['extra'] = 'not projected'
    elif damage == 'signal':
        rows['answers']['requests'][0]['signalPresent'] = False
    elif damage == 'root':
        changed['root'] += '-foreign'
    elif damage == 'python':
        changed['python'] = '3.11.0 foreign'
    elif damage == 'executable':
        changed['executable'] += '-foreign'
    elif damage == 'closure-missing':
        changed['imports'].pop('dsh/interaction/tool_ask_user.py')
    elif damage == 'closure-tail':
        changed['imports']['dsh/foreign.py'] = '0' * 64
    elif damage == 'module-hash':
        changed['imports']['dsh/interaction/tool_ask_user.py'] = '0' * 64
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    else:
        raise ValueError('Unknown ask-user damage: ' + damage)
    return changed


def damage_source(report, damage):
    changed = copy.deepcopy(report)
    if damage in ('missing', 'order', 'description'):
        return damage_runtime(changed, damage)
    if damage == 'pin':
        changed['sourceCommit'] = '0' * 40
    elif damage == 'node':
        changed['node'] = 'v20.0.0'
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'inputs-missing':
        changed['inputs'].pop('scripts/oracles/ask_user_python.py')
    elif damage == 'inputs-hash':
        changed['inputs']['reference/packages/interaction/tool-ask-user/src/index.ts'] = '0' * 64
    elif damage == 'inputs-foreign':
        changed['inputs']['foreign/observer.py'] = '0' * 64
    elif damage == 'inputs-path':
        changed['inputs']['reference/../foreign.py'] = '0' * 64
    else:
        raise ValueError('Unknown ask-user Source damage: ' + damage)
    return changed
