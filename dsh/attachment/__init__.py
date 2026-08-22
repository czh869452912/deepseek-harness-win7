"""
Durable attachment processing and storage seam.
Aligned 1:1 with `@deepseek-ai/dsh-attachment` and `@deepseek-ai/dsh-attachment-local`.
"""

from dsh.attachment.admission import admit_encoded_images, decode_base64
from dsh.attachment.brand import AttachmentId, ImageVariantId
from dsh.attachment.error import (
    IMAGE_ADMISSION_ERROR_CODES,
    AttachmentError,
    is_image_admission_error,
)
from dsh.attachment.local import (
    LocalAttachmentStore,
    commit_prepared_image_file,
    detect_image,
    prepare_image_file,
    probe_image,
    request_image_variant_id,
)
from dsh.attachment.store import AttachmentStore
from dsh.attachment.types import (
    create_image_attachment_limits,
    create_image_attachment_ref,
)

__all__ = [
    "AttachmentId",
    "ImageVariantId",
    "AttachmentError",
    "is_image_admission_error",
    "IMAGE_ADMISSION_ERROR_CODES",
    "admit_encoded_images",
    "decode_base64",
    "create_image_attachment_ref",
    "create_image_attachment_limits",
    "AttachmentStore",
    "LocalAttachmentStore",
    "probe_image",
    "detect_image",
    "prepare_image_file",
    "commit_prepared_image_file",
    "request_image_variant_id",
]
