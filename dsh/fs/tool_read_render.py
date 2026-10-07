import math

from dsh.cordis.utils import js_to_string
from dsh.fs.fs_local import FsError


READ_MAX_LINE_LENGTH = 2000
READ_MAX_BYTES = 50 * 1024
LANG_BY_EXTENSION = {
    'ts': 'ts', 'tsx': 'tsx', 'mts': 'ts', 'cts': 'ts',
    'js': 'js', 'jsx': 'jsx', 'mjs': 'js', 'cjs': 'js',
    'json': 'json', 'jsonc': 'json', 'py': 'py', 'rb': 'rb', 'go': 'go', 'rs': 'rs', 'java': 'java',
    'c': 'c', 'h': 'c', 'cc': 'cpp', 'cpp': 'cpp', 'hpp': 'cpp', 'cxx': 'cpp',
    'cs': 'cs', 'kt': 'kotlin', 'swift': 'swift', 'php': 'php',
    'sh': 'sh', 'bash': 'sh', 'zsh': 'sh', 'yaml': 'yaml', 'yml': 'yaml', 'toml': 'toml', 'ini': 'ini',
    'md': 'md', 'markdown': 'md', 'mdx': 'mdx', 'html': 'html', 'htm': 'html', 'css': 'css',
    'scss': 'scss', 'less': 'less', 'sql': 'sql', 'xml': 'xml', 'lua': 'lua',
}


def utf16_length(value):
    return len(value.encode('utf-16-le', 'surrogatepass')) // 2


def _slice_units(value, maximum):
    return value.encode('utf-16-le', 'surrogatepass')[:int(maximum) * 2].decode('utf-16-le', 'surrogatepass')


def _utf8_bytes(value):
    return len(value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8'))


async def _chunks(values):
    if hasattr(values, '__aiter__'):
        async for value in values:
            yield value
    else:
        for value in values:
            yield value


async def build_window(chunks, request, display_path):
    lines = []
    total_lines = 0
    output_bytes = 0
    truncated = False
    buffer = ''
    capacity = request['maxLineLength'] + 1

    def append(segment):
        nonlocal buffer
        if utf16_length(buffer) >= capacity:
            return
        buffer = _slice_units(buffer + segment, capacity)

    def flush():
        nonlocal buffer, total_lines, output_bytes, truncated
        raw = buffer[:-1] if buffer.endswith('\r') else buffer
        buffer = ''
        total_lines += 1
        if truncated or total_lines < request['offset'] or len(lines) >= request['limit']:
            return
        text = '%s... (line truncated to %s chars)' % (_slice_units(raw, request['maxLineLength']), js_to_string(request['maxLineLength'])) if utf16_length(raw) > request['maxLineLength'] else raw
        size = _utf8_bytes(text) + (1 if lines else 0)
        if output_bytes + size > request['maxBytes']:
            truncated = True
            return
        output_bytes += size
        lines.append(dict(number=total_lines, text=text))

    async for chunk in _chunks(chunks):
        start = 0
        while True:
            newline = chunk.find('\n', start)
            if newline < 0:
                break
            append(chunk[start:newline])
            flush()
            start = newline + 1
        append(chunk[start:])
    if utf16_length(buffer) > 0:
        flush()
    if not truncated and request['offset'] > total_lines and not (total_lines == 0 and request['offset'] == 1):
        raise FsError('offset %s is out of range for "%s" (%s lines)' % (js_to_string(request['offset']), display_path, total_lines), 'FS_NOT_FOUND')
    return dict(lines=lines, totalLines=total_lines, truncatedByBytes=truncated)


def format_read_output(display_path, outcome):
    offset, lines, total = outcome['offset'], outcome['lines'], outcome['totalLines']
    end = lines[-1]['number'] if lines else max(0, offset - 1)
    if outcome.get('truncatedByBytes'):
        footer = '(Output capped. Showing lines %s-%s. Use offset=%s to continue.)' % tuple(js_to_string(value) for value in (offset, end, end + 1))
    elif end < total:
        footer = '(Showing lines %s-%s of %s. Use offset=%s to continue.)' % tuple(js_to_string(value) for value in (offset, end, total, end + 1))
    else:
        footer = '(End of file - total %s lines)' % js_to_string(total)
    body = '\n'.join('%s: %s' % (js_to_string(line['number']), line['text']) for line in lines) + '\n\n' + footer if lines else footer
    return '<path>%s</path>\n<type>file</type>\n<content>\n%s\n</content>' % (display_path, body)


def lang_from_path(path):
    base = path[max(path.rfind('/'), path.rfind('\\')) + 1:]
    dot = base.rfind('.')
    return LANG_BY_EXTENSION.get(base[dot + 1:].lower()) if dot > 0 else None


def _integer(value, minimum):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum and int(value) == value


def read_meta_from_meta(meta):
    if not isinstance(meta, dict):
        return None
    path, offset, lines, total = (meta.get(key) for key in ('path', 'offset', 'lines', 'totalLines'))
    if not isinstance(path, str) or not _integer(offset, 1) or not _integer(total, 0) or not isinstance(lines, list):
        return None
    if 'lang' in meta and not isinstance(meta['lang'], str):
        return None
    previous = offset - 1
    for line in lines:
        if not isinstance(line, dict) or not _integer(line.get('number'), 1) or not isinstance(line.get('text'), str):
            return None
        number = line['number']
        if number <= previous or number > total:
            return None
        previous = number
    result = dict(path=path, offset=offset, lines=lines, totalLines=total)
    if 'lang' in meta:
        result['lang'] = meta['lang']
    return result
