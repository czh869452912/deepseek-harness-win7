"""JavaScript text boundaries used by the ported fixed workflow."""

import json

from dsh.cordis.utils import _js_string_length

utf16_length = _js_string_length
JS_WHITESPACE = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def js_trim(value):
    return value.strip(JS_WHITESPACE)


def utf16_slice(value, units):
    return value.encode("utf-16-le", "surrogatepass")[:units * 2].decode("utf-16-le", "surrogatepass")


def json_text(value, pretty=False):
    rendered = json.dumps(value, ensure_ascii=False, allow_nan=False,
                          indent=2 if pretty else None, separators=None if pretty else (",", ":"))
    # JSON.stringify joins surrogate pairs and escapes lone UTF-16 surrogates.
    rendered = rendered.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
    return rendered.encode("utf-8", "backslashreplace").decode("utf-8")
