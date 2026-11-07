"""Combined state, custom event and timer example; no persistent storage."""
def plugin(ctx):
    state = {'calls': 0, 'events': 0, 'ticks': 0, 'active': True}
    ctx.provide('win7AuthoringStateful', state)

    def on_ping(value=None):
        state['events'] += 1

    def tick():
        state['ticks'] += 1

    ctx.on('win7-authoring/ping', on_ping)
    ctx.interval(tick, 20)

    def count(args, execution):
        state['calls'] += 1
        return state['calls']

    ctx.tools.register(harness.defineTool({
        'name': 'win7_state_counter', 'description': 'Count calls in this activation.',
        'parameters': {}, 'execute': count,
        'output': {'schema': {'type': 'integer'},
                   'render': lambda args, value: [{'type': 'text', 'text': str(value)}]},
    }))
    harness.handle('snapshot', lambda args: dict(state))

    def cleanup():
        state['active'] = False

    ctx.effect(lambda: cleanup)


plugin.inject = ['tools', 'timer']
