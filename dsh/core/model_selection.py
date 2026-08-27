"""
Agent-scoped model selection shared by runtime entry points.
Aligned 1:1 with official `@deepseek-ai/dsh-agent/model-selection`.
"""

import inspect

from typing import Any, Callable, Dict, List, Optional
from dsh.cordis.context import Context
from dsh.cordis.service import Service
from dsh.settings.provider import install_settings_section
from dsh.settings.types import settings_namespace


AGENT_DEFAULT_MODEL_SETTINGS_NAMESPACE = settings_namespace("agent-default-model")


class _StringObjectSchema:
    """Small Schemastery-compatible adapter for this package's object schemas."""

    def __init__(self, required: List[str], optional: Optional[List[str]] = None):
        self.required = list(required)
        self.optional = list(optional or [])

    def _issues(self, value: Any) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        if not isinstance(value, dict):
            return [{"message": "expected an object"}]
        for key in self.required:
            if key not in value:
                issues.append({"message": "is required", "path": [key]})
            elif not isinstance(value[key], str):
                issues.append({"message": "expected a string", "path": [key]})
        for key in self.optional:
            if key in value and value[key] is not None and not isinstance(value[key], str):
                issues.append({"message": "expected a string", "path": [key]})
        return issues

    def validate(self, value: Any) -> Dict[str, Any]:
        return {"value": value, "issues": self._issues(value)}

    def __call__(self, value: Any) -> Any:
        issues = self._issues(value)
        if issues:
            issue = issues[0]
            path = ".".join(issue.get("path", []))
            suffix = " at %s" % path if path else ""
            raise TypeError("invalid agent default model settings: %s%s" % (issue["message"], suffix))
        return value

    def to_json(self) -> Dict[str, Any]:
        properties = {
            key: {"type": "string"}
            for key in self.required + self.optional
        }
        return {"type": "object", "properties": properties, "required": list(self.required)}


AGENT_DEFAULT_MODEL_SETTINGS_SCHEMA = _StringObjectSchema(
    ["provider", "model"], ["reasoningEffort"]
)


class AgentDefaultModelConfig(Service):
    """Default Agent model selection layered over the optional settings service."""

    Config = _StringObjectSchema(["provider", "model"])

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
    def _on_assembly(assembly: Any, context: Any, next_fn: Callable[[], Any]) -> Any:
        selected = selection.current
        assembled = next_fn()
        selection.assembled = selected
        if selected is None:
            return assembled
        if isinstance(assembled, dict):
            vars_dict = dict(assembled.get("variables", {}))
            vars_dict["provider"] = selected.provider
            vars_dict["model"] = selected.model
            assembled["variables"] = vars_dict
        return assembled

    def _on_request(payload: Any, next_fn: Callable[[], Any]) -> Any:
        resolved = next_fn()
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
