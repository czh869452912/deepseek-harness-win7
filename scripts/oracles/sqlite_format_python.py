import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys


MODULES = ['dsh/session/sqlite_codec.py', 'dsh/session/sqlite_source_seqs.py', 'dsh/session/sqlite_compression.py',
           'dsh/session/sqlite_json.py', 'dsh/session/zstd.py', 'dsh/cordis/json_text.py', 'dsh/cordis/utils.py']


def observe(root, inputs, frames):
    sys.path.insert(0, str(root))
    from dsh.session import sqlite_codec as codec
    from dsh.session import sqlite_compression as compression
    from dsh.session import sqlite_source_seqs as sequences
    from dsh.session import zstd
    from dsh.cordis.json_text import stringify_json
    rows = []

    def capture(name, operation):
        try:
            rows.append(dict(name=name, value=operation()))
        except Exception as error:
            rows.append(dict(name=name, error=dict(name='TypeError' if isinstance(error, TypeError) else getattr(error, 'name', 'Error'),
                                                  message=str(error), code=getattr(error, 'code', None))))

    for item in inputs['packs']:
        capture(item['name'], lambda item=item: codec.pack_chunk_runs(item['events']))
    for item in inputs['decodes']:
        capture(item['name'], lambda item=item: codec.decode_storage_record(item['value']))
    for item in inputs['varints']['encode']:
        capture(item['name'], lambda item=item: sequences.encode_source_event_seqs(item['values']).hex())
    for item in inputs['varints']['decode']:
        capture(item['name'], lambda item=item: sequences.decode_source_event_seqs(bytes.fromhex(item['hex']), item['seq']))
    for index, data in enumerate(inputs['compression']):
        def bind(index=index, data=data):
            bound = compression.bind_record(dict(seq=index, time=index, type='custom/event', data=data))
            return dict(seq=bound['seq'], time=bound['time'], type=bound['type'], isPacked=bound['is_packed'],
                        data=dict(text=bound['data']) if isinstance(bound['data'], str) else dict(hex=bound['data'].hex()),
                        decoded=compression.decode_row(bound))
        capture('bind-' + str(index), bind)
    for item in frames:
        capture(item['name'], lambda item=item: zstd.decompress(bytes.fromhex(item['hex']), item.get('maxOutputLength')).hex())
    start = compression.bind_record(dict(type='turn/start', seq=0, time=1, data=dict(turn=1)))
    end = compression.bind_record(dict(type='turn/end', seq=2, time=3, data=dict(turn=1, reason=dict(kind='completed'))))
    invalid = dict(start, seq=1, data='{not json')
    gap = dict(start, seq=2)
    capture('scan-empty', lambda: compression.scan_rows([]))
    capture('scan-valid', lambda: compression.scan_rows([start]))
    capture('scan-invalid-tail', lambda: compression.scan_rows([start, invalid]))
    capture('scan-invalid-committed', lambda: compression.scan_rows([start, invalid, end]))
    capture('scan-gap-tail', lambda: compression.scan_rows([start, gap]))
    capture('scan-gap-committed', lambda: compression.scan_rows([start, gap, dict(end, seq=3)]))
    capture('scan-nonzero-base', lambda: compression.scan_rows([dict(start, seq=100)], 100))
    capture('packed-unknown-tag', lambda: compression.decode_row(dict(start, is_packed=1)))
    capture('packed-surface-refusal', lambda: compression.decode_row(dict(start, type='text-chunks', is_packed=1, source_event_seqs=b'')))
    capture('serialized-byte-limit', lambda: codec.decode_serialized_chunk_row('text-chunks', 0, 0, ' ' * 1048577))
    capture('serialized-surrogate-byte-limit', lambda: codec.decode_serialized_chunk_row('text-chunks', 0, 0, '\ud800' * 349526))
    directory, _ = zstd.verify_zstd_files()
    assets = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(directory.iterdir()) if path.is_file()}
    return dict(root=str(root), python=platform.python_version(), moduleFile=str(Path(codec.__file__).resolve()),
                modules={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in MODULES},
                assets=assets, libraryFile=str(Path(zstd.library()._name).resolve()),
                zstdVersion=zstd.library().ZSTD_versionString().decode('ascii'),
                frameInputsSha256=hashlib.sha256(json.dumps(frames, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest(), rows=rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    report = observe(root, json.loads(args.inputs.read_text(encoding='utf-8')), json.loads(args.source.read_text(encoding='utf-8'))['frames'])
    from dsh.cordis.json_text import stringify_json
    args.output.write_text(stringify_json(report) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
