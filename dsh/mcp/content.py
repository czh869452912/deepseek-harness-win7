import base64
import inspect

from dsh.cordis.utils import _UNDEFINED, js_to_string
from dsh.attachment.error import is_image_admission_error


def error_string(error):
    if isinstance(error, BaseException):
        return '%s: %s' % (getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error'),
            getattr(error, 'message', str(error)))
    return js_to_string(error)


def project_content(content, tool_name, image=None):
    projected, text = [], []
    def flush():
        if text:
            projected.append({'type': 'text', 'text': '\n'.join(text)})
            text.clear()
    for index, block in enumerate(content):
        if not isinstance(block, dict):
            text.append('[unsupported MCP content block: expected an object]')
            continue
        kind = block.get('type', _UNDEFINED)
        if kind == 'text':
            if 'text' in block:
                text.append('' if block['text'] is None else js_to_string(block['text']))
        elif kind == 'image':
            flush()
            projected.append(image(block, index) if image is not None else {
                'type': 'text', 'text': image_diagnostic(block, 'this result was not admitted to durable model context')})
        elif kind == 'resource_link':
            if 'name' not in block or 'uri' not in block:
                text.append('[resource link unavailable: the MCP block is missing its name or URI]')
            else:
                text.append('Resource link: %s (%s)' % (js_to_string(block['name']), js_to_string(block['uri'])))
        elif kind == 'audio':
            media_type = block.get('mimeType')
            text.append('[audio result unsupported: %s; raw audio data remains available to programmatic callers]' %
                js_to_string('unknown media type' if media_type is None else media_type))
        elif kind == 'resource':
            text.append('[embedded resource unsupported; raw resource data remains available to programmatic callers]')
        else:
            text.append('[unsupported MCP content type: %s]' % js_to_string(kind))
    flush()
    return projected or [{'type': 'text', 'text': '(%s returned no model-visible content)' % tool_name}]


def image_diagnostic(block, reason):
    media_type = block.get('mimeType')
    return '[image unavailable: %s; %s; raw image data remains available to programmatic callers]' % (
        js_to_string('unknown media type' if media_type is None else media_type), reason)


def extract_text(mcp_content, tool_name):
    return '\n'.join(block['text'] for block in project_content(mcp_content, tool_name))


def _get(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


async def _resolve_admission(ctx, execution):
    attachments = ctx.get('attachments')
    if attachments is None:
        raise RuntimeError('no attachment store is mounted')
    agent = _get(execution, 'agent')
    session = _get(agent, 'session')
    header_method = _get(session, 'request_header', _get(session, 'requestHeader'))
    header = header_method() if header_method is not None else None
    route = _get(header, 'config')
    options = _get(agent, 'options')
    provider, model = _get(route, 'provider'), _get(route, 'model')
    if provider is None:
        provider = _get(options, 'provider')
    if model is None:
        model = _get(options, 'model')
    llm = ctx.get('llm')
    if provider is None or model is None or llm is None:
        raise RuntimeError('the current model route could not be resolved')
    signal = _get(execution, 'signal')
    try:
        resolver = _get(llm, 'resolve_model_info', _get(llm, 'resolveModelInfo'))
        info = resolver(provider, model, signal)
        if inspect.isawaitable(info):
            info = await info
    except Exception:
        raise RuntimeError('the current model route could not be verified')
    modalities = _get(info, 'inputModalities')
    if modalities is None or 'image' not in modalities:
        raise RuntimeError('model "%s" does not declare image input' % model)
    if _get(signal, 'aborted', False):
        raise RuntimeError('the tool call was canceled before image storage')
    return attachments


def _decode_image(block):
    media_type = block.get('mimeType')
    if media_type not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
        raise ValueError('the declared media type is not PNG, JPEG, WebP, or GIF')
    encoded = block.get('data')
    try:
        if not isinstance(encoded, str):
            raise ValueError()
        data = base64.b64decode(encoded, validate=True)
        if base64.b64encode(data).decode('ascii') != encoded:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('the image data is not canonical base64')
    return {'data': data, 'mediaType': media_type}


async def prepare_image_projection(ctx, execution, content, tool_name):
    decoded, invalid, indexes = [], {}, []
    for index, block in enumerate(content):
        if not isinstance(block, dict) or block.get('type') != 'image':
            continue
        indexes.append(index)
        try:
            decoded.append(_decode_image(block))
        except ValueError as error:
            invalid[index] = str(error)
    def refusal(reason):
        return project_content(content, tool_name, lambda block, index: {
            'type': 'text', 'text': image_diagnostic(block, reason)})
    if invalid:
        return project_content(content, tool_name, lambda block, index: {
            'type': 'text', 'text': image_diagnostic(block, invalid.get(index, 'another image in the same result was invalid'))})
    try:
        attachments = await _resolve_admission(ctx, execution)
    except Exception as error:
        return refusal(str(error))
    try:
        save = _get(attachments, 'save_images', _get(attachments, 'saveImages'))
        refs = save(decoded)
        if inspect.isawaitable(refs):
            refs = await refs
        images = dict(zip(indexes, refs))
        return project_content(content, tool_name, lambda block, index: {'type': 'image', 'attachment': images[index]})
    except Exception as error:
        reason = ('image admission rejected the result: ' + _get(error, 'message', str(error))
            if is_image_admission_error(error) else 'durable image storage rejected the result')
        return refusal(reason)
