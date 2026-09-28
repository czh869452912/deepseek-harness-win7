"""Scoped model adapters for continuation delivery, interruption and reports."""
from dsh.cordis.plugin import Plugin
from dsh.subagent.canonical_tools import register, object_schema, text, agent_of


class ToolSubagentControl(Plugin):
    id = 'tool-subagent-control'
    inject = ['tools', 'subagents']

    def apply(self, ctx):
        async def send(args, execution):
            parent = agent_of(execution)
            identity = await ctx.get('subagents').followup(parent, args['subagent_id'], text(args['message']),
                dict(source=dict(kind='coordinator', form='relay', senderSessionId=parent.id), signal=execution.signal))
            return dict(messageId=identity)
        register(ctx, 'send_message', 'Queue the next FIFO turn for your direct background child. Returns admission only; it does not redirect the current turn.',
                 dict(subagent_id={'type': 'string'}, message={'type': 'string'}), send,
                 object_schema(dict(messageId={'type': 'string'})), lambda args, _: text('message queued as the next turn for subagent ' + args['subagent_id']))
        async def interrupt(args, execution):
            ctx.get('subagents').interrupt(args['agent_id'], dict(kind='ancestor', agent=agent_of(execution)))
            return dict(accepted=True)
        register(ctx, 'interrupt_agent', 'Stop a descendant background agent current turn. Queued messages and descendants remain available; a later send_message wakes parked work.',
                 dict(agent_id={'type': 'string'}), interrupt, object_schema(dict(accepted={'type': 'boolean'})),
                 lambda args, _: text('interrupt requested for agent ' + args['agent_id']))


class ToolListAgents(Plugin):
    id = 'tool-subagent-list-agents'
    inject = ['tools', 'subagents', 'agents']

    def apply(self, ctx):
        async def execute(args, execution):
            parent = agent_of(execution)
            descendants = args.get('scope', 'children') == 'descendants'
            service = ctx.get('subagents')
            rows = await (service.listDescendants(parent.id, execution.signal) if descendants else service.listChildren(parent.id, execution.signal))
            result = []
            for row in rows:
                position = dict(parent=row['parentId'], depth=row['depth']) if descendants else {}
                if row['kind'] == 'diagnostic':
                    result.append(dict(kind='diagnostic', id=row['id'], reason=row['reason'], **position))
                elif row['mode'] == 'continuable':
                    agent = ctx.get('agents').get(row['id'])
                    status = 'ready' if agent is None else 'running' if agent.status == 'running' else 'idle'
                    result.append(dict(kind='child', id=row['id'], label=row['label'], status=status, **position))
            return result
        def render(args, entries):
            if not entries:
                return text('(no subagents)')
            lines = []
            for entry in entries:
                at = ' parent={} depth={}'.format(entry['parent'], entry['depth']) if args.get('scope') == 'descendants' else ''
                lines.append('{} [{}]{}{}'.format(entry['id'], entry['status'] if entry['kind'] == 'child' else 'diagnostic: ' + entry['reason'],
                    at, ' — ' + entry['label'] if entry['kind'] == 'child' else ''))
            return text('\n'.join(lines))
        common = dict(id={'type': 'string'}, parent={'type': 'string'}, depth={'type': 'number'})
        schema = {'type': 'array', 'items': {'oneOf': [
            object_schema(dict(common, kind={'type': 'string', 'const': 'child'}, label={'type': 'string'}, status={'type': 'string', 'enum': ['running', 'idle', 'ready']}), ['kind', 'id', 'label', 'status']),
            object_schema(dict(common, kind={'type': 'string', 'const': 'diagnostic'}, reason={'type': 'string', 'enum': ['corrupt', 'unsupported', 'unavailable']}), ['kind', 'id', 'reason'])]}}
        register(ctx, 'list_agents', 'Recall continuable child ids. Status ready means persisted and resumable. Descendants include tree position; send_message accepts only direct children.',
                 dict(scope={'type': 'string', 'enum': ['children', 'descendants']}), execute, schema, render, [])


class ToolSubagentReport(Plugin):
    id = 'tool-subagent-report'
    inject = ['tools', 'subagents', 'systemPrompt']

    def apply(self, ctx):
        delivery = self.config.get('reportDelivery', 'next-step')
        if delivery not in ('quiet', 'next-step'):
            raise ValueError('invalid reportDelivery')
        def install(child_ctx):
            section = child_ctx.get('systemPrompt').section(dict(name='tool:report', order=2900,
                text='Report a self-contained result before finishing, and report partial findings when they change what your parent should do next. Reporting does not end your turn.'))
            async def execute(args, execution):
                identity = ctx.get('subagents').reportFrom(agent_of(execution), text(args['output']), dict(delivery=delivery, signal=execution.signal))
                return dict(messageId=identity)
            try:
                tool = register(child_ctx, 'report', 'Deliver selected content to your direct parent without ending your turn. A failed call may still have arrived; do not blindly repeat it.',
                    dict(output={'type': 'string'}), execute, object_schema(dict(messageId={'type': 'string'})),
                    lambda _, value: text('report accepted by the agent that started you as message ' + value['messageId']))
            except BaseException:
                section()
                raise
            def dispose():
                errors = []
                for remove in (tool, section):
                    try:
                        remove()
                    except Exception as error:
                        errors.append(error)
                if errors:
                    raise RuntimeError('failed to revoke report registrations: ' + '; '.join(str(error) for error in errors))
            return dispose
        ctx.get('subagents').registerContinuableSetup(install)
