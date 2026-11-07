def plugin(ctx):
    tool = harness.defineTool({
        'name': 'win7_echo',
        'description': 'Return text without modifying files.',
        'parameters': {'text': {'type': 'string', 'required': True}},
        'execute': lambda args, execution: args['text'],
        'output': {'schema': {'type': 'string'},
                   'render': lambda args, value: [{'type': 'text', 'text': value}]},
    })
    ctx.tools.register(tool)


plugin.inject = ['tools']
