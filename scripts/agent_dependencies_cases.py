import copy


VALUE_DAMAGES = ('missing', 'order', 'pending', 'fallback', 'loss', 'retired-factory',
    'restoration', 'published', 'final-disposal', 'root', 'python', 'executable', 'closure-missing', 'closure-tail', 'module-hash', 'fixture')
SOURCE_DAMAGES = ('missing', 'order', 'retired-factory', 'pin', 'node', 'fixture', 'inputs-missing', 'inputs-hash', 'inputs-foreign', 'inputs-path')


def damage_runtime(report, damage):
    changed = copy.deepcopy(report)
    rows = {row['name']: row for row in changed['rows']}
    if damage == 'missing':
        changed['rows'].pop()
    elif damage == 'order':
        changed['rows'].reverse()
    elif damage == 'pending':
        rows['provide-tools']['active'] = True
    elif damage == 'fallback':
        rows['provide-tools']['services']['sessions'] = True
    elif damage == 'loss':
        rows['llm/after-loss']['published'] = True
    elif damage == 'retired-factory':
        rows['tools/retired-factory']['result']['message'] = 'agent loop is not active'
    elif damage == 'restoration':
        rows['sessions/restored']['replacement'] = False
    elif damage == 'published':
        rows['agents/restored-create']['published'] = False
    elif damage == 'final-disposal':
        rows['systemPrompt/final-disposal']['loop'] = True
    elif damage == 'root':
        changed['root'] += '-foreign'
    elif damage == 'python':
        changed['python'] = '3.11.0 foreign'
    elif damage == 'executable':
        changed['executable'] += '-foreign'
    elif damage == 'closure-missing':
        changed['imports'].pop('dsh/core/agent_loop.py')
    elif damage == 'closure-tail':
        changed['imports']['dsh/foreign.py'] = '0' * 64
    elif damage == 'module-hash':
        changed['imports']['dsh/core/agent_loop.py'] = '0' * 64
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    else:
        raise ValueError('Unknown dependency damage: ' + damage)
    return changed


def damage_source(report, damage):
    changed = copy.deepcopy(report)
    if damage in ('missing', 'order', 'retired-factory'):
        return damage_runtime(changed, damage)
    if damage == 'pin':
        changed['sourceCommit'] = '0' * 40
    elif damage == 'node':
        changed['node'] = 'v20.0.0'
    elif damage == 'fixture':
        changed['fixtureSha256'] = '0' * 64
    elif damage == 'inputs-missing':
        changed['inputs'].pop('scripts/oracles/agent_dependencies_python.py')
    elif damage == 'inputs-hash':
        changed['inputs']['reference/packages/core/agent-loop/src/index.ts'] = '0' * 64
    elif damage == 'inputs-foreign':
        changed['inputs']['foreign/observer.py'] = '0' * 64
    elif damage == 'inputs-path':
        changed['inputs']['reference/../foreign.py'] = '0' * 64
    else:
        raise ValueError('Unknown dependency Source damage: ' + damage)
    return changed
