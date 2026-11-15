"""Declarative preset definitions and reference-counted retained revisions."""
import asyncio
import math
import weakref
from functools import cmp_to_key
from types import SimpleNamespace as NS
from urllib.parse import urljoin
import yaml
from dsh.boot.compatibility_preflight import prepare_profile_entries
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import EntryTree, is_js_expr
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED as SCHEMA_UNDEFINED
from dsh.cordis.volatile import is_volatile
from dsh.core.scope import ScopeKey, create_scope, scope_of, scope_parent_of, bind_scope_parent
from dsh.presets.mount import leaked_services, mount_detail, _within_fiber
from dsh.typert.remote import TypertRemoteService, Remote, RemoteError
from dsh.cordis.plugin import Plugin
from dsh.session.icu_collation import locale_compare


def entry_list_problem(rows, at=''):
    if not isinstance(rows, list):
        return 'the composition must be a top-level list of plugin rows' if not at else 'group %s must hold a list of plugin rows' % at
    for index, row in enumerate(rows):
        label = ('row %s' if not at else at + ' row %s') % (index + 1)
        if not isinstance(row, dict):
            return label + ' is not a plugin row (expected a map with a "name")'
        if not isinstance(row.get('name'), str) or row['name'] == '':
            return label + ' names no plugin (a "name" string is required)'
        if row.get('group') is True:
            problem = entry_list_problem(row.get('config'), label)
            if problem is not None:
                return problem


def _preset_schema(value):
    if value is not None and not isinstance(value, str):
        raise TypeError('agent preset projection must be a string or null')
    return value


PRESET_PROJECTION = dict(key='agentPreset', stateVersion=1, stateSchema=_preset_schema,
    init=lambda header, cut: header.get('agentPreset'),
    apply=lambda state, event: event['data']['agentPreset'] if event['type'] == 'agent-preset/selected' else state,
    wire=dict(viewSchema=_preset_schema, view=lambda state: state))


class _PresetTree(EntryTree):
    def __init__(self, ctx):
        owner = getattr(ctx, '_loader_entry', None)
        old = getattr(owner, 'subtree', None)
        super().__init__(ctx)
        if owner is not None:
            owner.subtree = old
        self.builtins = ctx.get('loader').builtins

    def import_plugin(self, name, *args):
        base = getattr(self.ctx, 'baseUrl', None)
        if base and name.startswith(('./', '../')):
            name = urljoin(base, name)
        return self.ctx.get('loader').import_plugin(name)

    import_ = import_plugin

    def write(self):
        pass


async def audit_rows(tree):
    try:
        await tree.wait()
    except Exception:
        # The Python Loader aggregates failed fibers; report each entry below.
        pass
    failed, pending = [], []
    for entry in tree.entries():
        if entry.disabled:
            continue
        label = '%s (%s)' % (entry.options.get('id'), entry.options.get('name'))
        fiber = entry.fiber
        if fiber is None:
            failed.append(label + ': never started')
            continue
        try:
            await fiber
        except Exception as error:
            failed.append(label + ': ' + mount_detail(error))
            continue
        missing = [name for name in fiber.inject if fiber.ctx.get(name) is None]
        if missing:
            pending.append(label + ': waiting for ' + ', '.join(missing))
    return NS(failed=failed, pending=pending)


async def mount_preset(ctx, identity, plugins):
    if scope_of(ctx) is None:
        raise RuntimeError('agent-preset: mounting requires a scope')
    await ctx.fiber
    tree = _PresetTree(ctx)
    ctx.effect(lambda: tree.root.stop, 'agent-preset.tree')
    await tree.root.update(prepare_profile_entries(ctx, plugins, getattr(ctx, 'baseUrl', None)))
    audit = await audit_rows(tree)
    leaks = leaked_services(ctx, ctx.fiber)
    if audit.failed:
        raise RuntimeError('\n'.join(audit.failed))
    if leaks:
        raise RuntimeError('Preset services require isolate realms: ' + ', '.join(leaks))
    return NS(presetId=identity, fiber=ctx.fiber, tree=tree, key=scope_of(ctx))


def _declared_rows(plugins, outer=False):
    rows = []
    for row in plugins:
        disabled = row.get('disabled', False)
        own = 'conditional' if is_js_expr(disabled) else bool(disabled)
        effective = True if outer is True or own is True else 'conditional' if outer == 'conditional' or own == 'conditional' else False
        if row.get('group') is True:
            rows.extend(_declared_rows(row['config'], effective))
            continue
        value = dict(entryId=row.get('id') or None, moduleName=row['name'], enabled='conditional' if effective == 'conditional' else not effective)
        if is_js_expr(disabled):
            value['condition'] = disabled['__jsExpr']
        rows.append(value)
    return rows


class CurrentAgentPresetRegistry(TypertRemoteService):
    inject = ['loader', 'sessionProjections', 'agents']
    Config = Schema.object(dict(default=Schema.string().required(), selectedDefault=Schema.string().volatile()))

    def __init__(self, ctx, config):
        super().__init__(ctx, 'agentPresets')
        self.owner, self.config = ctx, config
        self.definitions, self.generations, self.bindings, self.switches = {}, {}, weakref.WeakKeyDictionary(), {}

    async def init(self):
        self.projection = await self.owner.get('sessionProjections').register(PRESET_PROJECTION)
        def settings(child):
            child.effect(lambda: child.get('settings').configure(dict(auto=False), self.owner.fiber))
        self.owner.inject(['settings'], settings)
        def event(session, value):
            if value['type'] == 'agent-preset/selected':
                self.owner.emit('agent-preset/selected', session.id, value['data']['agentPreset'])
        self.owner.on('session/event', event)

    @property
    def defaultId(self):
        selected = self.config.get('selectedDefault', SCHEMA_UNDEFINED)
        if is_volatile(selected):
            selected = selected.get()
        return self.config['default'] if selected is None or selected is SCHEMA_UNDEFINED else selected

    def presetForSession(self, session):
        return self.projection.stateOf(session)

    async def register(self, definition):
        identity = definition['id']
        if not identity.strip():
            raise RuntimeError('Preset id must not be empty')
        if identity in self.definitions:
            raise RuntimeError('Duplicate agent preset: ' + identity)
        record = NS(config=definition, context=self.ctx, ready=None, generation=None, broken=None)
        self.definitions[identity] = record
        disposed = False
        async def unregister():
            nonlocal disposed
            if disposed:
                return
            disposed = True
            self.definitions.pop(identity, None)
            await record.ready
            if record.generation is not None:
                record.generation.retired = True
                await self._collect(record.generation)
        record.ready = start_coroutine(self._activate(record))
        await record.ready
        return unregister

    async def _activate(self, record):
        key = ScopeKey({}); scope = create_scope(self.owner, key)
        try:
            problem = entry_list_problem(record.config['plugins'])
            if problem is not None:
                raise RuntimeError(problem)
            context = scope.ctx.extend(dict(baseUrl=getattr(record.context, 'baseUrl', None)))
            mount = await mount_preset(context, record.config['id'], record.config['plugins'])
            generation = NS(scope=scope, key=key, mount=mount, users=0, retired=False)
            def retain():
                self.generations[key] = generation
                return lambda: self.generations.pop(key, None)
            context.effect(retain, 'agent-preset.mount')
            record.generation = generation
        except Exception as error:
            record.broken = str(error)
            self.owner.logger.warn('agent preset %s: %s', record.config['id'], record.broken)
            await scope.dispose()

    async def _diagnostic(self, record):
        await record.ready
        if record.generation is None:
            return record.broken
        audit = await audit_rows(record.generation.mount.tree)
        if audit.pending:
            await self.owner.get('loader').wait()
            audit = await audit_rows(record.generation.mount.tree)
        return '\n'.join(audit.failed + audit.pending) or None

    async def _collect(self, generation):
        if generation.retired and generation.users == 0:
            self.generations.pop(generation.key, None)
            await generation.scope.dispose()

    def _generation_for(self, ctx):
        key = scope_of(ctx)
        return self.generations.get(scope_parent_of(key)) if key is not None else None

    def inspectCompositions(self, ctx=None):
        joined = self._generation_for(ctx) if ctx is not None else None
        generations = list(self.generations.values()) if ctx is None else [] if joined is None else [joined]
        rows = []
        for generation in generations:
            mount = generation.mount; modules = []
            for entry in mount.tree.entries():
                if entry.options.get('group') or entry.disabled or entry.fiber is None or entry.fiber.state != FiberState.ACTIVE:
                    continue
                value = dict(moduleName=entry.options['name'], useHostBase=entry.parent.tree is mount.tree)
                base = getattr(entry.parent.tree.ctx, 'baseUrl', None)
                if base is not None:
                    value['baseUrl'] = base
                modules.append(value)
            rows.append(dict(id=mount.presetId, modules=modules, leakedServices=leaked_services(self.owner, mount.fiber)))
        return rows

    async def list(self):
        rows = []
        for record in list(self.definitions.values()):
            broken = await self._diagnostic(record)
            value = {key: record.config[key] for key in ('id', 'name', 'description', 'order') if key in record.config}
            if broken is not None:
                value['broken'] = broken
            rows.append(value)
        def compare(left, right):
            a, b = left.get('order'), right.get('order')
            a = math.inf if a is None else a
            b = math.inf if b is None else b
            return (-1 if a < b else 1 if a > b else locale_compare(left['id'], right['id']))
        return sorted(rows, key=cmp_to_key(compare))

    @Remote('list')
    async def remoteExportList(self):
        identity = self.defaultId
        return dict(presets=[dict(row, isDefault=row['id'] == identity) for row in await self.list()])

    def _not_found(self, identity):
        return RemoteError('agent-preset/not-found', 'Unknown agent preset: ' + identity,
            dict(agentPreset=identity, available=list(self.definitions)))

    async def resolve(self, identity=None):
        wanted = self.defaultId if identity is None else identity
        record = self.definitions.get(wanted)
        if record is None:
            raise self._not_found(wanted)
        broken = await self._diagnostic(record)
        return dict(id=wanted, **(dict(broken=broken) if broken is not None else {}))

    @Remote('read')
    async def readDocument(self, agentPreset):
        record = self.definitions.get(agentPreset)
        if record is None:
            raise self._not_found(agentPreset)
        value = dict(agentPreset=agentPreset, content=yaml.safe_dump(record.config['plugins'], allow_unicode=True, sort_keys=False, width=2147483647))
        value.update({key: record.config[key] for key in ('name', 'description') if key in record.config})
        return value

    async def _retain(self, identity=None):
        wanted = self.defaultId if identity is None else identity
        while True:
            record = self.definitions.get(wanted)
            if record is None:
                raise self._not_found(wanted)
            broken = await self._diagnostic(record)
            if self.definitions.get(wanted) is not record:
                continue
            if broken is not None or record.generation is None:
                raise RemoteError('agent-preset/invalid', broken, dict(agentPreset=wanted, reason=broken))
            record.generation.users += 1
            return record.generation

    def _join(self, ctx, key, generation):
        binding = NS(parent=bind_scope_parent(key, generation.key), generation=generation)
        generation.users += 1; self.bindings[key] = binding
        async def release():
            self.bindings.pop(key, None)
            binding.generation.users -= 1
            await self._collect(binding.generation)
        ctx.effect(lambda: release, 'agent-preset.binding')

    async def _bind(self, ctx, generation):
        key = scope_of(ctx)
        if key is None:
            raise RuntimeError('Agent preset binding requires a scoped context')
        binding = self.bindings.get(key)
        if binding is not None and binding.generation is generation:
            return
        if binding is None:
            self._join(ctx, key, generation)
        else:
            binding.parent.rebind(generation.key)
            old = binding.generation; generation.users += 1; binding.generation = generation; old.users -= 1
            await self._collect(old)

    async def mount(self, ctx, identity=None):
        generation = await self._retain(identity)
        try:
            await self._bind(ctx, generation)
            return dict(id=generation.mount.presetId)
        finally:
            generation.users -= 1
            await self._collect(generation)

    def composeFrom(self, ctx, parent):
        generation = self._generation_for(parent)
        if generation is None:
            presets = parent.get('agentPresets')
            if presets is not None and presets.composedPreset(parent) is not None:
                raise RuntimeError('Parent preset revision is unavailable')
            return None
        key = scope_of(ctx)
        if key is None:
            raise RuntimeError('Child preset binding requires a scope')
        if key in self.bindings:
            raise RuntimeError('Child already joined a preset')
        self._join(ctx, key, generation)
        return generation.mount.presetId

    def composedPreset(self, ctx):
        generation = self._generation_for(ctx)
        return None if generation is None else generation.mount.presetId

    def serviceFor(self, agent, name):
        generation = self._generation_for(agent.ctx)
        if generation is not None:
            for impl in list(self.owner.reflect.store.values()):
                if impl.name == name and _within_fiber(impl.fiber, generation.mount.fiber):
                    return impl.value

    async def recompose(self, ctx, identity):
        preset = await self.mount(ctx, identity)
        try:
            self.owner.emit('tools/change')
        except Exception as error:
            self.owner.logger.warn('Preset tools observer: %s', error)
        return preset

    @Remote('select')
    async def select(self, agent, agentPreset):
        previous = self.switches.get(agent.id)
        async def switch():
            if previous is not None:
                await previous
            boundary = self.owner.get('agents').turnBoundaryOf(agent.session)
            if boundary['openTurnStartSeq'] is not None or boundary['lastTurn'] > 0:
                raise RemoteError('agent-preset/locked', 'This session has already started', dict(sessionId=agent.id, agentPreset=agentPreset))
            record = self.definitions.get(agentPreset); current = record.generation if record is not None else None
            if current is not None and self._generation_for(agent.ctx) is current and self.projection.stateOf(agent.session) == agentPreset:
                return agentPreset
            preset = await self.recompose(agent.ctx, agentPreset)
            agent.session.append('agent-preset/selected', dict(agentPreset=preset['id']))
            return preset['id']
        task = start_coroutine(switch())
        async def guard():
            try:
                await task
            except Exception:
                pass
        guarded = start_coroutine(guard()); self.switches[agent.id] = guarded
        try:
            return await task
        finally:
            if self.switches.get(agent.id) is guarded:
                self.switches.pop(agent.id, None)

    async def acquireScope(self, identity=None):
        generation = await self._retain(identity); disposed = False
        async def dispose():
            nonlocal disposed
            if not disposed:
                disposed = True; generation.users -= 1
                await self._collect(generation)
        return NS(key=generation.key, dispose=dispose)

    async def compositionInventory(self):
        result = []
        for record in list(self.definitions.values()):
            value = {key: record.config[key] for key in ('id', 'name', 'description') if key in record.config}
            value['isDefault'] = record.config['id'] == self.defaultId
            broken = await self._diagnostic(record)
            if broken is not None:
                value['broken'] = broken
            if record.generation is None:
                value['rows'] = [] if entry_list_problem(record.config['plugins']) is not None else _declared_rows(record.config['plugins'])
            else:
                value['rows'] = []
                for entry in record.generation.mount.tree.entries():
                    if entry.options.get('group'):
                        continue
                    row = dict(entryId=entry.id, moduleName=entry.options['name'], enabled=not entry.disabled)
                    if is_js_expr(entry.options.get('disabled')):
                        row['condition'] = entry.options['disabled']['__jsExpr']
                    if entry.fiber is not None:
                        row['fiberState'] = entry.fiber.state.value if hasattr(entry.fiber.state, 'value') else entry.fiber.state
                    value['rows'].append(row)
            result.append(value)
        return result


class CurrentAgentPreset(Plugin):
    """A Loader carrier: child expressions belong to the activated preset tree."""
    inject = ['agentPresets']
    _cordis_entry_group = True
    Config = Schema.object(dict(id=Schema.string().required(), name=Schema.string(),
        description=Schema.string(), order=Schema.number(), plugins=Schema.array(Schema.any()).required()))

    async def apply(self, ctx):
        unregister = await ctx.get('agentPresets').register(self.config)
        return lambda: start_coroutine(unregister())
