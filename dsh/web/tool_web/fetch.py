import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple


TRUNCATION_FOOTER = "\n\n(Content truncated. Fetch a more specific URL or section for the full text.)"
MAX_CONVERSION_DEPTH = 512
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}
RAW_TEXT_ELEMENTS = {"script", "style", "noscript"}


def parse_fetch_args(args: Dict[str, Any]) -> Dict[str, str]:
    if args["url"].strip() == "":
        raise ValueError("url must be a non-empty string")
    return {"url": args["url"]}


def _exceeds_conversion_depth(source: str) -> bool:
    lower = source.lower()
    stack = []
    offset = 0
    in_comment = False
    while offset < len(source):
        start = source.find("<", offset)
        if in_comment:
            end = source.find("-->", offset)
            if end >= 0 and (start < 0 or end < start):
                in_comment = False
                offset = end + 3
                continue
        if start < 0:
            break
        if not in_comment and source.startswith("<!--", start):
            in_comment = True
            offset = start + 4
            continue
        cursor = start + 1
        closing = cursor < len(source) and source[cursor] == "/"
        if closing:
            cursor += 1
        name_start = cursor
        while cursor < len(source) and (source[cursor].isalnum() or source[cursor] == "-"):
            cursor += 1
        if cursor == name_start or not source[name_start].isalpha():
            offset = start + 1
            continue
        name = lower[name_start:cursor]
        quote = None
        while cursor < len(source):
            char = source[cursor]
            cursor += 1
            if quote is not None:
                if char == quote:
                    quote = None
            elif char in ("\"", "'"):
                quote = char
            elif char == ">":
                break
        if cursor == 0 or source[cursor - 1] != ">":
            return True
        if closing:
            if not in_comment and stack and stack[-1] == name:
                stack.pop()
        else:
            last = cursor - 2
            while last >= 0 and source[last].isspace():
                last -= 1
            if name not in VOID_ELEMENTS and (last < 0 or source[last] != "/"):
                stack.append(name)
                if len(stack) > MAX_CONVERSION_DEPTH:
                    return True
                if not in_comment and name in RAW_TEXT_ELEMENTS:
                    end = _find_raw_text_end(lower, name, cursor)
                    if end < 0:
                        break
                    offset = end
                    continue
        offset = cursor
    return False


def _find_raw_text_end(lower: str, name: str, start: int) -> int:
    prefix = "</" + name
    candidate = lower.find(prefix, start)
    while candidate >= 0:
        boundary = candidate + len(prefix)
        char = lower[boundary] if boundary < len(lower) else None
        if char is None or char in (">", "/") or char.isspace():
            return candidate
        candidate = lower.find(prefix, candidate + len(prefix))
    return -1


def _drop_unfinished_comment(source: str) -> str:
    lower = source.lower()
    offset = 0
    while offset < len(source):
        start = source.find("<", offset)
        if start < 0:
            return source
        if source.startswith("<!--", start):
            end = source.find("-->", start + 4)
            if end < 0:
                return source[:start]
            offset = end + 3
            continue
        match = re.match(r"<\s*(script|style|noscript)(?:\s|>|/)", lower[start:])
        if match:
            tag_end = source.find(">", start + len(match.group(0)))
            if tag_end < 0:
                return source
            raw_end = _find_raw_text_end(lower, match.group(1), tag_end + 1)
            offset = len(source) if raw_end < 0 else raw_end + 2 + len(match.group(1))
            continue
        quote = None
        cursor = start + 1
        while cursor < len(source):
            char = source[cursor]
            cursor += 1
            if quote is not None:
                if char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
            elif char == ">":
                break
        offset = cursor if cursor > start + 1 else start + 1
    return source


class _HtmlNode:
    def __init__(self, tag: Optional[str] = None,
                 attrs: Optional[Dict[str, str]] = None,
                 text: Optional[str] = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.text = text
        self.children: List["_HtmlNode"] = []


class _MarkdownParser(HTMLParser):
    """Small DOM carrier followed by Turndown-compatible replacement rules."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = _HtmlNode("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str,
                        attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        node = _HtmlNode(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str,
                           attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data.startswith("<!--"):
            return
        self.stack[-1].children.append(_HtmlNode(text=data))

    def markdown(self) -> str:
        value = _render_tree(self.root)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def _escape_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value.replace("\xa0", " "))
    value = re.sub(r"([\\\[\]*_`])", r"\\\1", value)
    value = re.sub(r"(^|\n)(\s*)(\d+)\.(?=\s)",
                   lambda match: (match.group(1) + match.group(2)
                                  + match.group(3) + "\\."), value)
    value = re.sub(r"(^|\n)(\s*)(-{3,})(?=\s|$)",
                   lambda match: (match.group(1) + match.group(2)
                                  + "\\" + match.group(3)), value)
    return re.sub(r"(^|\n)(\s*)([#>+]|[-*](?=\s))",
                  lambda match: (match.group(1) + match.group(2)
                                 + "\\" + match.group(3)), value)


def _render_tree(root: _HtmlNode) -> str:
    rendered: Dict[int, str] = {}
    raw: Dict[int, str] = {}
    stack = [(root, False)]
    while stack:
        node, visited = stack.pop()
        if not visited:
            stack.append((node, True))
            for child in reversed(node.children):
                stack.append((child, False))
            continue
        key = id(node)
        if node.text is not None:
            raw[key] = node.text
            rendered[key] = _escape_text(node.text)
            continue
        raw[key] = "".join(raw[id(child)] for child in node.children)
        content = "".join(rendered[id(child)] for child in node.children)
        rendered[key] = _render_element(node, content, rendered, raw)
    return rendered[id(root)]


def _wrapped(content: str, marker: str) -> str:
    if not content.strip():
        return ""
    leading = content[:len(content) - len(content.lstrip())]
    trailing = content[len(content.rstrip()):]
    return leading + marker + content.strip() + marker + trailing


def _inline_code(content: str) -> str:
    if not content.strip():
        return ""
    runs = [len(value) for value in re.findall(r"`+", content)]
    delimiter = "`" * max([1] + [length + 1 for length in runs])
    leading = " " if content.startswith("`") else ""
    trailing = " " if content.endswith("`") else ""
    return delimiter + leading + content + trailing + delimiter


def _render_list(node: _HtmlNode, rendered: Dict[int, str]) -> str:
    ordered = node.tag == "ol"
    try:
        number = int(node.attrs.get("start", "1"))
    except ValueError:
        number = 1
    lines = []
    for child in node.children:
        if child.tag != "li":
            continue
        marker = ("%d.  " % number) if ordered else "-   "
        number += 1
        body_parts = []
        nested = []
        for item in child.children:
            if item.tag in ("ul", "ol"):
                nested.append(rendered[id(item)].strip())
            else:
                body_parts.append(rendered[id(item)])
        body = "".join(body_parts).strip()
        body = body.replace("\n", "\n" + " " * len(marker))
        line = marker + body
        for value in nested:
            line += "\n" + "\n".join("    " + part for part in value.splitlines())
        lines.append(line.rstrip())
    return "\n".join(lines)


def _table_rows(node: _HtmlNode) -> List[_HtmlNode]:
    rows = []
    pending = list(node.children)
    while pending:
        child = pending.pop(0)
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in ("thead", "tbody", "tfoot"):
            pending[0:0] = child.children
    return rows


def _render_table(node: _HtmlNode, rendered_values: Dict[int, str]) -> str:
    rows = _table_rows(node)
    output = []
    first_cells = ([child for child in rows[0].children if child.tag in ("th", "td")]
                   if rows else [])
    has_heading = bool(first_cells) and all(cell.tag == "th" for cell in first_cells)
    if first_cells and not has_heading:
        output.append("| " + " | ".join("   " for _cell in first_cells) + " |")
        output.append("| " + " | ".join("---" for _cell in first_cells) + " |")
    for index, row in enumerate(rows):
        cells = [child for child in row.children if child.tag in ("th", "td")]
        rendered = []
        for cell in cells:
            rendered.append({"text": ["".join(rendered_values[id(child)] for child in cell.children)],
                             "heading": cell.tag == "th",
                             "alignment": _cell_alignment(cell)})
        output.append("| " + " | ".join(_table_cell("".join(cell["text"])) for cell in rendered) + " |")
        if index == 0 and has_heading:
            output.append("| " + " | ".join(_table_border(cell["alignment"]) for cell in rendered) + " |")
    return "\n".join(output)


def _cell_alignment(node: _HtmlNode) -> str:
    alignment = node.attrs.get("align", "").lower()
    match = re.search(r"text-align\s*:\s*(left|right|center)",
                      node.attrs.get("style", ""), re.IGNORECASE)
    return alignment or (match.group(1).lower() if match else "")


def _render_element(node: _HtmlNode, content: str,
                    rendered: Dict[int, str], raw: Dict[int, str]) -> str:
    tag = node.tag or ""
    if tag in RAW_TEXT_ELEMENTS:
        return ""
    if tag == "pre":
        content = raw[id(node)]
        language = ""
        if len(node.children) == 1 and node.children[0].tag == "code":
            code = node.children[0]
            content = raw[id(code)]
            match = re.search(r"(?:^|\s)language-(\S+)", code.attrs.get("class", ""))
            language = match.group(1) if match else ""
        content = content.rstrip("\n")
        runs = [len(value) for value in re.findall(r"`{3,}", content)]
        fence = "`" * max([3] + [length + 1 for length in runs])
        return "\n\n%s%s\n%s\n%s\n\n" % (fence, language, content, fence)
    if tag in ("strong", "b"):
        return _wrapped(content, "**")
    if tag in ("em", "i"):
        return _wrapped(content, "_")
    if tag in ("del", "s", "strike"):
        return _wrapped(content, "~~")
    if tag == "code":
        return _inline_code(raw[id(node)])
    if tag == "a":
        href = node.attrs.get("href", "")
        title = node.attrs.get("title")
        return "[%s](%s%s)" % (content, href, ' "%s"' % title if title else "")
    if tag == "img":
        alt = _escape_text(node.attrs.get("alt", ""))
        src = node.attrs.get("src", "")
        title = node.attrs.get("title")
        return "![%s](%s%s)" % (alt, src, ' "%s"' % title if title else "")
    if tag == "input" and node.attrs.get("type", "").lower() == "checkbox":
        return ("[x] " if "checked" in node.attrs else "[ ] ")
    if tag == "hr":
        return "\n\n* * *\n\n"
    if tag == "br":
        return "  \n"
    if tag in ("ul", "ol"):
        return "\n\n" + _render_list(node, rendered) + "\n\n"
    if tag == "li":
        return content
    if tag == "blockquote":
        body = re.sub(r"\n{2,}", "\n\n", content.strip())
        return "\n\n" + "\n".join("> " + line for line in body.split("\n")) + "\n\n"
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return "\n\n" + "#" * int(tag[1]) + " " + content.strip() + "\n\n"
    if tag == "div":
        match = re.search(r"(?:^|\s)highlight-source-(\S+)",
                          node.attrs.get("class", ""))
        if match and any(child.tag == "pre" for child in node.children):
            value = content.strip()
            if value.startswith("```"):
                value = "```" + match.group(1) + value[3:]
            return "\n\n" + value + "\n\n"
        return "\n\n" + content.strip() + "\n\n"
    if tag == "p":
        return "\n\n" + content.strip() + "\n\n"
    if tag == "table":
        return "\n\n" + _render_table(node, rendered) + "\n\n"
    return content


def _table_cell(value: str) -> str:
    escaped = value.strip().replace("\n\r", "<br>").replace("\n", "<br>")
    escaped = re.sub(r"\|+", r"\\|", escaped)
    return escaped.ljust(3)


def _table_border(alignment: str) -> str:
    if alignment == "left":
        return ":---"
    if alignment == "right":
        return "---:"
    if alignment == "center":
        return ":---:"
    return "---"


def _format_table(rows: List[List[Dict[str, Any]]]) -> str:
    if not rows:
        return ""
    output = []
    for index, row in enumerate(rows):
        output.append("| " + " | ".join(_table_cell("".join(cell["text"])) for cell in row) + " |")
        if index == 0 and row and all(cell["heading"] for cell in row):
            output.append("| " + " | ".join(_table_border(cell["alignment"]) for cell in row) + " |")
    return "\n".join(output)


def _render_body(body: Mapping, max_input_chars: int) -> Tuple[str, bool]:
    original = body["content"]
    content = original[:max_input_chars]
    source_truncated = len(content) != len(original)
    if body["kind"] == "text":
        return content, source_truncated
    if body["kind"] != "html":
        raise ValueError("unhandled web fetch body kind")
    if _exceeds_conversion_depth(content):
        return content, source_truncated
    try:
        parser = _MarkdownParser()
        parser.feed(_drop_unfinished_comment(content))
        parser.close()
        return parser.markdown(), source_truncated
    except Exception:
        return content, source_truncated


_RENDER_CACHE = {}
_RENDER_CACHE_ORDER = []


def render_fetch_output(result: Mapping, max_output_chars: int) -> Dict[str, Any]:
    key = (id(result), max_output_chars)
    cached = _RENDER_CACHE.get(key)
    if cached is not None and cached[0] is result:
        return cached[1]
    computed = _compute_fetch_output(result, max_output_chars)
    _RENDER_CACHE[key] = (result, computed)
    _RENDER_CACHE_ORDER.append(key)
    while len(_RENDER_CACHE_ORDER) > 64:
        stale = _RENDER_CACHE_ORDER.pop(0)
        _RENDER_CACHE.pop(stale, None)
    return computed


def _compute_fetch_output(result: Mapping, max_output_chars: int) -> Dict[str, Any]:
    header = "Fetched %s (HTTP %s)\n\n" % (result["url"], result["statusCode"])
    body, source_truncated = _render_body(result["body"], max_output_chars)
    prefix = header + body
    truncated = bool(result["truncated"] or source_truncated or len(prefix) > max_output_chars)
    complete = prefix + (TRUNCATION_FOOTER if truncated else "")
    if len(complete) <= max_output_chars:
        return {"text": complete, "truncated": truncated}
    if max_output_chars < len(TRUNCATION_FOOTER):
        return {"text": complete[:max_output_chars], "truncated": True}
    return {"text": prefix[:max_output_chars - len(TRUNCATION_FOOTER)] + TRUNCATION_FOOTER,
            "truncated": True}


def format_fetch_output(result: Any = None, max_output_chars: int = 200000, **kwargs: Any) -> str:
    if not isinstance(result, Mapping):
        url = kwargs.get("url", result)
        value = {"url": url, "statusCode": kwargs.get("status_code", 200),
                 "body": {"kind": "text", "content": kwargs.get("content", "")},
                 "truncated": bool(kwargs.get("truncated", False))}
    else:
        value = result
    return render_fetch_output(value, max_output_chars)["text"]


def fetch_meta_from_value(value: Mapping, max_output_chars: int) -> Dict[str, Any]:
    rendered = render_fetch_output(value, max_output_chars)
    return {"url": value["url"], "statusCode": value["statusCode"],
            "truncated": rendered["truncated"]}


def fetch_meta_from_result(meta: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(meta, Mapping):
        return None
    status = meta.get("statusCode")
    if (not isinstance(meta.get("url"), str) or isinstance(status, bool)
            or not isinstance(status, (int, float)) or not isinstance(meta.get("truncated"), bool)):
        return None
    return {"url": meta["url"], "statusCode": status, "truncated": meta["truncated"]}


def present_fetch_call(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"card": "generic", "title": args["url"], "kind": "fetch", "rawInput": args["url"]}


def present_fetch_result(args: Dict[str, Any], result: Any) -> Any:
    if getattr(result, "is_error", getattr(result, "isError", False)):
        return None
    meta = fetch_meta_from_result(getattr(result, "meta", None))
    if meta is None:
        return None
    return {"card": "web", "kind": "fetch", "title": args["url"], "url": meta["url"],
            "statusCode": meta["statusCode"], "truncated": meta["truncated"]}
