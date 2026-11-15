"""Current process permission catalog and session-only durable selection."""
import asyncio
import copy
import inspect

from dsh.cordis.schema import Schema
from dsh.cordis.text import trim_js
from dsh.cordis.utils import _UNDEFINED, _js_own_key_order, js_to_string
from dsh.cordis.volatile import is_volatile
from dsh.jobs.pump import field
from dsh.typert.remote import TypertRemoteService, Remote
from .permission_presets import (PermissionPresetService, PermissionPresetError,
    DEFAULT_PRESETS, EMPTY_KNOBS, CUSTOM_PRESET, apply_knob_event)
from .user_approval import set_approval_policy
from dsh.sandbox.sandbox_policy import set_sandbox_mode

AUTO_PRESET = 'auto'
AUTO_SPEC = dict(sandbox='danger-full-access', approval='ask')


class CurrentPermissionPresets(TypertRemoteService):
    inject = ['shell', 'approval', 'sessions', 'agents', 'sessionProjections']
    Config = Schema.object(dict(presets=Schema.dict(Schema.object(dict(
        sandbox=Schema.union('read-only','workspace-write','danger-full-access').required(),
        approval=Schema.union('ask','never').required(), name=Schema.string(), description=Schema.string()))).default(DEFAULT_PRESETS),
        defaultPreset=Schema.string().volatile()))

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'permissionPresets')
        config = config or {}
        self.presets = copy.deepcopy(config.get('presets', DEFAULT_PRESETS))
        self.auto_admit = None
        self.projection = None
        self.default_ref = config.get('defaultPreset', _UNDEFINED)
        if CUSTOM_PRESET in self.presets:
            raise PermissionPresetError('permission: "custom" is reserved for the derived not-a-preset state and cannot name a table entry')
        if AUTO_PRESET in self.presets:
            raise PermissionPresetError('permission: "auto" is reserved and cannot name a configured preset')
        if getattr(ctx.shell, 'sandboxMode', None) is None:
            raise PermissionPresetError('permission: the mounted bash executor does not confine (no sandboxMode) — presets bundle a sandbox mode, so composing this plugin over an unconfined executor is a misconfiguration')
        self.inferred_default = self.derive(EMPTY_KNOBS)
        selected = self._configured_default()
        if selected == CUSTOM_PRESET:
            raise PermissionPresetError('permission: composed sandbox and approval defaults match no preset; configure defaultPreset explicitly')
        self.resolve(selected)
        def configure(child):
            child.effect(lambda: child.settings.configure(dict(auto=False), ctx.fiber))
        ctx.inject(['settings'], configure)

    def _configured_default(self):
        value = self.default_ref.get() if is_volatile(self.default_ref) else self.default_ref
        return self.inferred_default if value is _UNDEFINED or value is None else value

    @property
    def defaultPreset(self):
        name = self._configured_default()
        if name not in self.presets: raise PermissionPresetError('permission: unknown default preset "'+name+'"')
        return name

    @property
    def names(self): return _js_own_key_order(list(self.presets))+([AUTO_PRESET] if self.auto_admit is not None else [])

    async def init(self):
        ctx = self.ctx
        ctx.on('agent/created', lambda payload:self.pin_initial_permission(field(payload,'agent').session), prepend=True)
        self.projection = await ctx.sessionProjections.register(dict(key='permissions', stateVersion=2,
            stateSchema=PermissionPresetService._state, init=lambda *_:dict(EMPTY_KNOBS, seeded=False), apply=apply_knob_event,
            wire=dict(viewSchema=self._selection, view=lambda state:dict(currentValue=self.derive(state)))))
        for agent in ctx.agents.list(): self.pin_initial_permission(agent.session)
        def commands(child):
            child.commands.register(dict(definitionId='@deepseek-ai/dsh-permission-presets', name='permission',
                description='Switch the permission preset (sandbox mode + approval policy)', input=dict(hint='<preset>'), handler=self._command_handler))
        ctx.inject(['commands'], commands)

    @staticmethod
    def _selection(value):
        if not isinstance(value, dict) or not isinstance(value.get('currentValue'), str) or not value['currentValue']:
            raise ValueError('invalid permission selection')
        return dict(currentValue=value['currentValue'])

    def permission_state(self, session):
        if self.projection is None:
            raise PermissionPresetError('permission: presets are not ready; await plugin activation before creating or restoring a session')
        return self.projection.stateOf(session)

    def current(self, session): return self.derive(self.permission_state(session))

    def _spec(self, name):
        return self.presets.get(name, AUTO_SPEC if name == AUTO_PRESET and self.auto_admit is not None else None)

    def derive(self, state):
        sandbox = state.get('sandbox') if state.get('sandbox') is not None else self.ctx.shell.sandboxMode
        approval = state.get('approval') if state.get('approval') is not None else self.ctx.approval.config.get('policy') or 'ask'
        def matches(spec):return spec['sandbox'] == sandbox and spec['approval'] == approval
        name = state.get('preset')
        if name is not None:
            spec = self._spec(name)
            if spec is not None and matches(spec): return name
            if name == AUTO_PRESET and spec is not None and spec['sandbox'] == sandbox and approval == 'never': return AUTO_PRESET
        for name in _js_own_key_order(list(self.presets)):
            if matches(self.presets[name]): return name
        return CUSTOM_PRESET

    def resolve(self, name):
        spec = self._spec(name)
        if spec is None: raise PermissionPresetError('permission: unknown preset "'+name+'" (known: '+', '.join(self.names)+')')
        return spec

    optionOf = PermissionPresetService.optionOf

    @Remote('catalog')
    def catalog(self):
        return dict(options=[self.optionOf(name) for name in self.names],
                    defaultOptions=[self.optionOf(name) for name in _js_own_key_order(list(self.presets))], defaultPreset=self.defaultPreset)

    def registerAuto(self, admit):
        def setup():
            if self.auto_admit is not None: raise PermissionPresetError('permission: preset "auto" is already registered')
            self.auto_admit = admit
            self._catalog_changed()
            def dispose():
                self.auto_admit = None
                self._catalog_changed()
            return dispose
        return self.ctx.effect(setup, label='permissionPresets.registerAuto()')

    def _catalog_changed(self):
        def warn(error):self.ctx.logger.warn('permission: catalog-changed listener failed: '+(getattr(error,'message',str(error)) if isinstance(error,BaseException) else js_to_string(error)))
        async def observe(awaitable):
            try: await awaitable
            except Exception as error: warn(error)
        for listener in self.ctx.events.dispatch('emit', ['permission-presets/catalog-changed']):
            try:
                result = listener()
                if inspect.isawaitable(result): asyncio.ensure_future(observe(result))
            except Exception as error: warn(error)

    def set(self, session, name): self.apply(session, name, lambda policy:set_approval_policy(session, policy))

    def apply(self, session, name, set_approval):
        spec = self.resolve(name)
        if name == AUTO_PRESET and self.auto_admit is not None: self.auto_admit()
        current = self.current(session)
        state = self.permission_state(session)
        if current != name: session.append('permission/preset', dict(preset=name))
        if spec['sandbox'] != (state['sandbox'] if state['sandbox'] is not None else self.ctx.shell.sandboxMode): set_sandbox_mode(session, spec['sandbox'])
        if spec['approval'] != (state['approval'] if state['approval'] is not None else self.ctx.approval.config.get('policy') or 'ask'): set_approval(spec['approval'])

    def pin_initial_permission(self, session):
        state = self.permission_state(session)
        if state['preset'] == AUTO_PRESET:
            if self.auto_admit is None: raise PermissionPresetError('permission: cannot restore preset "auto" without its active integration')
            self.auto_admit()
        if all(state[key] is None for key in EMPTY_KNOBS) and not state['seeded']:
            name = self.defaultPreset; spec = self.resolve(name)
            session.append('permission/preset', dict(preset=name))
            set_sandbox_mode(session, spec['sandbox']);set_approval_policy(session, spec['approval'])
            return
        effective = self.derive(state)
        if state['preset'] is None and effective != CUSTOM_PRESET: session.append('permission/preset', dict(preset=effective))
        if state['sandbox'] is None: set_sandbox_mode(session, self.ctx.shell.sandboxMode)
        if state['approval'] is None: set_approval_policy(session, self.ctx.approval.config.get('policy') or 'ask')

    def _command_handler(self, invocation):
        name = trim_js(invocation.rawInput);agent = invocation.agent
        if not name: return dict(kind='success', text='current preset '+self.current(agent.session)+' (available: '+', '.join(self.names)+')')
        if name not in self.names: return dict(kind='error', text='unknown preset "'+name+'" (available: '+', '.join(self.names)+')')
        def approval(policy):
            service = self.ctx.approval
            setter = getattr(service, 'setPolicy', None) or service.set_policy
            setter(agent, policy)
        self.apply(agent.session, name, approval)
        return dict(kind='success', text='preset '+name)
