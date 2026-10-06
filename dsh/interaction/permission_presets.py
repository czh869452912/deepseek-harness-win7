"""
User-facing permission presets over sandbox-mode and approval-policy knobs.
Aligned 1:1 with official `@deepseek-ai/dsh-permission-presets`.
"""

import copy
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _js_own_key_order
from dsh.interaction.user_approval import effective_approval_policy, set_approval_policy
from dsh.sandbox.sandbox_policy import effective_sandbox_mode, set_sandbox_mode
from dsh.settings import install_settings_section


CUSTOM_PRESET = "custom"

DEFAULT_PRESETS: Dict[str, Dict[str, Any]] = {
    "workspace-write": {
        "sandbox": "workspace-write",
        "approval": "ask",
        "name": "workspace-write",
        "description": "Write inside the workspace and permitted temporary directories; wider retries require approval.",
    },
    "danger-full-access": {
        "sandbox": "danger-full-access",
        "approval": "never",
        "name": "danger-full-access",
        "description": "Full file access without approval prompts.",
    },
}


def effective_permission_preset(events: List[Dict[str, Any]]) -> Optional[str]:
    """
    Fold the last selected preset from the durable log.
    """
    for event in reversed(events):
        if event.get("type") == "permission/preset":
            return event.get("data", {}).get("preset")
    return None


effectivePermissionPreset = effective_permission_preset

EMPTY_KNOBS: Dict[str, Optional[str]] = {"preset": None, "sandbox": None, "approval": None}


def apply_knob_event(state: Dict[str, Optional[str]], event: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    One-event knob transition for permissions projection unit.
    """
    etype = event.get("type")
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    if etype == "permission/preset":
        return {**state, "preset": data.get("preset")}
    elif etype == "sandbox/mode":
        return {**state, "sandbox": data.get("mode")}
    elif etype == "approval/policy":
        return {**state, "approval": data.get("policy")}
    return state


applyKnobEvent = apply_knob_event


def fold_knobs(events: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    state = dict(EMPTY_KNOBS)
    for event in events:
        state = apply_knob_event(state, event)
    return state


class PermissionPresetError(ValueError):
    name = 'Error'


class PermissionPresetService:
    """
    Owns the deployment's permission presets and their write path.
    Mounted at `ctx.permissionPresets`.
    """

    def __init__(self, ctx: Any, presets: Optional[Dict[str, Dict[str, Any]]] = None, default_preset: Optional[str] = None):
        self.ctx = ctx
        self.presets = copy.deepcopy(presets if presets is not None else DEFAULT_PRESETS)
        if CUSTOM_PRESET in self.presets:
            raise PermissionPresetError('permission: "custom" is reserved for the derived not-a-preset state and cannot name a table entry')
        shell = ctx.get('shell')
        if shell is None or getattr(shell, 'sandboxMode', None) is None:
            raise PermissionPresetError('permission: the mounted bash executor does not confine (no sandboxMode) — presets bundle a sandbox mode, so composing this plugin over an unconfined executor is a misconfiguration')
        inferred = self.derive(EMPTY_KNOBS)
        selected = default_preset if default_preset is not None else inferred
        if selected == CUSTOM_PRESET:
            raise PermissionPresetError('permission: composed sandbox and approval defaults match no preset; configure defaultPreset explicitly')
        self.resolve(selected)
        base = dict(defaultPreset=selected)
        self.default_settings = lambda: base
        choices = []
        for name in self.names:
            choice = Schema.const_(name)
            label = self.presets[name].get('name')
            choices.append(choice.description(label) if label is not None else choice)
        settings_schema = Schema.object({'defaultPreset': Schema.union(choices).required()})
        install_settings_section(ctx, 'permission', settings_schema, base,
            dict(setSource=self._set_settings_source, onChange=lambda: None))
        ctx.on('session/created', self.pin_initial_permission)
        for session in ctx.get('sessions').list():
            self.pin_initial_permission(session)

        def projections(scope):
            scope.get('sessionProjections').register(dict(key='permissions',
                stateSchema=self._state, init=lambda header: dict(EMPTY_KNOBS), apply=apply_knob_event,
                wire=dict(viewSchema=self._select, view=self.selectFor), stateVersion=1))

        def commands(scope):
            scope.get('commands').register(dict(name='permission',
                description='Switch the permission preset (sandbox mode + approval policy)',
                input=dict(hint='<preset>'), handler=self._command_handler))

        ctx.inject(['sessionProjections'], projections)
        ctx.inject(['commands'], commands)

    def _set_settings_source(self, source):
        self.default_settings = source

    @staticmethod
    def _state(value):
        if not isinstance(value, dict) or set(value) != set(EMPTY_KNOBS):
            raise ValueError('invalid permission knob state')
        if any(selected is not None and not isinstance(selected, str) for selected in value.values()):
            raise ValueError('invalid permission knob value')
        if value['sandbox'] not in (None, 'read-only', 'workspace-write', 'danger-full-access'):
            raise ValueError('invalid permission sandbox mode')
        if value['approval'] not in (None, 'ask', 'never'):
            raise ValueError('invalid permission approval policy')
        return dict(value)

    @staticmethod
    def _select(value):
        if not isinstance(value, dict) or not isinstance(value.get('currentValue'), str) or not value['currentValue'] or not isinstance(value.get('options'), list):
            raise ValueError('invalid permission select')
        for option in value['options']:
            if not isinstance(option, dict) or any(not isinstance(option.get(key), str) or not option[key] for key in ('value', 'name')) or ('description' in option and not isinstance(option['description'], str)):
                raise ValueError('invalid permission option')
        options = []
        for option in value['options']:
            selected = {key: option[key] for key in ('value', 'name')}
            if 'description' in option:
                selected['description'] = option['description']
            options.append(selected)
        return dict(options=options, currentValue=value['currentValue'])

    @property
    def names(self) -> List[str]:
        return _js_own_key_order(list(self.presets.keys()))

    @property
    def defaultPreset(self) -> str:
        return self.default_settings()['defaultPreset']

    @property
    def default_preset(self) -> str:
        return self.default_settings()['defaultPreset']

    def current(self, events: List[Dict[str, Any]]) -> str:
        return self.derive(fold_knobs(events))

    def derive(self, state: Dict[str, Optional[str]]) -> str:
        shell = self.ctx.get('shell')
        approval = self.ctx.get('approval')
        sandbox = state.get('sandbox') if state.get('sandbox') is not None else shell.sandboxMode
        policy = state.get('approval') if state.get('approval') is not None else approval.config.get('policy')
        if policy is None:
            policy = 'ask'

        def matches(spec: Dict[str, Any]) -> bool:
            return spec.get("sandbox") == sandbox and spec.get("approval") == policy

        st_preset = state.get("preset")
        if st_preset is not None and st_preset in self.presets and matches(self.presets[st_preset]):
            return st_preset

        for name in self.names:
            spec = self.presets[name]
            if matches(spec):
                return name
        return CUSTOM_PRESET

    def selectFor(self, state: Dict[str, Optional[str]]) -> Dict[str, Any]:
        curr = self.derive(state)
        options = [self.optionOf(name) for name in self.names]
        if curr == CUSTOM_PRESET:
            options.append(self.optionOf(CUSTOM_PRESET))
        return {
            "options": options,
            "currentValue": curr,
        }

    def select_for(self, state: Dict[str, Optional[str]]) -> Dict[str, Any]:
        return self.selectFor(state)

    def resolve(self, name: str) -> Dict[str, Any]:
        spec = self.presets.get(name)
        if spec is None:
            raise PermissionPresetError(f'permission: unknown preset "{name}" (known: {", ".join(self.names)})')
        return spec

    def optionOf(self, name: str) -> Dict[str, Any]:
        if name == CUSTOM_PRESET:
            return {
                "value": CUSTOM_PRESET,
                "name": "Custom",
                "description": "Current sandbox and approval settings do not match a preset.",
            }
        spec = self.resolve(name)
        res = {"value": name, "name": spec["name"] if spec.get("name") is not None else name}
        if "description" in spec:
            res["description"] = spec["description"]
        return res

    def option_of(self, name: str) -> Dict[str, Any]:
        return self.optionOf(name)

    def set(self, session: Any, name: str) -> None:
        self.apply(session, name, lambda policy: set_approval_policy(session, policy))

    def apply(self, session: Any, name: str, set_approval=None) -> None:
        spec = self.resolve(name)
        if self.current(session.events) != name:
            session.append('permission/preset', dict(preset=name))
        sandbox = effective_sandbox_mode(session.events)
        if sandbox is None:
            sandbox = self.ctx.get('shell').sandboxMode
        if spec['sandbox'] != sandbox:
            set_sandbox_mode(session, spec['sandbox'])
        policy = effective_approval_policy(session.events)
        if policy is None:
            policy = self.ctx.get('approval').config.get('policy')
        if policy is None:
            policy = 'ask'
        if spec['approval'] != policy:
            (set_approval or (lambda value: set_approval_policy(session, value)))(spec['approval'])

    def pin_initial_permission(self, session: Any) -> None:
        events = session.events
        selected = effective_permission_preset(events)
        sandbox = effective_sandbox_mode(events)
        approval = effective_approval_policy(events)
        seeded = any(event['type'] == 'session/end-seed' for event in events)
        if selected is None and sandbox is None and approval is None and not seeded:
            name = self.defaultPreset
            spec = self.resolve(name)
            session.append('permission/preset', dict(preset=name))
            set_sandbox_mode(session, spec['sandbox'])
            set_approval_policy(session, spec['approval'])
            return
        effective = self.derive(dict(preset=selected, sandbox=sandbox, approval=approval))
        if selected is None and effective != CUSTOM_PRESET:
            session.append('permission/preset', dict(preset=effective))
        if sandbox is None:
            set_sandbox_mode(session, self.ctx.get('shell').sandboxMode)
        if approval is None:
            policy = self.ctx.get('approval').config.get('policy')
            set_approval_policy(session, policy if policy is not None else 'ask')

    def _command_handler(self, invocation: Any) -> Dict[str, Any]:
        name = invocation.rawInput.strip()
        agent = invocation.agent
        if not name:
            return dict(kind='success', text='current preset %s (available: %s)' % (self.current(agent.session.events), ', '.join(self.names)))
        if name not in self.names:
            return dict(kind='error', text='unknown preset "%s" (available: %s)' % (name, ', '.join(self.names)))
        self.apply(agent.session, name, lambda policy: self.ctx.get('approval').set_policy(agent, policy))
        return dict(kind='success', text='preset ' + name)


class PermissionPresetsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-permission-presets`: Configures permission presets.
    """

    id = "permission"
    name = "@deepseek-ai/dsh-permission-presets"
    inject = ['shell', 'approval', 'sessions']
    Config = Schema.object({'presets': Schema.dict(Schema.object({
        'sandbox': Schema.union(['read-only', 'workspace-write', 'danger-full-access']).required(),
        'approval': Schema.union(['ask', 'never']).required(), 'name': Schema.string(), 'description': Schema.string(),
    })).default(DEFAULT_PRESETS), 'defaultPreset': Schema.string()})

    def apply(self, ctx: Any) -> None:
        mode = self.config.get("defaultPreset")
        presets_cfg = self.config.get("presets")
        service = PermissionPresetService(ctx, presets=presets_cfg, default_preset=mode)
        ctx.set_service("permissionPresets", service)
