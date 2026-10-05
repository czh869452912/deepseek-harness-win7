from dsh.session.jsonl_zstd import decompress_frame, scan_frames


def read_jsonl_text(path):
    if path.suffix == '.jsonl':
        return path.read_text(encoding='utf-8')
    buffer = path.read_bytes()
    scanned = scan_frames(buffer)
    assert 'tornStart' not in scanned and scanned['frames']
    return b''.join(decompress_frame(buffer[frame['start']:frame['end']]) for frame in scanned['frames']).decode('utf-8')
