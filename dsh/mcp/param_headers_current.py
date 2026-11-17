"""Pinned SDK primitive parameter headers and static schema reachability."""
import base64
import math
import re

from dsh.cordis.utils import _js_own_enumerable_keys, js_to_string
from dsh.host.http_proxy_policy import JS_SPACE

TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
NON_REACHABLE = ('items','prefixItems','contains','additionalProperties','unevaluatedProperties',
    'unevaluatedItems','propertyNames','patternProperties','dependentSchemas','oneOf','anyOf',
    'allOf','not','if','then','else','$defs','definitions')
OBJECT_VALUED = ('patternProperties','dependentSchemas','$defs','definitions')
MISSING = object()


def entries(value):
    if isinstance(value,dict):
        return [(key,value[key]) for key in _js_own_enumerable_keys(value)]
    if isinstance(value,list):
        return [(str(index),item) for index,item in enumerate(value)]
    return []


def scan_declarations(input_schema):
    declarations,seen = [],{}
    def visit(node,path,reachable):
        if not isinstance(node,dict):
            return None
        label = '.'.join(path) if path else '<root>'
        if 'x-mcp-header' in node:
            if not reachable or not path:
                return label+": x-mcp-header is only permitted on properties statically reachable via a chain of 'properties' keys (not under items, additionalProperties, oneOf/anyOf/allOf/not, if/then/else, or $ref)"
            raw = node['x-mcp-header']
            if not isinstance(raw,str) or not raw:
                return label+': x-mcp-header MUST be a non-empty string'
            if TOKEN.fullmatch(raw) is None:
                return label+": x-mcp-header '"+raw+"' is not a valid RFC 9110 token (no spaces, control characters or HTTP delimiters)"
            kind = node.get('type')
            if not isinstance(kind,str) or kind not in ('string','integer','boolean','number'):
                return label+': x-mcp-header is only permitted on primitive-typed properties (string, integer, boolean); got '+(kind if isinstance(kind,str) else '<none>')
            lower = raw.lower()
            if lower in seen:
                return "x-mcp-header '"+raw+"' is not case-insensitively unique (also declared as '"+seen[lower]+"')"
            seen[lower] = raw
            declarations.append(dict(path=path,headerName=raw,type=kind))
        for key,child in entries(node.get('properties')):
            fault = visit(child,path+[key],reachable)
            if fault is not None:return fault
        for key in NON_REACHABLE:
            if key not in node:continue
            value = node[key]
            branches = value if isinstance(value,list) else (
                [item for _,item in entries(value)] if isinstance(value,dict) and key in OBJECT_VALUED else [value])
            for branch in branches:
                fault = visit(branch,path+['<'+key+'>'],False)
                if fault is not None:return fault
        return None
    fault = visit(input_schema,[],True)
    return dict(valid=True,declarations=declarations) if fault is None else dict(valid=False,reason=fault)


def encode_param_value(value):
    plain = bool(value) and value == value.strip(JS_SPACE) and not (value.startswith('=?base64?') and value.endswith('?='))
    plain = plain and all(character=='\t' or 32<=ord(character)<=126 for character in value)
    if plain:return value
    encoded = value.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace').encode('utf-8')
    return '=?base64?'+base64.b64encode(encoded).decode('ascii')+'?='


def build_param_headers(declarations,args):
    result = {}
    for declaration in declarations:
        value = args
        for key in declaration['path']:
            if isinstance(value,dict):value = value.get(key,MISSING)
            elif isinstance(value,list) and key=='length':value = len(value)
            elif isinstance(value,list) and re.fullmatch(r'0|[1-9][0-9]*',key):
                index = int(key);value = value[index] if index<len(value) else MISSING
            else:value = MISSING
        if isinstance(value,str) or isinstance(value,bool):text = js_to_string(value)
        elif type(value) in (int,float):
            try:number = float(value)
            except OverflowError:continue
            if not math.isfinite(number) or (number.is_integer() and abs(number)>9007199254740991):continue
            text = js_to_string(value)
        else:continue
        result['Mcp-Param-'+declaration['headerName']] = encode_param_value(text)
    return result
