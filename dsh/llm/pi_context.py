"""Harness history to pi-ai context, retaining durable image and replay ownership."""
import asyncio
import base64
import functools

from dsh.llm.image_content import handle, images, offload
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_replay import to_pi_assistant


def _text(blocks):
    return ''.join(block['text'] for block in blocks if block['type'] == 'text')


def _result_text(blocks):
    return ''.join(block['text'] if block['type'] == 'text' else
                   _result_text(block['content']) if block['type'] == 'tool-result' else ''
                   for block in blocks)


def _user_content(blocks, versions, access):
    content = []
    for block in blocks:
        kind = block['type']
        if kind == 'text' and block['text']:
            content.append(dict(type='text', text=block['text']))
        elif kind == 'image':
            ref = block['attachment']
            version = versions[ref['attachmentId']]
            content.extend([dict(type='text', text=handle(ref, version, access(ref))),
                            dict(type='image', data=base64.b64encode(version['data']).decode('ascii'),
                                 mimeType=version['mediaType'])])
        elif kind == 'tool-result':
            nested = _user_content(block['content'], versions, access)
            if isinstance(nested, str):
                if nested:
                    content.append(dict(type='text', text=nested))
            else:
                content.extend(nested)
    return _text(content) if all(block['type'] == 'text' for block in content) else content


def _convert(options, history, versions=None, access=None, on_degrade=None):
    messages, tool_names = [], {}
    for message in history:
        blocks = message['content']
        if versions is None and any(images(blocks)):
            raise LlmError('pi-ai image conversion requires the durable attachment service', 'UNSUPPORTED_CONTENT')
        if message['role'] == 'system':
            messages.append(dict(role='user', content=_text(blocks), timestamp=0))
        elif message['role'] == 'assistant':
            assistant = to_pi_assistant(message, on_degrade)
            tool_names.update({block['id']: block['name'] for block in assistant['content'] if block['type'] == 'toolCall'})
            messages.append(assistant)
        else:
            results = [block for block in blocks if block['type'] == 'tool-result']
            content = (_text(blocks) if versions is None else
                       _user_content([block for block in blocks if block['type'] != 'tool-result'], versions, access))
            if content or not results:
                messages.append(dict(role='user', content=content, timestamp=0))
            for result in results:
                content = (_result_text(result['content']) if versions is None else
                           _user_content(result['content'], versions, access))
                if isinstance(content, str):
                    content = [dict(type='text', text=content or '(no output)')]
                messages.append(dict(role='toolResult', toolCallId=result['toolCallId'],
                    toolName=tool_names.get(result['toolCallId'], 'unknown'), content=content,
                    isError=result.get('isError', False), timestamp=0))
    context = dict(messages=messages)
    if 'system' in options:
        context['systemPrompt'] = options['system']
    if options.get('tools'):
        context['tools'] = [{key: tool[key] for key in ('name', 'description', 'parameters')} for tool in options['tools']]
    return context


def to_pi_context(options, on_degrade=None):
    return _convert(options, options['messages'], on_degrade=on_degrade)


async def to_pi_context_with_images(options, attachments, resolve_image_access,
                                    max_request_image_bytes=None, request_image_policy=None, on_degrade=None):
    policy = request_image_policy if request_image_policy is not None else dict(maxPixels=2048 * 2048, maxBytes=1024 * 1024)
    history = options['messages']
    # Reject roles before offloading: a tiny budget must never conceal unsupported input.
    for message in history:
        if message['role'] != 'user' and any(images(message['content'])):
            raise LlmError('pi-ai cannot represent an image in an in-history {} message'.format(message['role']), 'UNSUPPORTED_CONTENT')
    limit = float('inf') if max_request_image_bytes is None else max_request_image_bytes

    def project(messages, length):
        return offload(messages, limit, float('inf'), 1, 1, length, base64=True, access=resolve_image_access)

    history = project(history, lambda ref: min(ref['bytes'], policy['maxBytes']))
    refs = {block['attachment']['attachmentId']: block['attachment'] for message in history for block in images(message['content'])}
    loop = asyncio.get_running_loop()
    versions = await asyncio.gather(*(loop.run_in_executor(None,
        functools.partial(attachments.read_image_request, ref, policy, options.get('signal'))) for ref in refs.values()))
    versions = dict(zip(refs, versions))
    history = project(history, lambda ref: versions[ref['attachmentId']]['bytes'])
    return _convert(options, history, versions, resolve_image_access, on_degrade)
