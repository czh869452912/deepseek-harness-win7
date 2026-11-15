"""
SystemPrompt Service implementation matching reference/packages/core/system-prompt/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import functools
import json
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Union

from dsh.cordis.context import Context
from dsh.cordis.service import Service
from dsh.core.scope import ScopedLayers, scope_of, scope_target
from dsh.core.system_prompt.layer import PromptLayer
from dsh.core.system_prompt.types import (
    FIRST_PARTY_SECTION_ORDER,
    PERSONA_ORDER,
    PERSONA_SECTION,
    TOOL_ORDER_REST,
    VARIABLE_NAME,
    PromptAssembly,
    AssembledItem,
    PromptContext,
    PromptSection,
    compare_prompt_sections,
    order_tools,
    validate_tool_order,
)


class SystemPrompt(Service):
    """
    Registry service for the prompt inputs assembled before each model step.
    Mounts as ctx.systemPrompt (with alias ctx.system_prompt).
    """

    name = "systemPrompt"
    _section_orders = FIRST_PARTY_SECTION_ORDER

    def _persona_sections(self, config):
        return [dict(name=PERSONA_SECTION, order=PERSONA_ORDER, text=config.get('persona') or '')]

    def get_section_order(self, name: str) -> int:
        """Resolve a centrally allocated prompt section placement."""
        return self._section_orders[name]

    getSectionOrder = get_section_order

    def get_context_order(self, name: str) -> int:
        """Resolve a centrally allocated runtime context placement."""
        return {"SANDBOX_POLICY": 110, "APPROVAL_POLICY": 115,
                "SUBAGENT_DELEGATION": 120}[name]

    getContextOrder = get_context_order

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx, "systemPrompt")
        # Backwards compatible alias
        try:
            self.ctx.set_service("system_prompt", self)
        except Exception:
            pass

        cfg = config or {}
        include_identity = cfg.get("includeHarnessIdentity", cfg.get("include_harness_identity", True))
        include_runtime_context = cfg.get("includeRuntimeContext", cfg.get("include_runtime_context", True))
        tool_order = cfg.get("toolOrder", cfg.get("tool_order", None))

        self.tool_order = validate_tool_order(tool_order)
        self.layers: ScopedLayers = ScopedLayers(
            lambda scope: PromptLayer(scope),
            lambda: self.ctx.emit("system-prompt/change"),
        )

        if include_identity:
            self.section({
                "name": "harness:identity",
                "order": self._section_orders["HARNESS_IDENTITY"],
                "text": "You are an AI agent powered by DeepSeek Harness.",
            })

        for section in self._persona_sections(cfg):
            self.section(section)

        if not include_runtime_context:
            self.suppress_runtime_context()

    @property
    def global_layer(self) -> PromptLayer:
        return self.layers.global_layer

    @property
    def scoped_layers(self) -> Dict[Any, PromptLayer]:
        return self.layers.scoped

    def _get_layer(self, scope: Optional[Any] = None) -> PromptLayer:
        if scope is None:
            scope = scope_of(self.ctx)
        return self.layers.layer_of(scope)

    def section(self, section: Union[Dict[str, Any], PromptSection]) -> Callable[[], None]:
        """
        Register an ordered prompt section in the calling context's scope.
        """
        if isinstance(section, dict):
            sec_name = section.get("name", "")
            sec_order = section.get("order", 0)
            sec_text = section.get("text", "")
            sec_complete = section.get("complete", False)
            sec_obj = PromptSection(name=sec_name, order=sec_order, text=sec_text, complete=sec_complete,
                                    interpolate=section.get("interpolate"))
        else:
            sec_name = section.name
            sec_order = section.order
            sec_obj = section

        if not isinstance(sec_order, (int, float)) or not math.isfinite(sec_order):
            raise TypeError(f'prompt section "{sec_name}" order must be a finite number')

        return self.layers.effect(
            self.ctx,
            lambda layer: layer.sections.insert(sec_name, sec_obj),
            {"label": "systemPrompt.section()"},
        )

    def context(self, context: Union[Dict[str, Any], PromptContext]) -> Callable[[], None]:
        """
        Register ordered dynamic context in the calling context's scope.
        """
        if isinstance(context, dict):
            ctx_name = context.get("name", "")
            ctx_order = context.get("order", 0)
            ctx_text = context.get("text", "")
            ctx_obj = PromptContext(name=ctx_name, order=ctx_order, text=ctx_text,
                                   required=context.get("required") is True, interpolate=context.get("interpolate"))
        else:
            ctx_name = context.name
            ctx_order = context.order
            ctx_obj = context

        if not isinstance(ctx_order, (int, float)) or not math.isfinite(ctx_order):
            raise TypeError(f'prompt context "{ctx_name}" order must be a finite number')

        return self.layers.effect(
            self.ctx,
            lambda layer: layer.contexts.insert(ctx_name, ctx_obj),
            {"label": "systemPrompt.context()"},
        )

    def suppress_runtime_context(self) -> Callable[[], None]:
        """
        Suppress every dynamic runtime-context contribution in calling context's scope.
        """
        return self.layers.effect(
            self.ctx,
            lambda layer: layer.runtime_context_suppressors.append(True),
            {"label": "systemPrompt.suppressRuntimeContext()"},
        )

    suppressRuntimeContext = suppress_runtime_context

    def tools(self, provider: Callable[..., Any]) -> Callable[[], None]:
        """
        Register a tool-schema provider in calling context's scope.
        """
        return self.layers.effect(
            self.ctx,
            lambda layer: layer.tool_providers.append(provider),
            {"label": "systemPrompt.tools()"},
        )

    def variable(self, name: str, provider: Union[str, Callable[..., Optional[str]]]) -> Callable[[], None]:
        """
        Register a prompt variable in calling context's scope.
        """
        if not VARIABLE_NAME.match(name):
            raise ValueError(f'invalid prompt variable name "{name}" (must match /^[a-z][a-z0-9_]*$/)')

        prov_fn = provider if callable(provider) else (lambda ctx=None: provider)
        return self.layers.effect(
            self.ctx,
            lambda layer: layer.variables.insert(name, prov_fn),
            {"label": "systemPrompt.variable()"},
        )

    async def assemble(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Assemble global and scoped providers, apply canonical ordering, then run waterfall.
        """
        ctx_param = context or {}
        scope = ctx_param.get("scope")
        scope_layers: List[PromptLayer] = self.layers.chain_layers(scope)

        runtime_context_suppressed = (
            not self.layers.global_layer.runtime_context_suppressors.is_empty()
            or any(not l.runtime_context_suppressors.is_empty() for l in scope_layers)
        )

        # Scoped variables shadow globals
        variables: Dict[str, Optional[str]] = {}
        for name, prov in self.layers.global_layer.variables.entries():
            variables[name] = prov(ctx_param) if callable(prov) else prov
        for layer in scope_layers:
            for name, prov in layer.variables.entries():
                variables[name] = prov(ctx_param) if callable(prov) else prov

        # Scoped sections and contexts shadow globals
        section_by_name = self.layers.merge(scope, lambda l: l.sections)
        context_by_name = self.layers.merge(scope, lambda l: l.contexts)

        # Snapshot tool providers before evaluation
        providers = (
            list(self.layers.global_layer.tool_providers.values())
            + [p for layer in scope_layers for p in layer.tool_providers.values()]
        )

        collected: List[Dict[str, Any]] = []
        known_names: Set[str] = set()
        for prov in providers:
            res = prov(ctx_param)
            raw_schemas: List[Any] = []
            prov_known_names: Optional[Sequence[str]] = None

            if isinstance(res, dict):
                raw_schemas = res.get("schemas", [])
                prov_known_names = res.get("knownNames") or res.get("known_names")
            elif hasattr(res, "schemas"):
                raw_schemas = getattr(res, "schemas", [])
                prov_known_names = getattr(res, "knownNames", None) or getattr(res, "known_names", None)
            elif isinstance(res, (list, tuple)):
                raw_schemas = list(res)

            schemas: List[Dict[str, Any]] = []
            for s in raw_schemas:
                if isinstance(s, dict):
                    schemas.append({
                        "name": s.get("name", ""),
                        "description": s.get("description", ""),
                        "parameters": copy.deepcopy(s.get("parameters", {})),
                    })
                else:
                    schemas.append({
                        "name": getattr(s, "name", ""),
                        "description": getattr(s, "description", ""),
                        "parameters": copy.deepcopy(getattr(s, "parameters", {})),
                    })

            collected.extend(schemas)
            if prov_known_names is not None:
                for k in prov_known_names:
                    known_names.add(k)
            else:
                for s in schemas:
                    known_names.add(s["name"])

        section_definitions = sorted(section_by_name.values(), key=functools.cmp_to_key(compare_prompt_sections))
        complete_sections = [
            s for s in section_definitions
            if (s.get("complete", False) if isinstance(s, dict) else getattr(s, "complete", False))
        ]
        if len(complete_sections) > 1:
            c_names = ", ".join(json.dumps(s.get("name", "") if isinstance(s, dict) else getattr(s, "name", "")) for s in complete_sections)
            raise ValueError(f"multiple complete prompt sections are active: {c_names}")

        complete_section: Optional[Dict[str, Any]] = None
        sections: List[Dict[str, Any]] = []
        for sec in section_definitions:
            sec_name = sec.get("name", "") if isinstance(sec, dict) else getattr(sec, "name", "")
            sec_text = sec.get("text", "") if isinstance(sec, dict) else getattr(sec, "text", "")
            resolved_text = sec_text(ctx_param) if callable(sec_text) else sec_text
            assembled = {"name": sec_name, "text": resolved_text}
            interpolation = getattr(sec, 'interpolate', None)
            if interpolation is not None:
                assembled['interpolate'] = interpolation
            is_comp = sec.get("complete", False) if isinstance(sec, dict) else getattr(sec, "complete", False)
            if is_comp:
                complete_section = dict(assembled)
            sections.append(assembled)

        contexts: List[Dict[str, Any]] = []
        if context_by_name:
            ctx_sorted = sorted(
                context_by_name.values(),
                key=lambda x: x.get("order", 0) if isinstance(x, dict) else getattr(x, "order", 0),
            )
            for c in ctx_sorted:
                if runtime_context_suppressed and getattr(c, 'required', False) is not True:
                    continue
                c_name = c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                c_text = c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "")
                resolved_text = c_text(ctx_param) if callable(c_text) else c_text
                resolved = {"name": c_name, "text": resolved_text}
                if getattr(c, 'interpolate', None) is not None:
                    resolved['interpolate'] = c.interpolate
                contexts.append(resolved)

        assembly = PromptAssembly(
            sections=sections,
            contexts=contexts,
            tools=order_tools(collected, self.tool_order, known_names),
            variables=variables,
        )

        carrier = scope_target(self, scope)
        authoritative_tools = getattr(self, '_authoritative_tools', False)
        accepted_tools = assembly['tools']
        if authoritative_tools:
            del assembly['tools']
        transformed = await self.ctx.waterfall(
            carrier,
            "system-prompt/assemble",
            assembly,
            ctx_param,
            lambda: assembly,
        )
        if authoritative_tools:
            transformed = dict(transformed, tools=accepted_tools)

        if complete_section is None and not runtime_context_suppressed:
            return transformed if isinstance(transformed, PromptAssembly) else PromptAssembly(transformed)

        res = PromptAssembly(transformed)
        if complete_section is not None:
            res["sections"] = [AssembledItem(complete_section)]
        if runtime_context_suppressed:
            required_names = {entry.name for entry in context_by_name.values() if getattr(entry, 'required', False) is True}
            res["contexts"] = [entry for entry in res["contexts"] if entry['name'] in required_names]
        return res
