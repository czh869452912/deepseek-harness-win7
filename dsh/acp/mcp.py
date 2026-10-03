import hashlib
import inspect
import ntpath
import os
import re
import unicodedata
from urllib.parse import urlsplit

from dsh.acp.errors import AcpInvalidParamsError
from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.cordis.utils import js_to_string


class AcpMcpConfigError(AcpInvalidParamsError):
    name = 'AcpMcpConfigError'


def normalize_server_name(name):
    if not name.strip('\u0009\u000a\u000b\u000c\u000d \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff') or re.search(r'[\x00-\x1f\x7f]', name):
        raise AcpMcpConfigError('mcpServers contains an invalid server name')
    if re.fullmatch(r'[A-Za-z0-9_-]{1,32}', name):
        return name
    slug = re.sub(r'[^A-Za-z0-9_-]+', '_', unicodedata.normalize('NFKD', name)).strip('_')[:20] or 'server'
    normalized = name.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace')
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:8]
    return (slug + '_' + digest)[:32]


def entries_to_record(entries, field, kind):
    result, names = {}, set()
    for entry in entries:
        name, value = entry['name'], entry['value']
        if kind == 'header':
            if not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or re.search(r'[^\x09\x20-\x7e\x80-\xff]', js_to_string(value)):
                raise AcpMcpConfigError(field + ' contains an invalid header entry')
        elif not name or '=' in name or '\0' in name or '\0' in value:
            raise AcpMcpConfigError(field + ' contains an invalid environment entry')
        identity = name.lower() if kind == 'header' else name
        if identity in names:
            raise AcpMcpConfigError(field + ' contains duplicate name: ' + name)
        names.add(identity)
        result[name] = value
    return result


def assert_http_url(value, field):
    try:
        candidate = value.strip('\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f ').replace('\t', '').replace('\n', '').replace('\r', '')
        match = re.match(r'^(https?):(.*)$', candidate, re.IGNORECASE | re.DOTALL)
        if match is None:
            raise ValueError('unsupported protocol')
        parsed = urlsplit(match.group(1) + '://' + match.group(2).replace('\\', '/').lstrip('/'))
        if not parsed.hostname or re.search(r'[\x00-\x20\x7f%]', parsed.hostname):
            raise ValueError('invalid host')
        parsed.port
    except (ValueError, TypeError):
        raise AcpMcpConfigError(field + ' must be an absolute HTTP(S) URL')


def resolve_mcp_configs(servers, session_cwd, plugin_class=None):
    plugin_class = plugin_class or resolve_harness_plugin('@deepseek-ai/dsh-mcp-client')
    if plugin_class is None:
        raise RuntimeError('ACP requires the mcp-client provider')
    names, configs = set(), []
    for index, server in enumerate(servers):
        name = normalize_server_name(server['name'])
        if name in names:
            raise AcpMcpConfigError('mcpServers contains duplicate normalized name: ' + name)
        names.add(name)
        field = 'mcpServers[%s]' % index
        if 'type' not in server:
            if not (ntpath.isabs(server['command']) if os.name == 'nt' else os.path.isabs(server['command'])):
                raise AcpMcpConfigError(field + '.command must be an absolute path')
            entries = entries_to_record(server['env'], field + '.env', 'environment')
            entry_field = 'env'
            config = {'transport': 'stdio', 'serverName': name, 'command': server['command'],
                      'args': server['args'], 'env': entries, 'cwd': session_cwd, 'failOnStartupError': True}
        elif server['type'] == 'http':
            assert_http_url(server['url'], field + '.url')
            entries = entries_to_record(server['headers'], field + '.headers', 'header')
            entry_field = 'headers'
            config = {'transport': 'streamable-http', 'serverName': name, 'url': server['url'],
                      'headers': entries, 'failOnStartupError': True}
        else:
            raise AcpMcpConfigError(field + ' transport ' + js_to_string(server['type']) + ' is not supported')
        try:
            parsed = plugin_class.Config(config)
        except Exception as error:
            raise AcpMcpConfigError(field + ' is invalid: ' + str(error)) from error
        parsed[entry_field] = entries
        configs.append(parsed)
    return configs


async def mount_acp_mcp_servers(agent_ctx, servers, session_cwd):
    plugin_class = resolve_harness_plugin('@deepseek-ai/dsh-mcp-client')
    configs = resolve_mcp_configs(servers, session_cwd, plugin_class)
    for config in configs:
        mounted = agent_ctx.plugin(plugin_class, config)
        if inspect.isawaitable(mounted):
            await mounted
