"""Exhaustive short repeated-line matching and bounded unified hunk comparison."""
import itertools
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    words = ['\n'.join(tokens) for length in range(5) for tokens in itertools.product(('a', 'b'), repeat=length)]
    rows = [dict(before=a, after=b, timeoutMs=1000) for a in words for b in words]
    generator = random.Random(322)
    for _ in range(128):
        before = [generator.choice(('repeat', 'line', '', ' x ', '\u4e2d\u6587', '\U0001f600')) for _ in range(generator.randrange(30))]
        after = list(before)
        for _ in range(generator.randrange(1, 8)):
            start = generator.randrange(len(after)+1)
            after[start:start+generator.randrange(4)] = [generator.choice(('new', 'line', '', ' x ')) for _ in range(generator.randrange(4))]
        rows.append(dict(before='\n'.join(before), after='\n'.join(after), timeoutMs=1000))
    rows.extend(dict(before=before, after=after, timeoutMs=timeout)
        for before, after in [(None, ''), ('', None), (None, 'a'), ('a', None), ('a', 'a\n'),
            ('a\r\n', 'a\n'), ('\r', '\n'), ('\n', ''), ('\0\n', 'z\n'),
            ('\n'.join(str(i) for i in range(25)), '\n'.join('changed' if i in (2, 9, 20) else str(i) for i in range(25)))]
        for timeout in (1000, -1))
    return rows


async def observe():
    from dsh.deliverables.change_compare import compareText
    return [dict(case=case, result=compareText(**case)) for case in cases()]


def prepare(output):
    path = output/'cases.json'
    path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_change_compare.mts',
        'Actual original compareText versus native line-path implementation: exhaustive repeated short lines, '
        'seeded edits, hunk context/merging, null/empty/CRLF/Unicode/NUL, ignored final newline and forced coarse fallback.',
        [Path(__file__).resolve(), ROOT/'dsh/deliverables/change_compare.py'], prepare=prepare)
