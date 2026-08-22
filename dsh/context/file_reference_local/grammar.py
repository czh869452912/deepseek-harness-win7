import re
from typing import Any, Dict, Optional


class ActiveAtToken:
    def __init__(self, prefix: str, query: str, quoted: bool):
        self.prefix = prefix
        self.query = query
        self.quoted = quoted

    def to_dict(self) -> Dict[str, Any]:
        return {"prefix": self.prefix, "query": self.query, "quoted": self.quoted}


def active_at_token(line: str, cursor_col: int) -> Optional[ActiveAtToken]:
    """
    Extract an @path or @"path with spaces token at cursor.
    An @ inside another token (like an email) is not a completion trigger.
    """
    before_cursor = line[:cursor_col]
    quoted_match = re.search(r'(?:^|\s)(@"([^"]*))$', before_cursor)
    if quoted_match and quoted_match.group(1) is not None and quoted_match.group(2) is not None:
        return ActiveAtToken(prefix=quoted_match.group(1), query=quoted_match.group(2), quoted=True)

    plain_match = re.search(r'(?:^|\s)(@([^\s]*))$', before_cursor)
    if plain_match and plain_match.group(1) is not None and plain_match.group(2) is not None:
        return ActiveAtToken(prefix=plain_match.group(1), query=plain_match.group(2), quoted=False)

    return None


def format_file_mention(candidate: Dict[str, str], preserve_quote: bool = False) -> Optional[str]:
    """
    Format a selected path as prompt text. Whitespace uses the quoted @"path" grammar;
    a quoted directory keeps that quote open after its trailing slash.
    """
    kind = candidate.get("kind", "file")
    path_val = candidate.get("path", "")
    path = f"{path_val}/" if kind == "directory" else path_val

    # Check for invalid control chars or double quote
    if re.search(r'[\u0000-\u001f\u007f-\u009f"]', path):
        return None

    is_quoted = preserve_quote or bool(re.search(r'\s', path))
    if not is_quoted:
        return f"@{path}"
    if kind == "directory":
        return f'@"{path}'
    return f'@"{path}"'
