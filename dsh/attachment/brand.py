"""
Branded identity types for attachments.
Aligned 1:1 with `@deepseek-ai/dsh-attachment/brand`.
"""


def AttachmentId(value: str) -> str:
    """Brand string wrapper for AttachmentId."""
    return str(value)


def ImageVariantId(value: str) -> str:
    """Brand string wrapper for ImageVariantId."""
    return str(value)
