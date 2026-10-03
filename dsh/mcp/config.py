import re

from dsh.cordis.schema import Schema
from dsh.mcp.connection import RECONNECT_DEFAULTS


RECONNECT = Schema.object({
    'enabled': Schema.boolean().default(RECONNECT_DEFAULTS['enabled']),
    'initialDelayMs': Schema.number().min(1).max(2147483647).default(RECONNECT_DEFAULTS['initialDelayMs']),
    'maxDelayMs': Schema.number().min(1).max(2147483647).default(RECONNECT_DEFAULTS['maxDelayMs']),
    'maxAttempts': Schema.number().step(1).min(1).max(9007199254740991).default(RECONNECT_DEFAULTS['maxAttempts']),
})


CONFIG = Schema.union([
    Schema.object({
        'transport': Schema.const_('stdio'),
        'serverName': Schema.string().required().pattern(re.compile(r'^[A-Za-z0-9_-]{1,32}$')),
        'command': Schema.string().required(),
        'args': Schema.array(Schema.string()).default([]),
        'env': Schema.dict(Schema.string()).default({}),
        'cwd': Schema.string().default(''),
        'toolCallTimeoutMs': Schema.number().default(60000),
        'failOnStartupError': Schema.boolean().default(False),
        'reconnect': RECONNECT,
    }),
    Schema.object({
        'transport': Schema.const_('streamable-http'),
        'serverName': Schema.string().required().pattern(re.compile(r'^[A-Za-z0-9_-]{1,32}$')),
        'url': Schema.string().required(),
        'headers': Schema.dict(Schema.string()).default({}),
        'toolCallTimeoutMs': Schema.number().default(60000),
        'failOnStartupError': Schema.boolean().default(False),
        'reconnect': RECONNECT,
    }),
])
