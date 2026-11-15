import copy
from decimal import Decimal, ROUND_HALF_UP
import inspect
import os
from typing import Any, Dict, List, Optional

from dsh.attachment.error import AttachmentError
from dsh.fs.fs_local import FsError
from dsh.fs.tool_fs import _observation_target


IMAGE_EXTENSIONS = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.gif': 'image/gif'}


class ImageReadError(ValueError):
    name = 'Error'


def image_media_type_for_path(file_path: str) -> Optional[str]:
    return IMAGE_EXTENSIONS.get(os.path.splitext(file_path)[1].lower())


def sniff_image_media_type(data: bytes) -> Optional[str]:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


async def assert_image_capable_route(ctx: Any, execution: Any, requested_path: str) -> None:
    agent = getattr(execution, 'agent', None)
    session = getattr(agent, 'session', None)
    header = session.requestHeader() if session is not None else None
    routed = header.get('config', {}) if header is not None else {}
    options = getattr(agent, 'options', {})
    provider = routed.get('provider')
    model = routed.get('model')
    if provider is None:
        provider = options.get('provider')
    if model is None:
        model = options.get('model')
    llm = ctx.get('llm')
    if provider is None or model is None or llm is None:
        raise ImageReadError('cannot read "%s" as an image: the current model route could not be resolved' % requested_path)
    active = await llm.resolve_model_info(provider, model, execution.signal)
    if 'image' not in active.get('inputModalities', []):
        raise ImageReadError('cannot read "%s" as an image: model "%s" does not declare image input; switch to an image-capable model to read images' % (requested_path, model))


def image_ref_from_value(image: Dict[str, Any]) -> Dict[str, Any]:
    return {name: copy.deepcopy(image[name]) for name in ('attachmentId', 'mediaType', 'bytes',
        'width', 'height', 'name', 'originalDimensions') if name in image}


def format_image_read_output(display_path: str, image: Dict[str, Any]) -> str:
    scaled = ''
    if 'originalDimensions' in image:
        original = image['originalDimensions']
        horizontal = str(Decimal.from_float(original['width'] / image['width']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        vertical = str(Decimal.from_float(original['height'] / image['height']).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        advice = 'multiply coordinates by ' + horizontal if horizontal == vertical else 'multiply x coordinates by %s and y coordinates by %s' % (horizontal, vertical)
        scaled = ' (downscaled from %sx%s px; %s to locate features in the original file)' % (original['width'], original['height'], advice)
    return '<path>%s</path>\n<type>image</type>\n<content>\n%s image, %sx%s px, %s bytes%s\n</content>' % (
        display_path, image['mediaType'], image['width'], image['height'], image['bytes'], scaled)


def image_read_content(value: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(type='text', text=format_image_read_output(value['path'], value['image'])),
        dict(type='image', attachment=image_ref_from_value(value['image']))]


def apply_read_image_tool(ctx: Any, current: bool = False, directory_aware=False) -> None:
    async def execute(arguments: Dict[str, Any], execution: Any) -> Dict[str, Any]:
        requested_path = arguments['file_path']
        if not requested_path.strip():
            raise ImageReadError('file_path must be a non-empty string')
        extension = os.path.splitext(requested_path)[1].lower()
        declared = image_media_type_for_path(requested_path)
        if declared is None and extension:
            raise ImageReadError('cannot read "%s": the %s extension does not declare a supported image format; read_image accepts PNG/JPEG/WebP/GIF files, including extension-less files in those formats' % (requested_path, extension))
        attachments = ctx.get('attachments')
        if attachments is None:
            raise ImageReadError('cannot read "%s" as an image: no attachment service is mounted' % requested_path)
        limits = attachments.image_limits
        if declared is not None and declared not in limits['mediaTypes']:
            raise ImageReadError('cannot read "%s": %s images are not accepted by this deployment' % (requested_path, declared))
        await assert_image_capable_route(ctx, execution, requested_path)
        filesystem = ctx.get('fs')
        target = await _observation_target(filesystem, requested_path, execution,
            directories=ctx.get('workingDirectory') if directory_aware else None)
        information = await filesystem.stat(target, execution.signal)
        if information is None:
            ctx.emit('fs/observed', target, dict(kind='absent'), execution)
            raise FsError('cannot read "%s": not found' % target.displayPath, 'FS_NOT_FOUND')
        if information.type != 'file':
            raise FsError('cannot read "%s": not a regular file' % target.displayPath, 'FS_NOT_REGULAR_FILE')
        byte_cap = min(limits['maxImageBytes'], limits['maxMessageImageBytes'])
        data = await filesystem.readBytes(target, execution.signal, byte_cap)
        media_type = declared if declared is not None else sniff_image_media_type(data)
        if media_type is None:
            raise ImageReadError('cannot read "%s": the file content is not a supported image format; read_image accepts PNG/JPEG/WebP/GIF' % target.displayPath)
        if declared is None and media_type not in limits['mediaTypes']:
            raise ImageReadError('cannot read "%s": %s images are not accepted by this deployment' % (target.displayPath, media_type))
        try:
            reference = attachments.save_image(dict(data=data, mediaType=media_type, name=os.path.basename(target.displayPath)))
            if inspect.isawaitable(reference):
                reference = await reference
        except AttachmentError as failure:
            messages = {
                'IMAGE_DIMENSION_TOO_LARGE': 'at least one image side exceeds the %spx limit; downscale the image and read the smaller copy' % limits['maxImageDimension'],
                'IMAGE_TOO_MANY_PIXELS': 'the image exceeds the %s-pixel decoded-size limit; downscale the image and read the smaller copy' % limits['maxImagePixels'],
                'IMAGE_TOO_LARGE': "the image cannot be stored within the deployment's byte limits; downscale the image and read the smaller copy",
            }
            message = messages.get(failure.code)
            if failure.code == 'ATTACHMENT_WRITE_FAILED' and '16-bit png' in str(failure).lower():
                message = 'the 16-bit PNG could not be converted to the normalized 8-bit sRGB form; convert it to an 8-bit PNG/JPEG/WebP and retry'
            if failure.code == 'INVALID_IMAGE' and declared is None:
                message = 'the bytes do not decode as a supported PNG/JPEG/WebP/GIF image; the file may be truncated or corrupt'
            if failure.code == 'IMAGE_TYPE_MISMATCH':
                if declared is None:
                    message = 'the file signature claims %s, but the bytes decode as a different image format; the file may be corrupt' % media_type
                else:
                    message = 'the %s extension declares %s, but the bytes use a different image format; rename the file to match its actual format if it is PNG/JPEG/WebP/GIF, or convert it to one of those formats' % (extension, media_type)
            if message is None:
                raise
            error = ImageReadError('cannot read "%s": %s' % (target.displayPath, message))
            error.cause = failure
            raise error from failure
        ctx.emit('fs/observed', target, dict(kind='present', version=information.version), execution)
        return dict(path=target.displayPath, image=image_ref_from_value(reference))

    image_schema = dict(type='object', additionalProperties=False,
        properties=dict(attachmentId=dict(type='string'), mediaType=dict(type='string', enum=list(dict.fromkeys(IMAGE_EXTENSIONS.values()))),
            bytes=dict(type='integer'), width=dict(type='integer'), height=dict(type='integer'), name=dict(type='string'),
            originalDimensions=dict(type='object', additionalProperties=False, properties=dict(width=dict(type='integer'), height=dict(type='integer')),
                required=['width', 'height'])), required=['attachmentId', 'mediaType', 'bytes', 'width', 'height'])
    ctx.get('tools').register(dict(name='read_image',
        description='Read a PNG/JPEG/WebP/GIF file and return the image itself. A path without a file extension is accepted; the format is detected from the file content, so normalized attachment paths can be passed directly without copying or renaming. Harness validates and downscales large supported images before the next model request, so use this tool directly instead of installing image libraries or creating thumbnails merely to inspect an image. Independent files may be read concurrently in small batches. Requires the current model to accept image input.',
        parameters=dict(type='object', properties=dict(file_path=dict(type='string', description='Path to the image file, resolved by the filesystem backend.')), required=['file_path']),
        output=dict(schema=dict(type='object', additionalProperties=False, properties=dict(path=dict(type='string'), image=image_schema), required=['path', 'image']),
            render=lambda arguments, value: image_read_content(value),
            **(dict(presentationMeta=lambda arguments, value: dict(path=value['path'])) if current else {})),
        isConcurrencySafe=lambda execution: True, execute=execute,
        presentCall=lambda arguments: dict(card='generic', title='Read image ' + arguments['file_path'], kind='read', locations=[dict(path=arguments['file_path'])])))
