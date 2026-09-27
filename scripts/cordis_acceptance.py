"""Accept the scoped Cordis observations with one explicit Python-language adaptation.

The raw differential report still fails C58. This gate requires its exact native
signature and a matching C59 adapter; it never erases or normalizes that difference.
"""
import argparse
import hashlib
import json
from pathlib import Path


def evaluate(report):
    rows = report.get('cases', [])
    expected = {'C%d' % n for n in range(1, 68)}
    errors = []
    if len(rows) != 67 or {row.get('case') for row in rows} != expected:
        errors.append('Expected exactly C1-C67, with no duplicates or missing cases.')
    for row in rows:
        case = row.get('case')
        sides = [row.get(side, {}) for side in ('upstream', 'python')]
        if any(side.get('status') != 'observed' or side.get('exit_code') != 0 for side in sides):
            errors.append(str(case) + ': observer did not complete.')
            continue
        left, right = [side.get('observation') for side in sides]
        if case == 'C58':
            if (row.get('status') != 'different' or
                left != {'immediate': ['prefix', 'peer'], 'log': ['prefix', 'peer', 'tail']} or
                right != {'immediate': ['prefix', 'tail', 'peer'], 'log': ['prefix', 'tail', 'peer']}):
                errors.append('C58 no longer has the reviewed native scheduling signature.')
        elif row.get('status') != 'matched' or left != right or row.get('differences'):
            errors.append(str(case) + ': unaccepted differential.')
    return {'result': 'failed' if errors else 'passed', 'errors': errors,
            'scope': 'C1-C67 source-derived Cordis/Loader/Include/HMR/schema observations only',
            'adaptations': ['PY38-RESOLVED-AWAIT: C58 native divergence retained; C59 explicit checkpoint must match.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.report.read_bytes()
    report = json.loads(raw)
    result = evaluate(report)
    result.update(report=str(args.report), report_sha256=hashlib.sha256(raw).hexdigest(),
                  target_upstream=report['target_upstream'], product_commit=report['product_base'])
    args.output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(result['result'])
    return 0 if result['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
