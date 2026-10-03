import base64
import binascii
import json
import re

from dsh.attachment.error import is_image_admission_error
from dsh.core.abort import AbortController, abort_reason_error
from dsh.acp.model_control import resolved

IMAGE_MEDIA_TYPES = ('image/png', 'image/jpeg', 'image/webp', 'image/gif')
CANONICAL_BASE64 = re.compile(r'^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$')


class AcpContentError(Exception):
    def __init__(self, message, kind='invalid'):
        super().__init__(message)
        self.message = message
        self.kind = kind


def check_signal(signal):
    if signal is not None and signal.aborted:
        raise abort_reason_error(signal, 'ACP content admission cancelled')


async def supports_acp_image_prompts(ctx, provider=None, model=None):
    attachments, llm = ctx.get('attachments'), ctx.get('llm')
    if attachments is None or llm is None or provider is None or model is None:
        return False
    if not any(media_type in IMAGE_MEDIA_TYPES for media_type in attachments.image_limits['mediaTypes']):
        return False
    try:
        info = await resolved(llm.resolve_model_info(provider, model))
        return 'image' in info.get('inputModalities', [])
    except Exception:
        return False


def decode_image(block):
    media_type = block.get('mimeType')
    if media_type not in IMAGE_MEDIA_TYPES:
        raise AcpContentError('image mimeType must be image/png, image/jpeg, image/webp, or image/gif')
    data = block.get('data')
    if not isinstance(data, str) or CANONICAL_BASE64.fullmatch(data) is None:
        raise AcpContentError('image data must be canonical base64')
    try:
        decoded = base64.b64decode(data, validate=True)
    except (ValueError, TypeError, binascii.Error) as error:
        raise AcpContentError('image data must be canonical base64') from error
    if base64.b64encode(decoded).decode('ascii') != data:
        raise AcpContentError('image data must be canonical base64')
    return {'data': decoded, 'mediaType': media_type}


async def admit_acp_prompt(ctx, route, prompt, image_enabled=False, signal=None):
    signal = signal if signal is not None else AbortController().signal
    images = []
    for block in prompt:
        block_type = block.get('type') if isinstance(block, dict) else None
        if block_type in ('text', 'resource_link'):
            continue
        if block_type == 'image':
            if not image_enabled:
                raise AcpContentError('inline image prompts were not advertised by this connection')
            images.append(decode_image(block))
        elif block_type == 'audio':
            raise AcpContentError('audio prompt content is not supported')
        elif block_type == 'resource':
            raise AcpContentError('embedded resource prompt content is not supported')
        else:
            raise AcpContentError('unsupported ACP prompt content')
    refs = []
    if images:
        attachments = ctx.get('attachments')
        if attachments is None:
            raise AcpContentError('no attachment store is mounted')
        llm = ctx.get('llm')
        if route is None or llm is None:
            raise AcpContentError('the current model route could not be resolved for image input')
        try:
            info = await resolved(llm.resolve_model_info(route.provider, route.model, signal))
        except Exception as error:
            raise AcpContentError('the current model route could not be verified for image input', 'internal') from error
        if 'image' not in info.get('inputModalities', []):
            raise AcpContentError('model "%s" does not declare image input' % route.model)
        check_signal(signal)
        try:
            refs = await resolved(attachments.save_images(images))
        except Exception as error:
            if is_image_admission_error(error):
                raise AcpContentError(getattr(error, 'message', str(error))) from error
            raise AcpContentError('unable to persist the prompt image batch', 'internal') from error
        check_signal(signal)
    content, pending_text, image_index = [], '', 0
    for block in prompt:
        if block['type'] == 'text':
            pending_text += block['text']
        elif block['type'] == 'resource_link':
            pending_text += '\n[resource_link name=%s uri=%s]\n' % (
                json.dumps(block['name'], ensure_ascii=False, separators=(',', ':')),
                json.dumps(block['uri'], ensure_ascii=False, separators=(',', ':')))
        elif block['type'] == 'image':
            if pending_text:
                content.append({'type': 'text', 'text': pending_text})
                pending_text = ''
            content.append({'type': 'image', 'attachment': refs[image_index]})
            image_index += 1
    if pending_text:
        content.append({'type': 'text', 'text': pending_text})
    if not any(item['type'] == 'image' or item['text'].strip() for item in content):
        raise AcpContentError('empty prompt')
    return content


async def assistant_block_to_acp(ctx, block):
    if block['type'] == 'text':
        return {'type': 'text', 'text': block['text']} if block['text'] else None
    if block['type'] != 'image':
        return None
    attachments = ctx.get('attachments')
    if attachments is None:
        raise AcpContentError('cannot deliver assistant image: no attachment store is mounted', 'internal')
    try:
        stored = await resolved(attachments.read_image(block['attachment']))
    except Exception as error:
        raise AcpContentError('cannot deliver assistant image: the attachment is unavailable or corrupt', 'internal') from error
    return {'type': 'image', 'data': base64.b64encode(stored['data']).decode('ascii'), 'mimeType': stored['ref']['mediaType']}
