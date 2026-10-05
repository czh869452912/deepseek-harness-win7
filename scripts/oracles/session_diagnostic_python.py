import argparse
import hashlib
import json
from pathlib import Path
import sys


MODES = ('create', 'restore')
FIELDS = ('version', 'id')
LABELS = ('missing', 'null', 'true', 'false', 'zero', 'one', 'fraction', 'negative-zero', 'nan',
    'infinite', 'negative-infinite', 'empty-array', 'string', 'object', 'nested-array',
    'large-exponent', 'small-exponent', 'decimal-threshold', 'integer-threshold')
NAMES = tuple(mode + '/' + field + '/' + label for mode in MODES for field in FIELDS for label in LABELS)


def observe(name):
    from dsh.core.session import Session

    mode, field, label = name.split('/')
    if name not in NAMES:
        raise ValueError('Unknown Session diagnostic observation')
    values = dict(missing=None, null=None, true=True, false=False, zero=0, one=1, fraction=1.5,
        **{'negative-zero': -0.0, 'nan': float('nan'), 'infinite': float('inf'),
            'negative-infinite': -float('inf'), 'empty-array': [], 'string': 's', 'object': {},
            'nested-array': ['x', None, ['y']], 'large-exponent': 1e21, 'small-exponent': 1e-7,
            'decimal-threshold': 1e-6, 'integer-threshold': 1e20})
    header = dict(id='s', version=0, createdAt=1)
    if label == 'missing':
        del header[field]
    else:
        header[field] = values[label]
    row = dict(name=name)
    try:
        if mode == 'create':
            Session.create('s', [], header)
        else:
            Session.from_restore('s', [], header)
        row['accepted'] = True
    except ValueError as error:
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
