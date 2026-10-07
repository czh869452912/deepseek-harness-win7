import copy


VALUE_DAMAGES = ('missing-row', 'duplicate-row', 'row-order', 'read-content', 'read-meta', 'read-trace',
    'mutation-bytes', 'mutation-presentation', 'image-bytes', 'image-route', 'window-lines', 'window-error',
    'escalation-reason', 'escalation-policy', 'diff-text', 'boolean-number', 'nonfinite-number',
    'foreign-root', 'foreign-python', 'observer-hash', 'missing-module', 'module-hash', 'extra-field', 'fixture-workspace')
SOURCE_DAMAGES = ('wrong-pin', 'wrong-node', 'missing-input', 'input-hash', 'foreign-input', 'observer-hash',
                  'missing-row', 'duplicate-row', 'public-content', 'extra-field', 'missing-diff-dependency', 'diff-dependency-hash')


def damage_runtime(report, damage):
    value = copy.deepcopy(report)
    if damage == 'missing-row':
        value['rows'].pop()
    elif damage == 'duplicate-row':
        value['rows'].append(copy.deepcopy(value['rows'][0]))
    elif damage == 'row-order':
        value['rows'][0], value['rows'][1] = value['rows'][1], value['rows'][0]
    elif damage == 'foreign-root':
        value['root'] += '-foreign'
    elif damage == 'foreign-python':
        value['python'] = '3.9.0 foreign'
    elif damage == 'observer-hash':
        value['fixtureSha256'] = '0' * 64
    elif damage == 'missing-module':
        value['imports'].pop('dsh/fs/tool_read.py')
    elif damage == 'module-hash':
        value['imports']['dsh/fs/tool_read.py'] = '0' * 64
    elif damage == 'extra-field':
        value['unexpected'] = True
    elif damage == 'fixture-workspace':
        value['fixtureWorkspace'] += '-foreign'
    else:
        prefixes = dict(read='read/', mutation='real/', image='image/', window='window/', escalation='escalation/', diff='diff/')
        prefix = prefixes[damage.split('-')[0]] if damage not in ('boolean-number', 'nonfinite-number') else 'window/'
        row = next(item for item in value['rows'] if item['name'].startswith(prefix))
        if damage == 'boolean-number':
            row['value']['outcome']['totalLines'] = True
        elif damage == 'nonfinite-number':
            row['value']['outcome']['totalLines'] = float('nan')
        elif damage == 'read-content':
            row['result']['content'][0]['text'] += ' damaged'
        elif damage == 'read-meta':
            row['result']['meta']['totalLines'] += 1
        elif damage == 'read-trace':
            row['trace'].pop()
        elif damage == 'mutation-bytes':
            row['afterHex'] = '00'
        elif damage == 'mutation-presentation':
            row['steps'][0]['call']['title'] += ' damaged'
        elif damage == 'image-bytes':
            selected = next(item for item in value['rows'] if item['name'] == 'image/positive')
            selected['stored']['dataHex'] += '00'
        elif damage == 'image-route':
            selected = next(item for item in value['rows'] if item['name'] == 'image/positive')
            selected['lookups'][0]['model'] = 'foreign'
        elif damage == 'window-lines':
            row['value']['outcome']['lines'].pop()
        elif damage == 'window-error':
            selected = next(item for item in value['rows'] if item['name'].startswith('window/') and 'error' in item)
            selected['error']['message'] += ' damaged'
        elif damage == 'escalation-reason':
            selected = next(item for item in value['rows'] if item['name'] == 'escalation/granted')
            next(item for item in selected['trace'] if item['kind'] == 'ask')['reason'] += ' damaged'
        elif damage == 'escalation-policy':
            selected = next(item for item in value['rows'] if item['name'] == 'escalation/granted')
            selected['policy']['mode'] = 'read-only'
        elif damage == 'diff-text':
            row['value'] = [{'path': 'foreign', 'oldText': 'wrong', 'newText': 'wrong'}]
    return value


def damage_source(report, damage):
    value = copy.deepcopy(report)
    if damage == 'wrong-pin':
        value['sourceCommit'] = '0' * 40
    elif damage == 'wrong-node':
        value['node'] = 'v22.22.1'
    elif damage == 'missing-input':
        value['inputs'].pop('reference/packages/fs/tool-fs/src/read.ts')
    elif damage == 'input-hash':
        value['inputs']['reference/packages/fs/tool-fs/src/read.ts'] = '0' * 64
    elif damage == 'foreign-input':
        value['inputs']['../foreign'] = '0' * 64
    elif damage == 'observer-hash':
        value['fixtureSha256'] = '0' * 64
    elif damage == 'missing-row':
        value['rows'].pop()
    elif damage == 'duplicate-row':
        value['rows'].append(copy.deepcopy(value['rows'][0]))
    elif damage == 'public-content':
        value['rows'][0]['afterHex'] = '00'
    elif damage == 'extra-field':
        value['unexpected'] = True
    elif damage == 'missing-diff-dependency':
        value['inputs'].pop('reference/node_modules/.pnpm/diff@9.0.0/node_modules/diff/libesm/diff/base.js')
    elif damage == 'diff-dependency-hash':
        value['inputs']['reference/node_modules/.pnpm/diff@9.0.0/node_modules/diff/libesm/diff/base.js'] = '0' * 64
    return value
