"""Candidate creation-time, durable subagent model authorization settings."""
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.cordis.volatile import is_volatile
from dsh.core.session.json import UNDEFINED
from dsh.subagent.selection import POLICY, assert_allowed_routes, read_policy


class SubagentModelSelectionConfig(Plugin):
    id = 'subagent-model-selection-settings'
    inject = ['sessionProjections', 'sessions']
    Config = Schema.object(dict(
        enabled=Schema.boolean().default(False).volatile(),
        allowedModels=Schema.array(Schema.object(dict(
            provider=Schema.string().min(1).required(),
            model=Schema.string().min(1).required()))).default([]).volatile()))

    def current(self):
        def value(name):
            item = self.config[name]
            return item.get() if is_volatile(item) else item
        enabled, routes = value('enabled'), value('allowedModels')
        assert_allowed_routes(routes)
        if enabled and not routes:
            raise RuntimeError('enabled subagent model selection requires at least one allowed model')
        return dict(enabled=enabled, allowedModels=[dict(route) for route in routes])

    async def apply(self, ctx):
        ready = ctx.get('sessionProjections').register(POLICY)

        async def created(payload):
            projection = await ready
            ctx.fiber.assert_active()
            target = payload['agent'].session
            if read_policy(projection, target) is not UNDEFINED:
                return
            allowed = UNDEFINED
            parent_id = target.header.get('parentSession') if target.header.get('origin') == 'subagent' else None
            if parent_id is not None:
                parent = ctx.get('sessions').get(parent_id)
                if parent is not None:
                    allowed = read_policy(projection, parent)
            elif target.firstLiveSeq == 0 and (target.eventAt(0) or {}).get('type') != 'session/end-seed':
                current = self.current()
                if current['enabled']:
                    allowed = current['allowedModels']
            if allowed is not UNDEFINED:
                target.append('subagent/model-selection-policy', dict(allowedModels=allowed))

        ctx.on('agent/created', created)
        await ready
        ctx.fiber.assert_active()
        Service(ctx, 'subagentModelSelection')
