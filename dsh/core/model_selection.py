"""
Agent-scoped model selection shared by runtime entry points.
Aligned 1:1 with official `@deepseek-ai/dsh-agent/model-selection`.
"""

import inspect

from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.context import Context
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema as z
from dsh.settings.provider import install_settings_section
from dsh.settings.types import settings_namespace


AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE = settings_namespace("agent-default-model")


AGENT_DEFAULT_MODEL_SETTINGS_SCHEMA = z.object({
    "provider": z.string().required(),
    "model": z.string().required(),
    "reasoningEffort": z.string(),
})

class AgentDefaultModelConfig(Service):
    """Default Agent model selection layered over the optional settings service."""

    Config = z.object({"provider": z.string().required(), "model": z.string().required()})

    def __init__(self, ctx: Context, config: Dict[str, Any]):
        super().__init__(ctx, "agentDefaultModel")
        entry = {"provider": config["provider"], "model": config["model"]}
        self._source = lambda: entry

        def set_source(source: Callable[[], Dict[str, Any]]) -> None:
            self._source = source

        install_settings_section(
            ctx,
            AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE,
            AGENT_DEFAULT_MODEL_SETTINGS_SCHEMA,
            entry,
            {"setSource": set_source, "onChange": lambda: None},
        )

    def current_selection(self) -> Dict[str, Any]:
        settings = self._source()
        result = {"provider": settings["provider"], "model": settings["model"]}
        if "reasoningEffort" in settings:
            result["reasoningEffort"] = settings["reasoningEffort"]
        return result

    def currentSelection(self) -> Dict[str, Any]:
        return self.current_selection()

    async def save_selection(self, next_selection: Any) -> None:
        settings = self.ctx.get("settings", None)
        if settings is None:
            return
        if isinstance(next_selection, ModelSelection):
            value = next_selection.to_dict()
        else:
            value = next_selection
        section = {"provider": value["provider"], "model": value["model"]}
        if value.get("reasoningEffort") is not None:
            section["reasoningEffort"] = str(value["reasoningEffort"])
        result = settings.replace(AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE, section)
        if inspect.isawaitable(result):
            await result

    async def saveSelection(self, next_selection: Any) -> None:
        await self.save_selection(next_selection)


class ModelSelection:
    """Complete provider, model, and optional reasoning effort selected for one live Agent."""

    def __init__(
        self,
        provider: str,
        model: str,
        reasoning_effort: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.reasoning_effort = reasoning_effort

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
        }
        if self.reasoning_effort is not None:
            res["reasoningEffort"] = self.reasoning_effort
        return res


class ModelSelectionRef:
    """Mutable model selection plus the value captured for the current step."""

    def __init__(
        self,
        current: Optional[ModelSelection] = None,
        assembled: Optional[ModelSelection] = None,
    ):
        self.current = current
        self.assembled = assembled


def install_model_selection(agent_ctx: Context, selection: ModelSelectionRef) -> Callable[[], None]:
    """
    Couple one mutable selection to Agent-scoped prompt assembly and request routing.
    """
    import inspect

    async def _on_assembly(*args: Any, **kwargs: Any) -> Any:
        next_fn = args[-1] if args and callable(args[-1]) else None
        current_assembly = args[0] if args else {}
        selected = selection.current
        assembled = (await next_fn()) if (next_fn and inspect.iscoroutinefunction(next_fn)) else (next_fn() if next_fn else current_assembly)
        if inspect.isawaitable(assembled):
            assembled = await assembled
        selection.assembled = selected
        if selected is None:
            return assembled
        if isinstance(assembled, dict):
            res = dict(assembled)
            vars_dict = dict(res.get("variables", {}))
            vars_dict["provider"] = selected.provider
            vars_dict["model"] = selected.model
            res["variables"] = vars_dict
            return res
        return assembled

    async def _on_request(*args: Any, **kwargs: Any) -> Any:
        next_fn = args[-1] if args and callable(args[-1]) else None
        current_req = args[0] if args else {}
        resolved = (await next_fn()) if (next_fn and inspect.iscoroutinefunction(next_fn)) else (next_fn() if next_fn else current_req)
        if inspect.isawaitable(resolved):
            resolved = await resolved
        selected = selection.assembled
        if selected is None:
            return resolved
        if isinstance(resolved, dict):
            res = dict(resolved)
            res.pop("reasoningEffort", None)
            res["provider"] = selected.provider
            res["model"] = selected.model
            if selected.reasoning_effort is not None:
                res["reasoningEffort"] = selected.reasoning_effort
            return res
        return resolved

    dispose_assembly = agent_ctx.on("system-prompt/assemble", _on_assembly)
    dispose_request = agent_ctx.on("agent/request", _on_request)

    def disposer() -> None:
        dispose_assembly()
        dispose_request()

    return disposer


installModelSelection = install_model_selection
