"""Managed server entry schema, write-time validation and client conversion."""
import re
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _js_own_enumerable_keys
from dsh.mcp.config import RECONNECT
from dsh.mcp.connection import resolve_reconnect_policy
from dsh.mcp.current import RESOURCE_CONFIG
from dsh.mcp.diagnostic_current import McpLocalError
from dsh.mcp.templates_current import assert_template_syntax

SERVER_ENTRY_SCHEMA = Schema.object(dict(
    transport=Schema.union(['stdio','streamable-http']).required(),
    command=Schema.string().default(''),args=Schema.array(str).default([]),
    env=Schema.dict(str).default({}),cwd=Schema.string().default(''),
    url=Schema.string().default(''),headers=Schema.dict(str).default({}),
    enabled=Schema.boolean().default(True),toolCallTimeoutMs=Schema.number(),
    startupTimeoutMs=Schema.number().min(1).max(2147483647).default(30000),
    closeTimeoutMs=Schema.number().min(1).max(2147483647),reconnect=RECONNECT))
MANAGER_CONFIG = Schema.object(dict(servers=Schema.dict(SERVER_ENTRY_SCHEMA).default({}).volatile()))


def templated_strings(name, entry):
    path = 'servers.'+name
    if entry['transport']=='stdio':
        return [(entry['command'],path+'.command')]+[(value,path+'.args['+str(index)+']') for index,value in enumerate(entry['args'])]+[(entry['env'][key],path+'.env.'+key) for key in _js_own_enumerable_keys(entry['env'])]+[(entry['cwd'],path+'.cwd')]
    return [(entry['url'],path+'.url')]+[(entry['headers'][key],path+'.headers.'+key) for key in _js_own_enumerable_keys(entry['headers'])]


def validate_entries(entries):
    for name in _js_own_enumerable_keys(entries):
        entry, path = entries[name], 'servers.'+name
        if re.fullmatch(r'[A-Za-z0-9_-]{1,32}',name) is None:
            raise McpLocalError(path+': server name must match /^[A-Za-z0-9_-]{1,32}$/ — rename the entry key')
        if entry['transport']=='stdio':
            if entry['command']=='':raise McpLocalError(path+': a stdio server requires "command"')
            for key in ('url','headers'):
                if entry[key]:raise McpLocalError(path+': "'+key+'" is not a stdio field — remove it or set transport: streamable-http')
        else:
            if entry['url']=='':raise McpLocalError(path+': a streamable-http server requires "url"')
            for key in ('command','args','env','cwd'):
                if entry[key]:raise McpLocalError(path+': "'+key+'" is not a streamable-http field — remove it or set transport: stdio')
        for value,where in templated_strings(name,entry):assert_template_syntax(value,where)
        resolve_reconnect_policy(entry['reconnect'],path+'.reconnect')


def to_client_config(name, entry):
    shared = dict(serverName=name,failOnStartupError=False,expandTemplates=True,
        startupTimeoutMs=entry['startupTimeoutMs'],reconnect=entry['reconnect'])
    for key in ('closeTimeoutMs','toolCallTimeoutMs'):
        if key in entry:shared[key]=entry[key]
    if entry['transport']=='stdio':
        raw = dict(transport='stdio',command=entry['command'],args=list(entry['args']),env=dict(entry['env']),cwd=entry['cwd'],**shared)
    else:raw = dict(transport='streamable-http',url=entry['url'],headers=dict(entry['headers']),**shared)
    return RESOURCE_CONFIG(raw)
