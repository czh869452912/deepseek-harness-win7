"""
Durable attachment storage seam (ctx.attachments).
Aligned 1:1 with `@deepseek-ai/dsh-attachment/index`.
"""

from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.attachment.error import AttachmentError
from dsh.attachment.types import create_image_attachment_limits


class AttachmentStore(Plugin):
    """
    Immutable binary attachment service.
    Implementations validate bytes before publishing a reference.
    """

    id = "attachments"
    name = "@deepseek-ai/dsh-attachment"

    @property
    def image_limits(self) -> Dict[str, Any]:
        """Deployment-resolved image policy used by validation."""
        return create_image_attachment_limits()

    def validate_image(self, input_data: Dict[str, Any]) -> None:
        """Validate one image without persisting it."""
        raise NotImplementedError

    def validate_image_batch(self, inputs: List[Dict[str, Any]]) -> None:
        """Validate one ordered image batch before committing any member."""
        limits = self.image_limits
        max_count = limits.get("maxImagesPerMessage", 20)
        max_batch_bytes = limits.get("maxMessageImageBytes", 200 * 1024 * 1024)
        media_types = limits.get("mediaTypes", ["image/png", "image/jpeg", "image/webp", "image/gif"])

        if len(inputs) > max_count:
            raise AttachmentError("Image batch exceeds the configured image-count limit.", "TOO_MANY_IMAGES")

        total_bytes = sum(len(inp.get("data", b"")) for inp in inputs)
        if total_bytes > max_batch_bytes:
            raise AttachmentError("Image batch exceeds the configured aggregate image-byte limit.", "IMAGES_TOO_LARGE")

        for inp in inputs:
            mtype = inp.get("mediaType", "")
            if mtype not in media_types:
                raise AttachmentError(f"Image type {mtype} is not accepted by this deployment.", "UNSUPPORTED_IMAGE_TYPE")

    def save_images(self, inputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate and durably commit one ordered image batch."""
        self.validate_image_batch(inputs)
        for inp in inputs:
            self.validate_image(inp)

        refs: List[Dict[str, Any]] = []
        for inp in inputs:
            refs.append(self.save_image(inp))
        return refs

    def save_image(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and durably commit one image."""
        raise NotImplementedError

    def read_image(self, ref: Dict[str, Any], signal: Any = None) -> Dict[str, Any]:
        """Read one image and verify that bytes still match recorded reference."""
        raise NotImplementedError

    def read_image_request(
        self, ref: Dict[str, Any], policy: Dict[str, Any], signal: Any = None
    ) -> Dict[str, Any]:
        """Generate or read model-request version from stored normalized image."""
        raise AttachmentError(
            "The mounted attachment provider cannot derive model-request images.",
            "ATTACHMENT_PROJECTION_UNSUPPORTED",
        )
