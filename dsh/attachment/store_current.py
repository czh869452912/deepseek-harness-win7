"""Explicit rc.3 attachment capability, pending the coordinated profile switch."""
import base64
import binascii
import asyncio

from dsh.attachment.error import AttachmentError, IMAGE_ADMISSION_ERROR_CODES
from dsh.attachment.store import AttachmentStore
from dsh.attachment.local import LocalAttachmentStore
from dsh.attachment.immutable_current import check_abort, disk
from dsh.attachment.files_current import (
    read_file_stream_verbatim, save_file_stream_verbatim, save_file_verbatim, stored_file_path,
)

ATTACHMENT_ERROR_CODES = frozenset(IMAGE_ADMISSION_ERROR_CODES + (
    'INVALID_FILE_BASE64', 'INVALID_ATTACHMENT_REF', 'ATTACHMENT_CORRUPT',
    'ATTACHMENT_WRITE_FAILED', 'ATTACHMENT_NOT_FOUND', 'ATTACHMENT_READ_FAILED',
    'ATTACHMENT_PROJECTION_UNSUPPORTED', 'ATTACHMENT_FILES_UNSUPPORTED',
))


def is_attachment_error(error):
    code = getattr(error, 'code', None)
    return isinstance(error, Exception) and isinstance(code, str) and code in ATTACHMENT_ERROR_CODES


def decode_upload(data, image=False):
    code = 'INVALID_IMAGE_BASE64' if image else 'INVALID_FILE_BASE64'
    message = ('Image' if image else 'File') + ' upload is not canonical base64.'
    try:
        decoded = base64.b64decode(data, validate=True)
        if (image and not data) or base64.b64encode(decoded).decode('ascii') != data:
            raise ValueError('non-canonical base64')
        return decoded
    except (ValueError, TypeError, binascii.Error):
        raise AttachmentError(message, code) from None


class CurrentAttachmentAPI:
    @property
    def imageLimits(self):
        return self.image_limits

    async def validateImage(self, input_data):
        await disk(self.validate_image, input_data)

    async def saveImage(self, input_data):
        return await disk(self.save_image, input_data)

    async def saveImages(self, inputs):
        return await disk(self.save_images, inputs)

    async def admitPromptContent(self, content):
        images = [part for part in content if part['type'] == 'image' and 'attachment' not in part]
        stored = [part for part in content if part['type'] == 'image' and 'attachment' in part]
        if stored:
            if len(images) + len(stored) > self.imageLimits['maxImagesPerMessage']:
                raise AttachmentError('Image batch exceeds the configured image-count limit.', 'TOO_MANY_IMAGES')
            # Node's byteLength(base64) estimates length before canonical decoding.
            def encoded_length(part):
                value = part['data']
                padding = 2 if value.endswith('==') else 1 if value.endswith('=') else 0
                units = len(value.encode('utf-16-le', errors='surrogatepass')) // 2
                return max(0, (units - padding) * 3 // 4)
            if sum(encoded_length(part) for part in images) + sum(part['encodedBytes'] for part in stored) > self.imageLimits['maxMessageImageBytes']:
                raise AttachmentError('Image batch exceeds the configured aggregate image-byte limit.', 'IMAGES_TOO_LARGE')
        refs = iter(await self.admitEncodedImages(images)) if images else iter(())
        return [dict(type='text', text=part['text']) if part['type'] == 'text' else
                dict(type=part['type'], attachment=next(refs) if part['type'] == 'image' and 'attachment' not in part else part['attachment'])
                for part in content]

    async def admitEncodedImages(self, images):
        inputs = [dict(data=decode_upload(image['data'], image=True), mediaType=image['mediaType'],
                       **({'name': image['name']} if 'name' in image else {})) for image in images]
        return await self.saveImages(inputs)

    async def admitEncodedFile(self, input_data):
        return await self.saveFile(dict(data=decode_upload(input_data['data']),
            **({'name': input_data['name']} if 'name' in input_data else {})))

    isAttachmentError = staticmethod(is_attachment_error)

    def fileHostPath(self, ref):
        return None

    def imageHostPath(self, ref):
        return None

    async def readImage(self, ref, signal=None):
        check_abort(signal)
        value = await disk(self.read_image, ref, signal)
        check_abort(signal)
        return value

    async def readImageRequest(self, ref, policy, signal=None):
        check_abort(signal)
        raise AttachmentError('The mounted attachment provider cannot derive model-request images.', 'ATTACHMENT_PROJECTION_UNSUPPORTED')

    async def saveFile(self, input_data):
        raise AttachmentError('The mounted attachment provider cannot store verbatim files.', 'ATTACHMENT_FILES_UNSUPPORTED')

    async def saveFileStream(self, input_data):
        raise AttachmentError('The mounted attachment provider cannot stream verbatim files.', 'ATTACHMENT_FILES_UNSUPPORTED')

    async def readFileStream(self, ref, signal=None):
        check_abort(signal)
        raise AttachmentError('The mounted attachment provider cannot read verbatim files.', 'ATTACHMENT_FILES_UNSUPPORTED')
        yield  # The failure is deferred until iteration, as for an async generator.


class CurrentAttachmentStore(CurrentAttachmentAPI, AttachmentStore):
    pass


class CurrentLocalAttachmentStore(CurrentAttachmentAPI, LocalAttachmentStore):
    def __init__(self, ctx=None, config=None):
        from dsh.attachment.compression_current import CompressionLimiter
        from dsh.core.session.json import deep_freeze
        super().__init__(ctx, config)
        value = (config or {}).get('imageCompressionConcurrency', 2)
        if type(value) not in (int, float) or not 1 <= value <= 8 or int(value) != value:
            raise ValueError('attachment-local: imageCompressionConcurrency must be an integer from 1 through 8')
        self.imageCompressionConcurrency = int(value)
        self.compression = CompressionLimiter(int(value))
        self._request_inflight = {}
        self._image_limits = deep_freeze(self._image_limits)
        self.normalization_policy = deep_freeze(self.normalization_policy)

    @property
    def normalizationPolicy(self):
        return self.normalization_policy

    async def _prepare_image(self, input_data):
        from dsh.attachment.local import prepare_image_file
        return await self.compression.run(lambda: disk(prepare_image_file, input_data, self.image_limits, self.normalization_policy))

    async def validateImage(self, input_data):
        await self._prepare_image(input_data)

    async def saveImages(self, inputs):
        from dsh.attachment.images_current import commit_prepared_image
        self.validate_image_batch(inputs)
        prepared = await asyncio.gather(*(self._prepare_image(input_data) for input_data in inputs))
        refs = []
        for image in prepared:
            refs.append(await commit_prepared_image(self.root, image))
        return refs

    async def saveImage(self, input_data):
        from dsh.attachment.images_current import commit_prepared_image
        return await commit_prepared_image(self.root, await self._prepare_image(input_data))

    async def readImageRequest(self, ref, policy, signal=None):
        from dsh.attachment.compression_current import SharedRequest
        from dsh.attachment.images_current import read_request_image
        from dsh.attachment.local import request_image_variant_id
        check_abort(signal)
        key = str(request_image_variant_id(ref, policy))
        operation = self._request_inflight.get(key)
        if operation is not None and operation.controller.signal.aborted:
            self._request_inflight.pop(key, None)
            operation = None
        if operation is None:
            async def compute(shared_signal):
                async def transform():
                    stored = await self.readImage(ref, shared_signal)
                    return await read_request_image(self.root, stored, policy, shared_signal)
                return await self.compression.run(transform)
            operation = SharedRequest(compute)
            self._request_inflight[key] = operation
            def settled(_done):
                if self._request_inflight.get(key) is operation:
                    self._request_inflight.pop(key, None)
            operation.task.add_done_callback(settled)
        return await operation.wait(signal)

    async def saveFile(self, input_data):
        return await save_file_verbatim(self.root, input_data)

    async def saveFileStream(self, input_data):
        return await save_file_stream_verbatim(self.root, input_data)

    def readFileStream(self, ref, signal=None):
        return read_file_stream_verbatim(self.root, ref, signal)

    def fileHostPath(self, ref):
        return stored_file_path(self.root, ref)

    def imageHostPath(self, ref):
        return self.image_host_path(ref)
