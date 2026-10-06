import copy


VALUE_DAMAGES = ('business-message', 'native-frame', 'result-kind', 'ready', 'body', 'zero',
    'descriptor', 'asset-child', 'asset-bytes', 'asset-missing', 'tail', 'order', 'root',
    'python', 'executable', 'module-missing', 'module-bytes', 'child-root', 'child-python',
    'child-executable', 'child-module', 'asset-extra', 'asset-shape')
SOURCE_DAMAGES = ('pin', 'node', 'inputs', 'bytes', 'row', 'tail', 'order', 'input-shape')


def damage_runtime(original, damage, foreign_root):
    altered = copy.deepcopy(original)
    selected = lambda name: next(row for row in altered['rows'] if row['name'] == name)
    if damage in ('business-message', 'native-frame'):
        selected('errors/guest-error')['result']['error'] = (
            'Error: foreign business' if damage == 'business-message'
            else 'Error: guest-boom\n    at fabricated frame')
    elif damage == 'result-kind':
        selected('session/parse')['result']['kind'] = 'foreign'
    elif damage == 'ready':
        selected('session/parse')['readyResolved'] = True
    elif damage == 'body':
        altered['rows'][0]['body'] = 'return 42'
    elif damage == 'zero':
        selected('session/scalars')['negativeZero'] = False
    elif damage == 'descriptor':
        selected('errors/guest-stack-properties')['result']['value']['own'] = {}
    elif damage == 'asset-child':
        altered['groups']['session']['assets'].clear()
    elif damage == 'asset-bytes':
        altered['assets']['dsh/javascript/bin/dsh_js_worker.exe'] = '0' * 64
        for child in altered['groups'].values():
            child['assets'] = copy.deepcopy(altered['assets'])
    elif damage == 'asset-missing':
        del altered['assets']
    elif damage == 'tail':
        altered['rows'].pop()
    elif damage == 'order':
        altered['rows'].reverse()
    elif damage == 'root':
        altered['root'] = str(foreign_root)
    elif damage == 'python':
        altered['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        altered['executable'] = str(foreign_root / 'python.exe')
    elif damage == 'module-missing':
        del altered['modules']['dsh/javascript/runtime.py']
    elif damage == 'module-bytes':
        altered['modules']['dsh/javascript/runtime.py'] = '0' * 64
    elif damage == 'child-root':
        altered['groups']['session']['root'] = str(foreign_root)
    elif damage == 'child-python':
        altered['groups']['session']['python'] = '3.9.0 foreign runtime'
    elif damage == 'child-executable':
        altered['groups']['session']['executable'] = str(foreign_root / 'python.exe')
    elif damage == 'child-module':
        del altered['groups']['session']['modules']['dsh/javascript/runtime.py']
    elif damage in ('asset-extra', 'asset-shape'):
        if damage == 'asset-extra':
            altered['assets']['dsh/javascript/bin/foreign.dat'] = '0' * 64
        else:
            altered['assets']['dsh/javascript/bin/dsh_js_worker.exe'] = True
        for child in altered['groups'].values():
            child['assets'] = copy.deepcopy(altered['assets'])
    else:
        raise ValueError('Unknown JavaScript error receipt damage')
    for group in ('session', 'errors'):
        altered['groups'][group]['rows'] = [
            {key: (row['name'][len(group) + 1:] if key == 'name' else value)
             for key, value in row.items() if key != 'group'}
            for row in altered['rows'] if row['group'] == group]
    return altered


def damage_source(original, damage):
    altered = copy.deepcopy(original)
    if damage == 'pin':
        altered['sourceCommit'] = '0' * 40
    elif damage == 'node':
        altered['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del altered['inputs']['reference/packages/workflow/workflow-worker-thread/src/session.ts']
    elif damage == 'bytes':
        altered['inputs']['reference/packages/workflow/workflow-worker-thread/src/session.ts'] = '0' * 64
    elif damage == 'row':
        altered['rows'][0]['body'] = 'return 42'
    elif damage == 'tail':
        altered['rows'].pop()
    elif damage == 'order':
        altered['rows'].reverse()
    elif damage == 'input-shape':
        altered['inputs']['reference/packages/workflow/workflow-worker-thread/src/session.ts'] = True
    else:
        raise ValueError('Unknown JavaScript error Source damage')
    return altered
