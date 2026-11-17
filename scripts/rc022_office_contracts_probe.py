"""Pair original SDK validation against the shipped Win7 QuickJS contract worker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh.cordis.utils import _UNDEFINED
from dsh.office.contracts import observe, prepare, RESOURCES


def cases(root):
    rows = []
    def add(name, kind, value):
        rows.append((name, kind, value))
    inputs = ('doc', 'docx', 'odt', 'xls', 'xlsx', 'ods', 'ppt', 'pptx', 'odp', 'pdf', '', 'unknown')
    outputs = ('pdf', 'docx', 'odt', 'txt', 'xlsx', 'ods', 'csv', 'pptx', 'odp', '', 'unknown')
    for kind in ('render', 'convert', 'recalculate'):
        for source in inputs:
            for output in outputs:
                add(kind + '-' + source + '-' + output, kind, dict(inputPath=str(root / ('input.' + source)), outputPath=str(root / ('output.' + output))))
    source, target = str(root / 'input.docx'), str(root / 'output.pdf')
    for index, path in enumerate([None, True, 1, '', 'relative.docx', 'C:relative.docx', '\\root.docx', 'C:/input.docx', '\\\\server\\share\\input.docx', source + '\0', source, source.replace('\\', '/'), str(root / '.docx'), str(root / '...'), str(root / 'x.docx.')]):
        add('input-path-' + str(index), 'convert', dict(inputPath=path, outputPath=target))
        add('output-path-' + str(index), 'convert', dict(inputPath=source, outputPath=path))
    for sheet in [None, '', ' ', '\ufeff', '\0', 'Exact Name', True, 1, [], _UNDEFINED]:
        for extension in ('csv', 'pdf'):
            add('sheet-' + str(len(rows)), 'convert', dict(inputPath=str(root / 'input.xlsx'), outputPath=str(root / ('output.' + extension)), sheet=sheet))
    for value in [_UNDEFINED, {}, None, True, [], 'bad', dict(unknown=1), dict(toString=1)]:
        add('options-' + str(len(rows)), 'options', value)
    for key in ('timeoutMs', 'maxInputBytes', 'maxOutputBytes', 'maxImageResolution', 'maxArchiveEntries', 'maxUncompressedBytes',
                'maxFontFiles', 'maxFontFileBytes', 'maxLoadedFontBytes', 'maxFontResolutionEntries', 'maxFontMetadataCacheBytes'):
        for value in [0, -1, 1, 1.5, True, None, '1', 9007199254740991, 9007199254740992, 2147483648, float('nan'), float('inf'), _UNDEFINED]:
            add(key + '-' + str(len(rows)), 'options', {key: value})
    for key in ('fontDirectories', 'initialFontFamilies'):
        for value in [None, [], {}, [''], [' '], ['a\0b'], ['Arial'], [1], _UNDEFINED]:
            add(key + '-' + str(len(rows)), 'options', {key: value})
    for value in [None, [], {}, [['a']], [['a', 'b']], [[' ', 'b']], [['\ufeff', 'b']], [['a\0', 'b']], [True], _UNDEFINED]:
        add('fallbacks-' + str(len(rows)), 'options', dict(fontFallbacks=value))
    for value in [False, True, '', 'relative', str(root / 'cache'), None, source + '\0', _UNDEFINED]:
        add('metadata-cache-' + str(len(rows)), 'options', dict(fontMetadataCacheDirectory=value))
    for value in [None, {}, 'callback', _UNDEFINED]:
        add('resolver-' + str(len(rows)), 'options', dict(resolveEnginePackage=value))
    image = dict(inputPath=source, outputDir=str(root / 'images'))
    for key, values in [('pages', ['all', None, [], [1], [1, 1], [0], [True], [1.5], [9007199254740992]]),
                        ('sheet', ['', ' ', 'Sheet 1', None, True]),
                        ('range', ['A1', '$b$2:d4', 'XFD1048576', 'XFE1', 'A1048577', 'B2:A1', 'A0', 'Sheet1!A1', None, True]),
                        ('dpi', [23, 24, 600, 601, 96.5, None, True, float('nan'), float('inf')]),
                        ('maxPages', [0, 1, 10000, 10001, 1.5, True]),
                        ('maxPixels', [0, 1, 16777216, 16777217, 1.5, True]),
                        ('maxDimension', [0, 1, 16777216, 16777217, 1.5, True])]:
        for value in values:
            for extension in ('docx', 'xlsx'):
                request = dict(image, inputPath=str(root / ('input.' + extension)), **{key: value})
                if key == 'range':
                    request['sheet'] = 'Sheet 1'
                add('images-' + key + '-' + str(len(rows)), 'images', request)
    for output in [str(root), source, str(root / 'images/..'), 'relative', None, 'D:\\elsewhere']:
        add('images-output-' + str(len(rows)), 'images', dict(image, outputDir=output))
    for extension in inputs:
        add('images-format-' + extension, 'images', dict(image, inputPath=str(root / ('input.' + extension))))
    add('images-selected-budget', 'images', dict(image, pages=[1, 2], maxPages=1))
    return rows


def pair(source, node, root):
    corpus = cases(root)
    prepared = [prepare(kind, value) for _, kind, value in corpus]
    command = [str(node), str(Path(__file__).resolve().parent / 'oracles/rc022_office_contracts.mjs'), str(source)]
    completed = subprocess.run(command, input=json.dumps(prepared, ensure_ascii=True, allow_nan=False).encode('utf-8'),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode('utf-8', 'replace'))
    expected = json.loads(completed.stdout)
    actual = observe([(kind, value) for _, kind, value in corpus])
    rows = [dict(name=name, equal=native == original, native=native, source=original) for (name, _, _), native, original in zip(corpus, actual, expected)]
    assert len(rows) == len(corpus) == len(expected)
    return dict(rows=rows, all_equal=all(row['equal'] for row in rows), count=len(rows), source_command=command,
                runtime_manifest_sha256=hashlib.sha256((RESOURCES / 'manifest.json').read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser()
    for key in ('source', 'node', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    assert (root / '.goose/out').resolve() in out.parents
    out.mkdir()
    start = time.monotonic()
    report = pair(args.source, args.node, out)
    report.update(command=[sys.executable] + sys.argv, seconds=time.monotonic() - start)
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(count=report['count'], all_equal=report['all_equal'], seconds=report['seconds'],
                          differences=[dict(name=row['name'], native=row['native'].get('message'), source=row['source'].get('message')) for row in report['rows'] if not row['equal']][:6])), flush=True)
    assert report['all_equal']


if __name__ == '__main__':
    main()
