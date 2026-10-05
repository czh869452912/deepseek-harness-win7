import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


FIELDS = ('version', 'createdAt', 'seedLength', 'delegationDepth', 'seq', 'time')
LABELS = ('whole', 'negative-zero', 'fraction')
NAMES = tuple(field + '/' + label for field in FIELDS for label in LABELS)


def observe(name):
    from dsh.core.session import Session

    if name not in NAMES:
        raise ValueError('Unknown Session restore sign observation')
    field, label = name.split('/')
    value = {'whole': 0.0 if field in ('version', 'seq') else 1.0, 'negative-zero': -0.0, 'fraction': 0.5}[label]
    header = dict(id='s', version=0, createdAt=1)
    event = dict(type='session/end-seed', seq=0, time=1, data={})
    (event if field in ('seq', 'time') else header)[field] = value
    row = dict(name=name)
    try:
        session = Session.from_restore('s', [event], header)
        actual = session.events[0][field] if field in ('seq', 'time') else session.header[field]
        row.update(accepted=True, safeInteger=type(actual) in (int, float) and math.isfinite(actual)
            and abs(actual) <= 9007199254740991 and int(actual) == actual,
            negativeZero=actual == 0 and math.copysign(1, actual) < 0,
            equalInput=actual == value and (actual != 0 or math.copysign(1, actual) == math.copysign(1, value)))
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
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
