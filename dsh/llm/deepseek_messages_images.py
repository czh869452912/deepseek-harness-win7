"""Prepare retained images; request budgets require durable offload before retry."""
from dsh.llm.image_content_current import image_blocks, offloadedImageText, projectOffloadedImages, requiredImageOffload
from dsh.llm.deepseek_image_pricing_current import resolveRequestImageTarget, imagePricing
from dsh.llm.llm_service import LlmError


def _assert_fit(messages, versions, connection, representation):
    raw = representation == 'raw'
    budget = dict(representation=representation, maxBytes=connection['maxRequestFilesBytes' if raw else 'maxInlineRequestImageBytes'],
        maxImages=connection['maxImagesPerRequest'], byteQuantum=connection['imageOffloadByteQuantum' if raw else 'inlineImageOffloadByteQuantum'],
        countQuantum=connection['imageOffloadCountQuantum'])
    count = requiredImageOffload(messages, budget, lambda block: versions[block['attachment']['attachmentId']]['bytes'])
    if count:
        raise LlmError('DeepSeek Messages %s request images exceed the route budget; %s more oldest occurrence(s) must be offloaded.' % (representation, count),
            'IMAGE_OFFLOAD_REQUIRED', offloadImages=count)


async def prepareImages(history, connection, modelId, attachments, access, signal):
    versions = {}
    messages = projectOffloadedImages(history, lambda ref: offloadedImageText(ref, access(ref)))
    retained = list(image_blocks(messages))
    if not retained:
        return dict(messages=messages, versions=versions)
    model = next((entry for entry in connection['models'] if entry['id'] == modelId), {})
    if 'image' not in model.get('inputModalities', []) or attachments is None:
        raise LlmError('DeepSeek Messages image input requires a vision model and attachment service', 'UNSUPPORTED_CONTENT')
    if any(message['role'] not in ('user', 'tool') and any(block['type'] == 'image' for block in message['content']) for message in messages):
        raise LlmError('DeepSeek Messages supports images only in user messages and tool results', 'UNSUPPORTED_CONTENT')
    for block in retained:
        ref = block['attachment']
        if ref['attachmentId'] not in versions:
            versions[ref['attachmentId']] = await attachments.readImageRequest(ref, resolveRequestImageTarget(model, ref), signal)
    _assert_fit(messages, versions, connection, 'raw')
    return dict(messages=messages, versions=versions)


def inlineImages(messages, versions, connection):
    _assert_fit(messages, versions, connection, 'base64')
    return messages


async def prepareFileIds(messages, versions, files):
    ids = {}
    for index, message in enumerate(messages):
        image = 0
        for block in message['content']:
            if block['type'] != 'image':
                continue
            image += 1
            ref = block['attachment']
            ids[ref['attachmentId']] = await files.resolve(versions[ref['attachmentId']], dict(message=index+1, image=image))
    return ids
