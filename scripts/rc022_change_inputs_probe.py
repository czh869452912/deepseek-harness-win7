"""Compare workspace-change paths, numstat parsing and actual bounded captures."""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def numstat_cases():
    return ['', '1\t2\tfile\0', '-\t-\tbinary\0', '3\t4\t\0old\0new\0',
        '0\t1\ttab\tname\0', '2\t3\tline\nname\0', '2\t1\t\0\0\0',
        '1\t1\tf\0-\t-\t\0old\0new\0', '01\t+2\tfile\0', '0x10\t0b10\tf\0',
        'Infinity\t-0\tf\0', 'NaN\tbad\tf\0', '\t \tf\0', '.5\t1e3\tf\0',
        '1\t2\tf', '\0', 'bad\0', '1\tfile\0', '1\t2\t\0', '1\t2\t\0old\0']


def path_cases():
    return [dict(cwd='C:\\repo\\work', root='C:\\repo', home='C:\\Users\\user', absolute=absolute)
        for absolute in ['C:\\repo\\work', 'C:\\repo\\work\\a.txt', 'C:\\repo\\other.txt',
            'C:\\repo\\work\\..hidden', 'C:\\repo\\work-extra\\a', 'C:\\repo\\..other\\a',
            'c:\\REPO\\WORK\\A.txt', 'D:\\elsewhere\\a', 'C:\\Users\\user', 'C:\\Users\\user\\file',
            'C:\\Users\\user\\..private', 'C:\\elsewhere\\file', '\\\\server\\share\\file']]


def prepare(output):
    global OUTPUT
    OUTPUT = output
    files = output/'files'
    files.mkdir()
    (files/'small').write_bytes(b'one\ntwo\n')
    (files/'same').write_bytes(b'one\ntwo\n')
    (files/'empty').write_bytes(b'')
    (files/'binary').write_bytes(b'a\0b')
    (files/'boundary').write_bytes(b'a'*8000+b'\0')
    (files/'probe-boundary').write_bytes(b'a'*7999+b'\0')
    path = output/'input.json'
    path.write_text(json.dumps(dict(files=str(files), numstats=numstat_cases(), paths=path_cases())), encoding='utf-8')
    return [path]


async def observe():
    from dsh.deliverables.change_numstat import parseNumstat
    from dsh.deliverables.change_paths import canonicalPath, compareDisplay, displayPathOf, durablePathOf, isInside, temporaryRoots
    from dsh.deliverables.change_capture import captureFile, sameCapture
    from dsh.cordis.json_text import stringify_json
    rows = []
    for text in numstat_cases():
        try:
            result = parseNumstat(text)
        except Exception as error:
            result = dict(error=str(error))
        rows.append(dict(kind='numstat', input=text, result=result))
    for case in path_cases():
        rows.append(dict(kind='path', input=case, result=dict(inside=isInside(case['cwd'], case['absolute']),
            display=displayPathOf(**case), path=durablePathOf(case['absolute'], case['cwd']))))
    files = OUTPUT/'files'
    captures = []
    for name, limit in [('missing', 10), ('empty', 0), ('small', 8), ('small', 7), ('same', 8),
                        ('binary', 3), ('boundary', 8001), ('probe-boundary', 8000)]:
        value = await captureFile(str(files/name), str(files/'native-copies'), limit)
        if value and 'file' in value:
            value = dict(value, file=Path(value['file']).name)
        captures.append(value)
        rows.append(dict(kind='capture', name=name, limit=limit, result=value))
    rows.append(dict(kind='same', result=[[sameCapture(a, b) for b in captures] for a in captures]))
    missing = str(files/'missing'/'child')
    rows.append(dict(kind='canonical', result=dict(missing=await canonicalPath(missing),
        roots=await temporaryRoots([str(files), os.path.normpath(str(files/'..'/'files'))]))))
    names = ['a', 'A', '../x', '~/', '\U00010000', '\ue000', 'a\U0001f600', 'a\ufffd']
    rows.append(dict(kind='display-order', result=[[compareDisplay(dict(display=a), dict(display=b)) for b in names] for a in names]))
    return json.loads(stringify_json(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_change_inputs.mts',
        'Original/native Git numstat records, Windows display/durable paths, code-unit sorting, '
        'canonical missing descendants, deduplicated temp roots and bounded real content-addressed captures.',
        [Path(__file__).resolve(), ROOT/'dsh/deliverables/change_numstat.py',
         ROOT/'dsh/deliverables/change_paths.py', ROOT/'dsh/deliverables/change_capture.py'], prepare=prepare)
