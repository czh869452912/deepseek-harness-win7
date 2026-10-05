import argparse
import hashlib
import json
from pathlib import Path
import sys


FIELDS = ('version', 'createdAt', 'seedLength', 'delegationDepth', 'seq', 'time')
LABELS = ('whole', 'negative-zero', 'fraction', 'negative', 'boolean', 'unsafe', 'nan', 'infinite')
ACTIONS = ('unknown-field', 'header-mutation', 'nested-header-mutation')
NAMES = tuple(field + '/' + label for field in FIELDS for label in LABELS) + ACTIONS


def observe(name):
    from dsh.core.session import Session

    if name in ACTIONS:
        header = dict(id='s', version=0, createdAt=1, extra=dict(nested=[1, 2]))
        session = Session.create('s', [], header)
        row = dict(name=name)
        if name == 'header-mutation':
            try:
                session.header.created_at = 9
                row['mutationAccepted'] = True
            except Exception:
                row['mutationAccepted'] = False
        elif name == 'nested-header-mutation':
            try:
                session.header['extra']['nested'].append(3)
                row['mutationAccepted'] = True
            except Exception:
                row['mutationAccepted'] = False
        row.update(header=session.header.to_dict(), input=header)
        return row
    field, label = name.split('/')
    if field not in FIELDS or label not in LABELS:
        raise ValueError('Unknown Session number observation')
    number = {'whole': 0.0 if field in ('version', 'seq') else 1.0, 'negative-zero': -0.0,
        'fraction': 0.5, 'negative': -1, 'boolean': False, 'unsafe': 9007199254740992,
        'nan': float('nan'), 'infinite': float('inf')}[label]
    header = dict(id='s', version=0, createdAt=1)
    event = dict(type='session/end-seed', seq=0, time=1, data={})
    (event if field in ('seq', 'time') else header)[field] = number
    row = dict(name=name)
    try:
        session = Session.create('s', [event], header)
        row.update(header=session.header.to_dict(), events=session.events, accepted=True)
    except Exception as error:
        if not isinstance(error, ValueError):
            raise
        row.update(error=dict(name='Error', message=str(error)), accepted=False)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root = options.root.resolve()
    sys.path.insert(0, str(root))
    rows = [observe(name) for name in NAMES]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version,
            modules=modules, rows=rows), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
