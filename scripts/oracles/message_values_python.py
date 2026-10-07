import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
root = options.root.resolve()
sys.path.insert(0, str(root))
from dsh.llm import message as helpers
from dsh.cordis.context import Context
from dsh.core.session import Session
from dsh.core.session.json import FrozenDict, FrozenList
from dsh.core.runtime_context import RuntimeContextProjection, SOURCE


def frozen(value):
    return isinstance(value, (FrozenDict, FrozenList)) or not isinstance(value, (dict, list))


def encode(value):
    objects, indexes, nodes = [], {}, []
    def atom(item):
        if not isinstance(item, (dict, list)):
            return {'value': item}
        if id(item) not in indexes:
            indexes[id(item)] = len(objects)
            objects.append(item)
        return {'ref': indexes[id(item)]}
    identity = atom(value)
    position = 0
    while position < len(objects):
        item = objects[position]
        values = [atom(child) for child in item] if isinstance(item, list) else [[key, atom(item[key])] for key in sorted(item)]
        nodes.append(dict(type='array' if isinstance(item, list) else 'object', frozen=frozen(item), values=values))
        position += 1
    return dict(root=identity, nodes=nodes)


cases_path = Path(__file__).with_name('message-values-cases.json')
cases = json.loads(cases_path.read_text(encoding='utf-8'))
rows = []
for case in cases:
    name, helper, value = case['name'], case['helper'], case['input']
    before = copy.deepcopy(value)
    message = getattr(helpers, helper)(value)
    borrowed_input = value.get('extra', value.get('source'))
    borrowed_message = message.get('extra', message.get('source'))
    rows.append(dict(name=name, helper=helper, inputUnchanged=value == before,
        detached=borrowed_input is None or borrowed_message is None or borrowed_input is not borrowed_message,
        allocated=helper != 'freezeMessage', message=message, frozen=frozen(message),
        contentFrozen=frozen(message.get('content')), sourceFrozen=frozen(message.get('source'))))
shared = dict(flag=False, count=0, empty=[])
graph = dict(id='preserved-graph', role='user', source=dict(kind='user', shared=shared),
             content=[dict(type='text', text='graph')], extra=dict(first=shared, second=shared))
graph['extra']['self'] = graph['extra']
graph['extra']['message'] = graph
shared['empty'].extend([shared['empty'], graph])
first = helpers.freezeMessage(graph)
rows.append(dict(name='graph-first', detached=first is not graph, message=encode(first)))
try:
    second = helpers.freezeMessage(first)
    rows.append(dict(name='graph-repeat', detached=second is not first, message=encode(second)))
except Exception as error:
    rows.append(dict(name='graph-repeat', error=dict(name=type(error).__name__, message=str(error))))
for name, current, sections, previous in (
    ('projection-empty', '', [], None), ('projection-current', 'new', [], None),
    ('projection-section', 'new', [dict(name='policy', text='new')], None),
    ('projection-same', 'old', [], 'old'), ('projection-changed', 'new', [], 'old'),
    ('projection-cleared', '', [], 'old'),
):
    ctx = Context()
    session = Session('message-projection')
    if previous is not None:
        session.append('user/message', helpers.freezeMessage(dict(id='retained-id', role='user',
            content=[dict(type='text', text=previous)], source=dict(kind='plugin', plugin=SOURCE))), surface_op='append')
    projection = RuntimeContextProjection(ctx, session)
    message = projection.project(current, sections)
    row = dict(name=name, present=message is not None, allocated=message is not None)
    if message is not None:
        row.update(message=message, frozen=frozen(message), contentFrozen=frozen(message.get('content')),
                   sourceFrozen=frozen(message.get('source')))
    rows.append(row)
    asyncio.run(ctx.fiber.dispose())
imports = {}
for name, module in sorted(sys.modules.items()):
    filename = getattr(module, '__file__', None)
    if filename and (name == 'dsh' or name.startswith('dsh.')):
        path = Path(filename).resolve()
        imports[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
with options.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), python=sys.version, executable=sys.executable, imports=imports, rows=rows,
        fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        casesSha256=hashlib.sha256(cases_path.read_bytes()).hexdigest()), stream, indent=2)
    stream.write('\n')
