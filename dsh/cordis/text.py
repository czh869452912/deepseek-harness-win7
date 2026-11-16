"""ECMAScript whitespace shared by frozen text contracts."""
JS_WHITESPACE = '\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def has_non_whitespace(text):
    return any(char not in JS_WHITESPACE for char in text)


def trim_js(text):
    return text.strip(JS_WHITESPACE)


def lower_js(text):
    """Default Unicode 16 casing, including context-sensitive final sigma."""
    import bisect
    lower,cased,ignorable=_lower_tables()
    def member(code,ranges):
        index=bisect.bisect_right(ranges,(code,0x110000))-1
        return index>=0 and ranges[index][0]<=code<=ranges[index][1]
    result=[]
    for index,char in enumerate(text):
        code=ord(char)
        if code==0x3A3:
            before=index-1;after=index+1
            while before>=0 and member(ord(text[before]),ignorable):before-=1
            while after<len(text) and member(ord(text[after]),ignorable):after+=1
            final=(before>=0 and member(ord(text[before]),cased)
                   and (after==len(text) or not member(ord(text[after]),cased)))
            result.append('\u03c2' if final else '\u03c3')
        else:result.append(lower.get(code,char))
    return ''.join(result)


from functools import lru_cache


@lru_cache(maxsize=1)
def _lower_tables():
    import json
    from pathlib import Path
    with (Path(__file__).with_name('unicode16_lower.json')).open('r',encoding='utf-8') as stream:data=json.load(stream)
    if data['unicode']!='16.0':raise ValueError('unexpected lowercase table version')
    return dict(data['lower']),[tuple(row) for row in data['cased']],[tuple(row) for row in data['ignorable']]
