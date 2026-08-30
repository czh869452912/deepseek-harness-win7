"""
Default model selection for an Agent without a session-specific selection.
1:1 aligned with official `@deepseek-ai/dsh-agent-default-model`.
"""

from typing import Any, Dict, Optional, Union
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.model_selection import ModelSelection


AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE = "agent-default-model"


class AgentDefaultModelConfig:
    """
    Owns the default model selection independently of any Host or transport.
    """

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        self.ctx = ctx
        cfg = config or {}
        self._provider = str(cfg.get("provider", "deepseek"))
        self._model = str(cfg.get("model", "deepseek-chat"))
        self._reasoning_effort: Optional[str] = cfg.get("reasoningEffort") or cfg.get("reasoning_effort")

    def current_selection(self) -> Dict[str, Any]:
        """Read current default model selection."""
        settings = self.ctx.get("settings")
        if settings and hasattr(settings, "get"):
            doc = settings.get(AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE)
            if isinstance(doc, dict):
                res: Dict[str, Any] = {
                    "provider": doc.get("provider", self._provider),
                    "model": doc.get("model", self._model),
                }
                eff = doc.get("reasoningEffort") or doc.get("reasoning_effort")
                if eff is not None:
                    res["reasoningEffort"] = eff
                return res

        res = {
            "provider": self._provider,
            "model": self._model,
        }
        if self._reasoning_effort is not None:
            res["reasoningEffort"] = self._reasoning_effort
        return res

    def currentSelection(self) -> Dict[str, Any]:
        return self.current_selection()

    async def save_selection(self, next_sel: Union[ModelSelection, Dict[str, Any]]) -> None:
        """Save complete default model selection to settings."""
        if isinstance(next_sel, ModelSelection):
            payload = next_sel.to_dict()
        else:
            payload = dict(next_sel)

        prov = payload.get("provider", self._provider)
        mod = payload.get("model", self._model)
        eff = payload.get("reasoningEffort") or payload.get("reasoning_effort")

        self._provider = prov
        self._model = mod
        self._reasoning_effort = eff

        settings = self.ctx.get("settings")
        if settings and hasattr(settings, "replace"):
            save_dict: Dict[str, Any] = {"provider": prov, "model": mod}
            if eff is not None:
                save_dict["reasoningEffort"] = eff
            await settings.replace(AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE, save_dict)

    async def saveSelection(self, next_sel: Union[ModelSelection, Dict[str, Any]]) -> None:
        await self.save_selection(next_sel)


class AgentDefaultModelPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-agent-default-model`.
    """

    id = "agent-default-model"
    name = "@deepseek-ai/dsh-agent-default-model"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def apply(self, ctx: Context) -> None:
        config_inst = AgentDefaultModelConfig(ctx, self.config)
        ctx.set_service("agent_default_model", config_inst)
        ctx.set_service("agentDefaultModel", config_inst)
