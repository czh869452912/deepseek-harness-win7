import re

from dsh.cordis.utils import _UNDEFINED, js_to_string
from dsh.fs.fs_local import FsError
from dsh.fs.tool_read_render import _integer, build_window, format_read_output, lang_from_path, read_meta_from_meta


def parse_read_args(arguments, maximum):
    if not arguments['file_path'].strip():
        raise ValueError('file_path must be a non-empty string')
    offset, limit = arguments.get('offset', 1), arguments.get('limit', maximum)
    for name, value in (('offset', offset), ('limit', limit)):
        if not _integer(value, 1):
            raise ValueError(name + ' must be a positive integer')
    if limit > maximum:
        raise ValueError('limit must be less than or equal to ' + js_to_string(maximum))
    return dict(filePath=arguments['file_path'], offset=offset, limit=limit)


def apply_read_tool(ctx, caps):
    ctx.get('systemPrompt').section(dict(name='tool:read', order=1100,
        text='Use the read tool — not shell commands like cat — to inspect text files. Results include line numbers. Use offset and limit to continue reading large files.'))

    async def execute(arguments, execution):
        from dsh.fs.tool_fs import _observation_target
        requested = parse_read_args(arguments, caps['limit'])
        filesystem = ctx.get('fs')
        target = await _observation_target(filesystem, requested['filePath'], execution)
        info = await filesystem.stat(target, execution.signal)
        if info is None:
            ctx.emit('fs/observed', target, dict(kind='absent'), execution)
            raise FsError('cannot read "%s": not found' % target.displayPath, 'FS_NOT_FOUND')
        if info.type != 'file':
            raise FsError('cannot read "%s": not a regular file' % target.displayPath, 'FS_NOT_REGULAR_FILE')
        if info.size is None or info.size >= caps['streamMinSize']:
            chunks = await filesystem.streamText(target, execution.signal)
        else:
            chunks = [await filesystem.readText(target, execution.signal)]
        window = await build_window(chunks, dict(offset=requested['offset'], limit=requested['limit'],
            maxLineLength=caps['maxLineLength'], maxBytes=caps['maxBytes']), target.displayPath)
        ctx.emit('fs/observed', target, dict(kind='present', version=info.version), execution)
        return dict(path=target.displayPath, offset=requested['offset'], lines=window['lines'], totalLines=window['totalLines'])

    def render(arguments, value):
        requested = parse_read_args(arguments, caps['limit'])
        end = value['lines'][-1]['number'] if value['lines'] else max(0, value['offset'] - 1)
        truncated = len(value['lines']) < requested['limit'] and end < value['totalLines']
        return [dict(type='text', text=format_read_output(value['path'], dict(offset=value['offset'], lines=value['lines'],
            totalLines=value['totalLines'], truncatedByBytes=truncated)))]

    def metadata(arguments, value):
        result = dict(path=value['path'], offset=value['offset'], lines=[dict(number=line['number'], text=line['text']) for line in value['lines']], totalLines=value['totalLines'])
        language = lang_from_path(value['path'])
        if language is not None:
            result['lang'] = language
        return result

    def present_result(arguments, result):
        if result.get('isError'):
            return None
        meta = read_meta_from_meta(result.get('meta'))
        content = result.get('content', [])
        only = content[0] if len(content) == 1 else {}
        if meta is None or only.get('type') != 'text':
            return None
        body = re.fullmatch(r'<path>[^\n]*</path>\n<type>file</type>\n<content>\n([\s\S]*)\n</content>', only['text'])
        if body is None:
            return None
        return dict(card='read', **meta, content=[dict(type='text', text=body.group(1))])

    def present_call(arguments):
        offset = arguments.get('offset', _UNDEFINED)
        limit = arguments.get('limit', _UNDEFINED)
        first = 1 if offset is _UNDEFINED or offset is None else offset
        window = ' (%s - %s)' % (js_to_string(first), js_to_string(first + limit - 1)) if limit is not _UNDEFINED and limit is not None and limit > 0 else ' (from line %s)' % js_to_string(offset) if offset is not _UNDEFINED else ''
        return dict(card='generic', title='Read ' + arguments['file_path'] + window, kind='read', locations=[dict(path=arguments['file_path'], line=first)])

    line_schema = dict(type='object', additionalProperties=False, properties=dict(number=dict(type='integer'), text=dict(type='string')), required=['number', 'text'])
    ctx.get('tools').register(dict(name='read', description='Read a UTF-8 text file and return line-numbered content.',
        parameters=dict(type='object', properties=dict(file_path=dict(type='string', description='Path to read, resolved by the filesystem backend.'),
            offset=dict(type='number', description='1-based first line to return. Defaults to 1.'),
            limit=dict(type='number', description='Maximum number of lines to return. Defaults to %s.' % js_to_string(caps['limit']))), required=['file_path']),
        output=dict(schema=dict(type='object', additionalProperties=False,
            properties=dict(path=dict(type='string'), offset=dict(type='integer'), lines=dict(type='array', items=line_schema), totalLines=dict(type='integer')),
            required=['path', 'offset', 'lines', 'totalLines']), render=render, presentationMeta=metadata),
        isConcurrencySafe=lambda execution: True, execute=execute, presentCall=present_call, presentResult=present_result))
