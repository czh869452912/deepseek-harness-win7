import hashlib


def instruction_content_sha1(content: str) -> str:
    """Compute lowercase SHA-1 hex digest of exact UTF-8 instruction text."""
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def trimmed_instruction_digest(content: str) -> str:
    """Compute SHA-1 hex digest of trimmed UTF-8 instruction text."""
    return instruction_content_sha1(content.strip())
