import copy


VALUE_DAMAGES = ('missing', 'duplicate', 'order', 'calls', 'outcome', 'null-missing', 'absent-added',
    'bool-zero', 'empty-object-array', 'plain-error-added', 'typed-code', 'skip-error-message',
    'short-id', 'duplicate-id', 'surface', 'source-seq', 'time', 'message-body', 'public-value',
    'root', 'python', 'executable', 'closure-missing', 'closure-tail', 'module-hash', 'fixture')
SOURCE_DAMAGES = ('missing', 'order', 'short-id', 'pin', 'node', 'fixture', 'inputs-missing',
    'inputs-hash', 'inputs-foreign', 'inputs-path')


def damage_runtime(report, damage):
    result = copy.deepcopy(report)
    rows = result['rows']
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'order':
        rows.reverse()
    elif damage == 'calls':
        rows[0]['calls'].pop()
    elif damage == 'outcome':
        rows[0]['outcome']['concluded'] = True
    elif damage == 'null-missing':
        del rows[1]['events'][1]['data']['meta']
    elif damage == 'absent-added':
        rows[0]['events'][1]['data']['meta'] = None
    elif damage == 'bool-zero':
        rows[2]['publicResults'][0]['meta'] = 0
    elif damage == 'empty-object-array':
        rows[4]['events'][1]['data']['meta'] = []
    elif damage == 'plain-error-added':
        rows[8]['events'][1]['data']['error'] = dict(message='plain failure')
    elif damage == 'typed-code':
        rows[9]['events'][1]['data']['error']['code'] = 'OTHER'
    elif damage == 'skip-error-message':
        rows[10]['events'][1]['data']['error']['message'] = 'tool call aborted before dispatch'
    elif damage == 'short-id':
        rows[0]['events'][1]['data']['message']['id'] = 'msg-01234567'
    elif damage == 'duplicate-id':
        rows[0]['events'][3]['data']['message']['id'] = rows[0]['events'][1]['data']['message']['id']
    elif damage == 'surface':
        rows[0]['events'][1]['surfaceOp'] = 'replace'
    elif damage == 'source-seq':
        rows[0]['events'][1]['sourceEventSeqs'] = [12345]
    elif damage == 'time':
        rows[0]['events'][1]['time'] += 1
    elif damage == 'message-body':
        rows[0]['events'][1]['data']['message']['content'][0]['content'][0]['text'] = 'changed'
    elif damage == 'public-value':
        rows[0]['publicResults'][0]['value'] = 'changed'
    elif damage == 'root':
        result['root'] += '-foreign'
    elif damage == 'python':
        result['python'] = '3.11.0 foreign'
    elif damage == 'executable':
        result['executable'] += '.foreign'
    elif damage == 'closure-missing':
        del result['imports']['dsh/core/tool_calls.py']
    elif damage == 'closure-tail':
        result['imports']['dsh/foreign.py'] = '0' * 64
    elif damage == 'module-hash':
        result['imports']['dsh/core/tool_calls.py'] = '0' * 64
    elif damage == 'fixture':
        result['fixtureSha256'] = '0' * 64
    else:
        raise ValueError('Unknown durable damage ' + damage)
    return result


def damage_source(report, damage):
    result = copy.deepcopy(report)
    if damage in ('missing', 'order', 'short-id'):
        result = damage_runtime(result, damage)
    elif damage == 'pin':
        result['sourceCommit'] = '0' * 40
    elif damage == 'node':
        result['node'] = 'v20.0.0'
    elif damage == 'fixture':
        result['fixtureSha256'] = '0' * 64
    elif damage == 'inputs-missing':
        del result['inputs']['scripts/oracles/tool-durable-cases.json']
    elif damage == 'inputs-hash':
        result['inputs']['reference/packages/core/agent-loop/src/tool-calls.ts'] = '0' * 64
    elif damage == 'inputs-foreign':
        result['inputs']['foreign/observer.py'] = '0' * 64
    elif damage == 'inputs-path':
        result['inputs']['reference/../foreign.py'] = '0' * 64
    else:
        raise ValueError('Unknown durable Source damage ' + damage)
    return result
