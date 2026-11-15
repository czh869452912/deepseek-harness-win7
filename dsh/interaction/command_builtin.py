"""First-party definition identities and English/Chinese input spellings."""
BUILTINS = dict(goal='@deepseek-ai/dsh-command-goal', plan='@deepseek-ai/dsh-plan-mode',
                feedback='@deepseek-ai/dsh-command-feedback', compact='@deepseek-ai/dsh-command-compact',
                permission='@deepseek-ai/dsh-permission-presets', export='@deepseek-ai/dsh-session-log-export')
TOKENS = dict(en=dict(zip(BUILTINS, BUILTINS)),
              zh=dict(zip(BUILTINS, ('目标', '计划', '反馈', '压缩', '权限', '导出'))))


def field(descriptor, key):
    return descriptor.get(key) if isinstance(descriptor, dict) else getattr(descriptor, key, None)


def builtin_command_name(descriptor):
    return next((name for name, identity in BUILTINS.items() if field(descriptor, 'definitionId') == identity), None)


def resolve_command(token, descriptors):
    exact = next((descriptor for descriptor in descriptors if field(descriptor, 'name') == token), None)
    if exact is not None:
        return exact
    name = next((name for language in TOKENS.values() for name, spelling in language.items() if spelling == token), None)
    return next((descriptor for descriptor in descriptors if name is not None and field(descriptor, 'definitionId') == BUILTINS[name]), None)


builtinCommandName = builtin_command_name
resolveCommand = resolve_command
builtinCommandTokens = TOKENS
