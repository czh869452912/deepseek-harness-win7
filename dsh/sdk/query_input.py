"""Desktop-style SDK input admission without command or attachment side effects."""
import re

from dsh.interaction.command_builtin import builtin_command_name, resolve_command, field

# ECMAScript WhiteSpace + LineTerminator; Python \s also admits extra C0 controls.
JS_SPACE = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def js_trim(value):
    return value.strip(JS_SPACE)


def query_command(text, commands):
    trimmed = js_trim(text)
    if not trimmed.startswith('/'):
        return None
    match = re.search('[' + JS_SPACE + ']', trimmed)
    separator = match.start() if match else -1
    name = trimmed[1:] if separator < 0 else trimmed[1:separator]
    descriptor = resolve_command(name, commands)
    if descriptor is None:
        return None
    builtin = builtin_command_name(descriptor)
    raw = '' if separator < 0 else trimmed[separator:]
    if raw and raw[0] not in ' \t\r\n':
        raw = ' ' + raw[1:]
    if builtin == 'compact' and separator < 0:
        return '/' + field(descriptor, 'name')
    if builtin == 'permission' and separator >= 0 or builtin in ('plan', 'goal'):
        return '/' + field(descriptor, 'name') + raw
    return None


def query_content(value):
    if not isinstance(value, list) or not value:
        raise TypeError('session/query requires a non-empty contentBlocks array')
    blocks = []
    for block in value:
        if not isinstance(block, dict) or not isinstance(block.get('type'), str):
            raise TypeError('SDK content blocks require a string type')
        kind = block['type']
        if kind == 'text':
            if not isinstance(block.get('text'), str) or set(block) - {'type', 'text'}:
                raise TypeError('SDK text blocks require only type and string text')
        if kind == 'image' and 'data' in block:
            if (not isinstance(block['data'], str) or block.get('mimeType') not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
                    or ('name' in block and not isinstance(block['name'], str)) or set(block) - {'type', 'data', 'mimeType', 'name'}):
                raise TypeError('SDK encoded images require string data, a supported mimeType and an optional string name')
        elif kind == 'image' and not isinstance(block.get('attachment'), dict):
            raise TypeError('SDK image blocks require encoded data or a durable attachment reference')
        blocks.append(dict(block))
    if all(block['type'] == 'text' and not js_trim(block['text']) for block in blocks):
        raise TypeError('session/query requires non-blank text or non-text content')
    return blocks


def query_command_images(blocks, text):
    images = []
    for block in blocks:
        if block is text:
            continue
        if block['type'] != 'image' or 'data' not in block:
            raise TypeError('Native SDK commands require one text block and optional encoded image blocks')
        images.append(block)
    return images
