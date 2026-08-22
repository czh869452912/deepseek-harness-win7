"""
User-facing permission presets over sandbox-mode and approval-policy knobs.
Aligned 1:1 with official `@deepseek-ai/dsh-permission-presets`.
"""

import os
from typing import Any, Callable, Dict, List, Optional, Union
from dsh.cordis.plugin import Plugin


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


class PermissionPresetService:
    """
    Owns the deployment's permission presets and their write path.
    Mounted at `ctx.permissionPresets`.
    """

    def __init__(self, ctx: Any, presets: Optional[Dict[str, Dict[str, Any]]] = None, default_preset: Optional[str] = None):
        self.ctx = ctx
        self.presets = presets if presets is not None else dict(DEFAULT_PRESETS)
        if CUSTOM_PRESET in self.presets:
            raise ValueError(f'permission: "{CUSTOM_PRESET}" is reserved for the derived not-a-preset state')

        self.default_preset_name = default_preset or "workspace-write"

        projections = ctx.get("sessionProjections") if ctx else None
        if projections and hasattr(projections, "register"):
            projections.register(
                key="permissions",
                schema=None,
                init=lambda: dict(EMPTY_KNOBS),
                apply=apply_knob_event,
                view=lambda state: self.selectFor(state),
                state_version=1,
            )

        commands = ctx.get("commands") if ctx else None
        if commands and hasattr(commands, "register"):
            commands.register({
                "name": "permission",
                "description": "Switch the permission preset (sandbox mode + approval policy)",
                "input": {"hint": "<preset>"},
                "handler": self._command_handler,
            })

        if ctx and hasattr(ctx, "on"):
            ctx.on("session/created", self.pin_initial_permission)
            sessions = ctx.get("sessions")
            if sessions and hasattr(sessions, "list"):
                for sess in sessions.list():
                    self.pin_initial_permission(sess)

    @property
    def names(self) -> List[str]:
        return list(self.presets.keys())

    @property
    def defaultPreset(self) -> str:
        return self.default_preset_name

    @property
    def default_preset(self) -> str:
        return self.default_preset_name

    def current(self, events: List[Dict[str, Any]]) -> str:
        return self.derive(fold_knobs(events))

    def derive(self, state: Dict[str, Optional[str]]) -> str:
        shell = self.ctx.get("shell") if self.ctx else None
        approval = self.ctx.get("approval") if self.ctx else None

        sandbox = state.get("sandbox") or (getattr(shell, "sandboxMode", "workspace-write") if shell else "workspace-write")
        policy = state.get("approval") or (getattr(approval, "policy", "ask") if approval else "ask")

        def matches(spec: Dict[str, Any]) -> bool:
            return spec.get("sandbox") == sandbox and spec.get("approval") == policy

        st_preset = state.get("preset")
        if st_preset and st_preset in self.presets and matches(self.presets[st_preset]):
            return st_preset

        for name, spec in self.presets.items():
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
            raise ValueError(f'permission: unknown preset "{name}" (known: {", ".join(self.names)})')
        return spec

    def optionOf(self, name: str) -> Dict[str, Any]:
        if name == CUSTOM_PRESET:
            return {
                "value": CUSTOM_PRESET,
                "name": "Custom",
                "description": "Current sandbox and approval settings do not match a preset.",
            }
        spec = self.resolve(name)
        res = {"value": name, "name": spec.get("name", name)}
        if "description" in spec:
            res["description"] = spec["description"]
        return res

    def option_of(self, name: str) -> Dict[str, Any]:
        return self.optionOf(name)

    def set(self, session: Any, name: str) -> None:
        self.apply(session, name)

    def apply(self, session: Any, name: str) -> None:
        spec = self.resolve(name)
        events = getattr(session, "events", [])
        if self.current(events) != name:
            session.append("permission/preset", {"preset": name})

        approval_svc = self.ctx.get("approval") if self.ctx else None
        if approval_svc and hasattr(approval_svc, "set_policy"):
            agent = getattr(session, "owner", None)
            if agent:
                approval_svc.set_policy(agent, spec.get("approval", "ask"))
            elif hasattr(approval_svc, "policy"):
                approval_svc.policy = spec.get("approval", "ask")

    def pin_initial_permission(self, session: Any) -> None:
        events = getattr(session, "events", [])
        selected = effective_permission_preset(events)
        if selected is None:
            name = self.default_preset_name
            spec = self.resolve(name)
            session.append("permission/preset", {"preset": name})
            approval_svc = self.ctx.get("approval") if self.ctx else None
            if approval_svc and hasattr(approval_svc, "policy"):
                approval_svc.policy = spec.get("approval", "ask")

    def _command_handler(self, invocation_or_input: Any) -> Dict[str, Any]:
        if hasattr(invocation_or_input, "rawInput"):
            raw = invocation_or_input.rawInput.strip()
            agent = invocation_or_input.agent
            session = getattr(agent, "session", None) if agent else None
        else:
            raw = str(invocation_or_input).strip()
            session = None

        if not raw:
            curr = self.current(getattr(session, "events", [])) if session else self.default_preset_name
            return {"kind": "success", "text": f"current preset {curr} (available: {', '.join(self.names)})"}

        if raw not in self.names:
            return {"kind": "error", "text": f'unknown preset "{raw}" (available: {", ".join(self.names)})'}

        if session:
            self.apply(session, raw)

        return {"kind": "success", "text": f"preset {raw}"}


class PermissionPresetsPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-permission-presets`: Configures permission presets.
    """

    id = "permission"
    name = "@deepseek-ai/dsh-permission-presets"

    def apply(self, ctx: Any) -> None:
        mode = os.environ.get("DSH_PERMISSION_MODE") or self.config.get("mode", "workspace-write")
        presets_cfg = self.config.get("presets")
        service = PermissionPresetService(ctx, presets=presets_cfg, default_preset=mode)
        ctx.set_service("permissionPresets", service)
