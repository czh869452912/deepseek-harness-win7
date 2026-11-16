"""Credential template grammar and sequential substitution for MCP strings."""
import re

from dsh.mcp.diagnostic_current import McpLocalError

_TOKEN = re.compile(r'\$\{credential:([A-Za-z_][A-Za-z0-9_]*)\}')
_EXACT = re.compile(r'\$\{credential:[A-Za-z_][A-Za-z0-9_]*\}')
_SUSPECT = re.compile(r'\$\{[^}]*\}')


class MissingTemplateValue(McpLocalError):
    pass


def credential_refs_in(value):
    return [token.group(1) for token in _TOKEN.finditer(value)]


def assert_template_syntax(value, where):
    for occurrence in _SUSPECT.finditer(value):
        if _EXACT.fullmatch(occurrence.group(0)) is None:
            raise McpLocalError(where+': "'+occurrence.group(0)+'" is not a template token — use ${credential:REF}')


async def resolve_template_string(value, where, credential):
    out, cursor = '', 0
    for token in _TOKEN.finditer(value):
        name = token.group(1)
        resolved = await credential(name)
        if resolved is None:
            raise MissingTemplateValue(where+': credential "'+name+'" is not configured — store it through the credential seam or remove the ${credential:'+name+'} template')
        out += value[cursor:token.start()]+resolved
        cursor = token.end()
    return out+value[cursor:]
