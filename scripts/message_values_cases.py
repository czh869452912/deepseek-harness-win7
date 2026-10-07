import copy


VALUE_DAMAGES = ('missing', 'order', 'identity-prefix', 'identity-version', 'identity-reused',
    'retained-identity', 'user-default', 'user-coercion', 'assistant-extra', 'assistant-source',
    'tool-call', 'readonly', 'alias', 'cycle', 'graph-readonly', 'repeat-clone', 'projection-shape',
    'projection-presence', 'root', 'python', 'executable', 'closure-missing', 'closure-tail',
    'module-hash', 'fixture', 'cases')
SOURCE_DAMAGES = ('missing', 'order', 'readonly', 'cycle', 'pin', 'node', 'fixture', 'cases',
    'inputs-missing', 'inputs-hash', 'inputs-foreign', 'inputs-path')


def damage_runtime(report, damage):
    changed = copy.deepcopy(report)
    rows = {row['name']: row for row in changed['rows']}
    if damage == 'missing':
        changed['rows'].pop()
    elif damage == 'order':
        changed['rows'].reverse()
    elif damage == 'identity-prefix':
        rows['base']['message']['id'] = 'msg-' + rows['base']['message']['id']
    elif damage == 'identity-version':
        rows['base']['message']['id'] = '00000000-0000-5000-8000-000000000001'
    elif damage == 'identity-reused':
        rows['user']['message']['id'] = rows['base']['message']['id']
    elif damage == 'retained-identity':
        rows['freeze']['message']['id'] = 'new-identity'
    elif damage == 'user-default':
        rows['user-no-source']['message']['source'] = dict(kind='user')
    elif damage == 'user-coercion':
        rows['user-string']['message']['content'] = [dict(type='text', text='literal input')]
    elif damage == 'assistant-extra':
        rows['assistant-extra']['message']['extra'] = 'discarded'
    elif damage == 'assistant-source':
        rows['assistant-kind']['message']['source']['kind'] = 'model'
    elif damage == 'tool-call':
        rows['tool']['message']['content'][0]['toolCallId'] = 'other'
    elif damage == 'readonly':
        rows['freeze']['contentFrozen'] = False
    elif damage in ('alias', 'cycle', 'graph-readonly'):
        nodes = rows['graph-first']['message']['nodes']
        if damage == 'graph-readonly':
            nodes[-1]['frozen'] = False
        else:
            selected = next(node for node in nodes if node['type'] == 'object' and any(pair[0] == ('first' if damage == 'alias' else 'self') for pair in node['values']))
            next(pair for pair in selected['values'] if pair[0] == ('first' if damage == 'alias' else 'self'))[1] = dict(ref=0)
    elif damage == 'repeat-clone':
        rows['graph-repeat']['detached'] = False
    elif damage == 'projection-shape':
        rows['projection-current']['message']['source'].update(form='snapshot', sections=[])
    elif damage == 'projection-presence':
        rows['projection-empty']['present'] = True
    elif damage == 'root':
        changed['root'] += '-foreign'
    elif damage == 'python':
        changed['python'] = '3.11.0 foreign'
    elif damage == 'executable':
        changed['executable'] += '-foreign'
    elif damage == 'closure-missing':
        changed['imports'].pop('dsh/llm/message.py')
    elif damage == 'closure-tail':
        changed['imports']['dsh/foreign.py'] = '0' * 64
    elif damage == 'module-hash':
        changed['imports']['dsh/llm/message.py'] = '0' * 64
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'cases':
        changed['casesSha256'] = '0' * 64
    else:
        raise ValueError('Unknown Message damage: ' + damage)
    return changed


def damage_source(report, damage):
    changed = copy.deepcopy(report)
    if damage in ('missing', 'order', 'readonly', 'cycle'):
        return damage_runtime(changed, damage)
    if damage == 'pin':
        changed['sourceCommit'] = '0' * 40
    elif damage == 'node':
        changed['node'] = 'v20.0.0'
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'cases':
        changed['casesSha256'] = '0' * 64
    elif damage == 'inputs-missing':
        changed['inputs'].pop('scripts/oracles/message_values_python.py')
    elif damage == 'inputs-hash':
        changed['inputs']['reference/packages/llm/llm/src/message.ts'] = '0' * 64
    elif damage == 'inputs-foreign':
        changed['inputs']['foreign/observer.py'] = '0' * 64
    elif damage == 'inputs-path':
        changed['inputs']['reference/../foreign.py'] = '0' * 64
    else:
        raise ValueError('Unknown Message Source damage: ' + damage)
    return changed
