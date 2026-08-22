"""
Attachment failure class and failure code taxonomy.
Aligned 1:1 with `@deepseek-ai/dsh-attachment/error`.
"""

from typing import Any, Optional, Set, Tuple

IMAGE_ADMISSION_ERROR_CODES: Tuple[str, ...] = (
    "TOO_MANY_IMAGES",
    "IMAGES_TOO_LARGE",
    "UNSUPPORTED_IMAGE_TYPE",
    "INVALID_IMAGE_BASE64",
    "INVALID_IMAGE",
    "IMAGE_TYPE_MISMATCH",
    "IMAGE_TOO_LARGE",
    "IMAGE_TOO_MANY_PIXELS",
    "IMAGE_DIMENSION_TOO_LARGE",
)

IMAGE_ADMISSION_ERROR_CODE_SET: Set[str] = set(IMAGE_ADMISSION_ERROR_CODES)


class AttachmentError(Exception):
    """
    Stable failures suitable for host RPC error mapping.
    Re-implements HarnessError shape with 'code' attribute.
    """

    def __init__(self, message: str, code: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.name = "AttachmentError"
        self.message = message
        self.code = code
        self.cause = cause

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]: {self.message}"


def is_image_admission_error(error: Any) -> bool:
    """
    Distinguish caller-correctable image admission failures from storage faults.
    """
    if isinstance(error, AttachmentError):
        return error.code in IMAGE_ADMISSION_ERROR_CODE_SET
    if isinstance(error, Exception) and hasattr(error, "code"):
        return getattr(error, "code", None) in IMAGE_ADMISSION_ERROR_CODE_SET
    return False
