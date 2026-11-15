"""Current typed image admission over the asynchronous attachment store."""
import os

from dsh.attachment.error import AttachmentError
from dsh.cordis.text import trim_js
from dsh.core.tools import ToolArgsError, ToolContextUnavailableError
from dsh.jobs.pump import field
from dsh.llm.error import HarnessError
from .fs_local import FsError
from .patch_executor import resolve_options
from .tool_read_image import (image_media_type_for_path, sniff_image_media_type,
    image_ref_from_value, image_read_content, IMAGE_EXTENSIONS)


class ImageInputError(HarnessError): pass


async def assert_image_capable_route(ctx, execution, path):
    agent = field(execution, 'agent'); session = field(agent, 'session')
    header = session.requestHeader() if session is not None else None
    route = field(header, 'config') or {};options = field(agent, 'options') or {}
    provider = field(route, 'provider') if field(route, 'provider') is not None else field(options, 'provider')
    model = field(route, 'model') if field(route, 'model') is not None else field(options, 'model')
    llm = ctx.get('llm')
    if provider is None or model is None or llm is None:
        raise ToolContextUnavailableError('cannot read "'+path+'" as an image: the current model route could not be resolved')
    active = await llm.resolveModelInfo(provider, model, execution.signal)
    if 'image' not in (field(active, 'inputModalities') or []):
        raise ImageInputError('cannot read "'+path+'" as an image: model "'+model+'" does not declare image input; switch to an image-capable model to read images', 'IMAGE_UNSUPPORTED_MODEL')


def assert_deployment_accepts(attachments, media_type, path):
    if media_type not in attachments.imageLimits['mediaTypes']:
        raise ImageInputError('cannot read "'+path+'": '+media_type+' images are not accepted by this deployment', 'IMAGE_UNSUPPORTED_FORMAT')


def save_failure(error, attachments, facts):
    if not isinstance(error, AttachmentError): return error
    code = error.code;limits = attachments.imageLimits;media_type = facts['mediaType']
    detail = None
    if code == 'IMAGE_DIMENSION_TOO_LARGE': detail = 'at least one image side exceeds the '+str(limits['maxImageDimension'])+'px limit; downscale the image and read the smaller copy'
    elif code == 'IMAGE_TOO_MANY_PIXELS': detail = 'the image exceeds the '+str(limits['maxImagePixels'])+'-pixel decoded-size limit; downscale the image and read the smaller copy'
    elif code in ('IMAGE_TOO_LARGE', 'IMAGES_TOO_LARGE'): detail = "the image cannot be stored within the deployment's byte limits; downscale the image and read the smaller copy"
    elif code == 'UNSUPPORTED_IMAGE_TYPE': detail = media_type+' images are not accepted by this deployment'
    elif code == 'INVALID_IMAGE': detail = 'the bytes do not decode as a supported PNG/JPEG/WebP/GIF image; the file may be truncated or corrupt'
    elif code == 'IMAGE_TYPE_MISMATCH':
        detail = ('the file signature claims '+media_type+', but the bytes decode as a different image format; the file may be corrupt') if facts['sniffed'] else ('the '+facts['extension']+' extension declares '+media_type+', but the bytes use a different image format; rename the file to match its actual format if it is PNG/JPEG/WebP/GIF, or convert it to one of those formats')
    elif code == 'ATTACHMENT_WRITE_FAILED':
        if '16-bit png' in error.message.lower(): detail = 'the 16-bit PNG could not be converted to the normalized 8-bit sRGB form; convert it to an 8-bit PNG/JPEG/WebP and retry'
    elif code not in ('TOO_MANY_IMAGES','INVALID_IMAGE_BASE64','INVALID_FILE_BASE64','INVALID_ATTACHMENT_REF','ATTACHMENT_CORRUPT','ATTACHMENT_NOT_FOUND','ATTACHMENT_READ_FAILED','ATTACHMENT_PROJECTION_UNSUPPORTED','ATTACHMENT_FILES_UNSUPPORTED'):
        raise RuntimeError('unreachable variant in AttachmentErrorCode: '+code)
    return error if detail is None else AttachmentError('cannot read "'+facts['displayPath']+'": '+detail, code, error)


def apply_read_image_tool(ctx):
    async def execute(arguments, execution):
        path = arguments['file_path']
        if not trim_js(path): raise ToolArgsError('read_image', ['file_path must be a non-empty string'])
        extension = os.path.splitext(path)[1].lower();declared = image_media_type_for_path(path)
        if declared is None and extension:
            raise ImageInputError('cannot read "'+path+'": the '+extension+' extension does not declare a supported image format; read_image accepts PNG/JPEG/WebP/GIF files, including extension-less files in those formats', 'IMAGE_UNSUPPORTED_FORMAT')
        attachments = ctx.get('attachments')
        if attachments is None: raise ToolContextUnavailableError('cannot read "'+path+'" as an image: no attachment service is mounted')
        if declared is not None: assert_deployment_accepts(attachments, declared, path)
        await assert_image_capable_route(ctx, execution, path)
        target = await ctx.fs.resolve(path, await resolve_options(ctx, execution))
        info = await ctx.fs.stat(target, execution.signal)
        if info is None:
            ctx.emit('fs/observed', target, dict(kind='absent'), execution)
            raise FsError('cannot read "'+target.displayPath+'": not found', 'FS_NOT_FOUND')
        if info.type != 'file': raise FsError('cannot read "'+target.displayPath+'": not a regular file', 'FS_NOT_REGULAR_FILE')
        cap = min(attachments.imageLimits['maxImageBytes'], attachments.imageLimits['maxMessageImageBytes'])
        data = await ctx.fs.readBytes(target, execution.signal, cap)
        media_type = declared if declared is not None else sniff_image_media_type(data)
        if media_type is None:
            raise ImageInputError('cannot read "'+target.displayPath+'": the file content is not a supported image format; read_image accepts PNG/JPEG/WebP/GIF', 'IMAGE_UNSUPPORTED_FORMAT')
        if declared is None: assert_deployment_accepts(attachments, media_type, target.displayPath)
        try: reference = await attachments.saveImage(dict(data=data, mediaType=media_type, name=os.path.basename(target.displayPath)))
        except Exception as error: raise save_failure(error, attachments, dict(displayPath=target.displayPath, extension=extension, mediaType=media_type, sniffed=declared is None))
        ctx.emit('fs/observed', target, dict(kind='present', version=info.version), execution)
        return dict(path=ctx.fs.processPath(target), image=image_ref_from_value(reference))

    image_schema = dict(type='object', additionalProperties=False,
        properties=dict(attachmentId=dict(type='string'), mediaType=dict(type='string', enum=list(dict.fromkeys(IMAGE_EXTENSIONS.values()))),
            bytes=dict(type='integer'), width=dict(type='integer'), height=dict(type='integer'), name=dict(type='string'),
            originalDimensions=dict(type='object', additionalProperties=False, properties=dict(width=dict(type='integer'), height=dict(type='integer')), required=['width','height'])),
        required=['attachmentId','mediaType','bytes','width','height'])
    ctx.tools.register(dict(name='read_image',description='Read a PNG/JPEG/WebP/GIF file and return the image itself. Large images are downscaled automatically; do not install image libraries or create thumbnails to inspect an image.',
        parameters=dict(type='object',properties=dict(file_path=dict(type='string',description='Path to the image file, resolved by the filesystem backend.')),required=['file_path']),
        output=dict(schema=dict(type='object',additionalProperties=False,properties=dict(path=dict(type='string',description='Canonical absolute path in the filesystem execution world.'),image=image_schema),required=['path','image']),
            render=lambda args,value:image_read_content(value),presentationMeta=lambda args,value:dict(path=value['path'])),
        isConcurrencySafe=lambda *_:True,execute=execute,presentCall=lambda args:dict(card='generic',title='Read image '+args['file_path'],kind='read',locations=[dict(path=args['file_path'])])))
