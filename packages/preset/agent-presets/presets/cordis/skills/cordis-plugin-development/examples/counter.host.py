def plugin(ctx):
    state = {'calls': 0}
    ctx.provide('win7AuthoringCounter', state)
    # effect executes setup now and owns the returned cleanup.
    ctx.effect(lambda: state.clear)

    def echo(args):
        state['calls'] += 1
        return {'text': args['text'], 'calls': state['calls']}

    harness.handle('echo', echo)
    harness.handle('snapshot', lambda args: dict(state))
    tool = harness.defineTool({
        'name': 'win7_counted_echo',
        'description': 'Echo text and count calls in this activation.',
        'parameters': {'text': {'type': 'string', 'required': True}},
        'execute': lambda args, execution: echo(args),
        'output': {
            'schema': {'type': 'object', 'additionalProperties': False,
                       'properties': {'text': {'type': 'string', 'required': True},
                                      'calls': {'type': 'integer', 'required': True}}},
            'render': lambda args, value: [{'type': 'text', 'text': value['text']}],
        },
    })
    harness.registerTool(ctx, tool)


plugin.inject = ['tools']
