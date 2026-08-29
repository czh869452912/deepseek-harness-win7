"""
System Prompt Registry and Assembly Service for DeepSeek Harness.
1:1 matching reference/packages/core/system-prompt/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dsh.cordis.context import Context
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema, z


FIRST_PARTY_SECTION_ORDER: Dict[str, int] = {
    "HARNESS_IDENTITY": -1000,
    "HARNESS_SOURCE": -900,
    "WEB_SURFACE": -800,
    "DEPLOYMENT_PERSONA": 0,
    "PLAN_POLICY": 500,
    "TEAM_POLICY": 600,
    "PTC_ONLY": 800,
    "FILE_REFERENCE": 900,
    "TOOL_BASH": 1000,
    "TOOL_PWSH": 1010,
    "TOOL_READ": 1100,
    "TOOL_WRITE": 1200,
    "TOOL_EDIT": 1300,
    "TOOL_GLOB": 1400,
    "TOOL_GREP": 1500,
    "TOOL_JOBS": 1600,
    "TOOL_PTY": 1700,
    "TOOL_WEB_SEARCH": 2000,
    "TOOL_WEB_FETCH": 2100,
    "TOOL_LSP": 2200,
    "TOOL_SESSION_QUERY": 2300,
    "TOOL_GOAL": 2400,
    "TOOL_CORDIS": 2500,
    "TOOL_WORKFLOW": 2600,
    "TOOL_RALPH": 2700,
    "TOOL_SUBAGENT": 2800,
    "TOOL_REPORT": 2900,
    "TOOLS_SDK": 5000,
    "DELIVERABLE_FILE_REFERENCES": 9000,
    "STRUCTURED_OUTPUT": 9900,
}

PERSONA_SECTION: str = "deployment:persona"
PERSONA_ORDER: int = FIRST_PARTY_SECTION_ORDER["DEPLOYMENT_PERSONA"]
TOOL_ORDER_REST: str = "<unlisted-tools>"

VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
GROUP_AT = re.compile(r"^\{\{([^{}]*)\}\}")


def validate_tool_order(tool_order: Optional[List[str]]) -> Optional[List[str]]:
    """Validate duplicate names and the required TOOL_ORDER_REST marker."""
    if tool_order is None:
        return None
    seen = set()
    for name in tool_order:
        if name in seen:
            raise ValueError(f'toolOrder lists "{name}" more than once')
        seen.add(name)
    if TOOL_ORDER_REST not in seen:
        raise ValueError(f'toolOrder must contain the "{TOOL_ORDER_REST}" rest entry (where unlisted tools are inserted)')
    return tool_order


def compare_names(a: str, b: str) -> int:
    """Code-unit name comparison — locale-independent."""
    return -1 if a < b else (1 if a > b else 0)


def compare_prompt_sections(a: Dict[str, Any], b: Dict[str, Any]) -> int:
    """Order prompt sections by their explicit placement, then deterministically by name."""
    order_diff = a.get("order", 0) - b.get("order", 0)
    if order_diff != 0:
        return order_diff
    return compare_names(a.get("name", ""), b.get("name", ""))


def compare_tool_names(a: Dict[str, Any], b: Dict[str, Any]) -> int:
    """Order tool schemas lexicographically by name."""
    return compare_names(a.get("name", ""), b.get("name", ""))


def order_tools(tools: List[Dict[str, Any]], tool_order: Optional[List[str]], known_names: Set[str]) -> List[Dict[str, Any]]:
    """Apply configured tool order, inserting unlisted tools lexicographically at TOOL_ORDER_REST."""
    for tool in tools:
        if tool.get("name") == TOOL_ORDER_REST:
            raise ValueError(f'tool provider returned reserved tool name "{TOOL_ORDER_REST}" (reserved for toolOrder\'s rest entry)')

    if tool_order is None:
        return sorted(tools, key=lambda t: t.get("name", ""))

    unknown = [name for name in tool_order if name != TOOL_ORDER_REST and name not in known_names]
    if unknown:
        formatted_unknown = ", ".join(f'"{name}"' for name in unknown)
        known_str = ", ".join(sorted(known_names)) or "(none)"
        raise ValueError(f'toolOrder lists unregistered tool{"s" if len(unknown) > 1 else ""} {formatted_unknown}; known tools: {known_str}')

    listed = set(tool_order)
    rest = sorted([t for t in tools if t.get("name") not in listed], key=lambda t: t.get("name", ""))

    ordered_res: List[Dict[str, Any]] = []
    for name in tool_order:
        if name == TOOL_ORDER_REST:
            ordered_res.extend(rest)
        else:
            ordered_res.extend([t for t in tools if t.get("name") == name])
    return ordered_res


def interpolate_text(
    input_item: Dict[str, Any],
    variables: Dict[str, Optional[str]],
    kind: str = "section",
) -> str:
    """Interpolate strict {{variable}} references, handling diagnostics."""
    text = input_item.get("text", "")
    if not isinstance(text, str):
        text = str(text) if text is not None else ""

    result = ""
    last = 0
    item_name = input_item.get("name", "anonymous")

    while True:
        open_pos = text.find("{{", last)
        if open_pos < 0:
            break
        match = GROUP_AT.match(text[open_pos:])
        if match is None:
            if text.find("}}", open_pos + 2) >= 0:
                snippet = text[open_pos : open_pos + 16]
                raise ValueError(f'malformed prompt variable reference at "{snippet}…" in {kind} "{item_name}" (references are complete simple {{name}} groups)')
            result += text[last : open_pos + 2]
            last = open_pos + 2
            continue

        raw_group = match.group(0)
        var_name = raw_group[2:-2]
        if not VARIABLE_NAME.match(var_name):
            raise ValueError(f'malformed prompt variable reference "{{{{{var_name}}}}}" in {kind} "{item_name}" (variable names match /^[a-z][a-z0-9_]*$/)')

        if var_name not in variables:
            known_str = ", ".join(variables.keys()) if variables else "(none)"
            raise ValueError(f'unknown prompt variable "{{{{{var_name}}}}}" in {kind} "{item_name}"; registered variables: {known_str}')

        val = variables[var_name]
        if val is None:
            raise ValueError(f'prompt variable "{{{{{var_name}}}}}" has no value for this assembly ({kind} "{item_name}")')

        result += text[last:open_pos] + val
        last = open_pos + len(raw_group)

    return result + text[last:]


def render_prompt(assembly: Dict[str, Any]) -> str:
    """Interpolate strict {{variable}} references and join sections with double newlines."""
    sections = assembly.get("sections", [])
    variables = assembly.get("variables", {})
    rendered_parts: List[str] = []
    for section in sections:
        txt = interpolate_text(section, variables, "section")
        if txt.strip():
            rendered_parts.append(txt)
    return "\n\n".join(rendered_parts)


def render_context_sections(assembly: Dict[str, Any]) -> List[Dict[str, str]]:
    """Render each active context snapshot as named contributions."""
    contexts = assembly.get("contexts", [])
    variables = assembly.get("variables", {})
    res = []
    for ctx in contexts:
        txt = interpolate_text(ctx, variables, "context")
        if txt.strip():
            res.append({"name": ctx.get("name", ""), "text": txt})
    return res


def join_context_sections(sections: List[Dict[str, str]]) -> str:
    """Join context snapshot sections with official header."""
    body = "\n\n".join(s["text"] for s in sections if s.get("text"))
    if not body:
        return ""
    return f"Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n{body}"


def render_context_snapshot(assembly: Dict[str, Any]) -> str:
    """Render full joined dynamic context snapshot."""
    return join_context_sections(render_context_sections(assembly))


class PromptLayer:
    """All prompt registrations owned by one global or scoped layer."""

    def __init__(self, scope: Optional[Any] = None):
        self.scope = scope
        self.sections: Dict[str, Dict[str, Any]] = {}
        self.contexts: Dict[str, Dict[str, Any]] = {}
        self.runtime_context_suppressors: List[bool] = []
        self.tool_providers: List[Callable[..., Any]] = []
        self.variables: Dict[str, Callable[..., Optional[str]]] = {}

    def is_empty(self) -> bool:
        return (
            len(self.sections) == 0
            and len(self.contexts) == 0
            and len(self.runtime_context_suppressors) == 0
            and len(self.tool_providers) == 0
            and len(self.variables) == 0
        )


class SystemPrompt(Service):
    """
    Registry service for prompt sections, dynamic contexts, tool schemas, and prompt variables.
    Matching reference/packages/core/system-prompt/src/index.ts.
    """

    name = "systemPrompt"
    provide_name = "system_prompt"

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx, name="systemPrompt")
        self.ctx.set_service("system_prompt", self)
        self.config: Dict[str, Any] = config or {}
        self.tool_order = validate_tool_order(self.config.get("toolOrder"))
        self.global_layer = PromptLayer(None)
        self.scoped_layers: Dict[Any, PromptLayer] = {}

        # Default persona and harness identity
        inc_identity = self.config.get("includeHarnessIdentity", True)
        if inc_identity is not False:
            self.section({
                "name": "harness:identity",
                "order": FIRST_PARTY_SECTION_ORDER["HARNESS_IDENTITY"],
                "text": "You are an AI agent powered by DeepSeek Harness.",
            })

        persona_text = self.config.get("persona", "")
        self.section({
            "name": PERSONA_SECTION,
            "order": PERSONA_ORDER,
            "text": persona_text or "",
        })

        inc_runtime_context = self.config.get("includeRuntimeContext", True)
        if inc_runtime_context is False:
            self.suppress_runtime_context()

    def _get_layer(self, target_ctx: Optional[Context] = None) -> PromptLayer:
        c = target_ctx or self.ctx
        scope = getattr(c, "scope", None) or getattr(c, "_scope", None)
        if scope is None:
            return self.global_layer
        if scope not in self.scoped_layers:
            self.scoped_layers[scope] = PromptLayer(scope)
        return self.scoped_layers[scope]

    def section(self, section_dict: Dict[str, Any]) -> Callable[[], None]:
        """Register an ordered prompt section. Scoped sections shadow globals with same name."""
        name = section_dict.get("name")
        if not name:
            raise ValueError("Prompt section must have a 'name'")
        order = section_dict.get("order", 0)
        if not isinstance(order, (int, float)):
            raise TypeError(f'prompt section "{name}" order must be a finite number')

        layer = self._get_layer()
        if name in layer.sections:
            scope_hint = "in this scope" if layer.scope else "(for a per-agent override, register through that agent's `agent.ctx` instead)"
            raise ValueError(f'prompt section "{name}" is already registered {scope_hint}')

        layer.sections[name] = dict(section_dict)
        self.ctx.emit("system-prompt/change")

        def _disposer():
            layer.sections.pop(name, None)
            self.ctx.emit("system-prompt/change")

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(lambda: _disposer, label="systemPrompt.section()")
        return _disposer

    def context(self, context_dict: Dict[str, Any]) -> Callable[[], None]:
        """Register ordered dynamic context contribution."""
        name = context_dict.get("name")
        if not name:
            raise ValueError("Prompt context must have a 'name'")
        order = context_dict.get("order", 0)
        if not isinstance(order, (int, float)):
            raise TypeError(f'prompt context "{name}" order must be a finite number')

        layer = self._get_layer()
        if name in layer.contexts:
            scope_hint = "in this scope" if layer.scope else "(for a per-agent override, register through that agent's `agent.ctx` instead)"
            raise ValueError(f'prompt context "{name}" is already registered {scope_hint}')

        layer.contexts[name] = dict(context_dict)
        self.ctx.emit("system-prompt/change")

        def _disposer():
            layer.contexts.pop(name, None)
            self.ctx.emit("system-prompt/change")

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(lambda: _disposer, label="systemPrompt.context()")
        return _disposer

    def suppress_runtime_context(self) -> Callable[[], None]:
        """Suppress dynamic runtime-context contributions in current scope."""
        layer = self._get_layer()
        layer.runtime_context_suppressors.append(True)

        def _disposer():
            if layer.runtime_context_suppressors:
                layer.runtime_context_suppressors.pop()

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(lambda: _disposer, label="systemPrompt.suppressRuntimeContext()")
        return _disposer

    def tools(self, provider: Callable[..., Any]) -> Callable[[], None]:
        """Register a tool schema provider."""
        layer = self._get_layer()
        layer.tool_providers.append(provider)

        def _disposer():
            if provider in layer.tool_providers:
                layer.tool_providers.remove(provider)

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(lambda: _disposer, label="systemPrompt.tools()")
        return _disposer

    def variable(self, name: str, provider: Union[str, Callable[..., Optional[str]]]) -> Callable[[], None]:
        """Register a prompt variable in current scope."""
        if not VARIABLE_NAME.match(name):
            raise ValueError(f'invalid prompt variable name "{name}" (must match /^[a-z][a-z0-9_]*$/)')

        layer = self._get_layer()
        if name in layer.variables:
            scope_hint = "in this scope" if layer.scope else "(for a per-agent value, register through that agent's `agent.ctx` instead)"
            raise ValueError(f'prompt variable "{name}" is already registered {scope_hint}')

        prov_fn = provider if callable(provider) else (lambda ctx=None: provider)
        layer.variables[name] = prov_fn
        self.ctx.emit("system-prompt/change")

        def _disposer():
            layer.variables.pop(name, None)
            self.ctx.emit("system-prompt/change")

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(lambda: _disposer, label="systemPrompt.variable()")
        return _disposer

    async def assemble(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Assemble global and scoped sections, contexts, tools, and variables, then run waterfall.
        Matching TS SystemPrompt.assemble().
        """
        ctx_param = context or {}
        scope = ctx_param.get("scope")

        # Collect layers
        layers: List[PromptLayer] = [self.global_layer]
        if scope and scope in self.scoped_layers:
            layers.append(self.scoped_layers[scope])

        runtime_context_suppressed = any(len(l.runtime_context_suppressors) > 0 for l in layers)

        # Variables: scoped shadows globals
        variables: Dict[str, Optional[str]] = {}
        for layer in layers:
            for v_name, prov in layer.variables.items():
                variables[v_name] = prov(ctx_param) if callable(prov) else str(prov)

        # Sections: scoped shadows globals by name
        section_by_name: Dict[str, Dict[str, Any]] = {}
        for layer in layers:
            section_by_name.update(layer.sections)

        # Contexts: scoped shadows globals by name
        context_by_name: Dict[str, Dict[str, Any]] = {}
        for layer in layers:
            context_by_name.update(layer.contexts)

        # Tools
        collected_tools: List[Dict[str, Any]] = []
        known_names: Set[str] = set()
        for layer in layers:
            for provider in layer.tool_providers:
                res = provider(ctx_param) if callable(provider) else provider
                if isinstance(res, dict):
                    schemas = res.get("schemas", [])
                    known = res.get("knownNames") or [t.get("name") for t in schemas if t.get("name")]
                elif isinstance(res, list):
                    schemas = res
                    known = [t.get("name") for t in schemas if t.get("name")]
                else:
                    schemas = []
                    known = []

                for s in schemas:
                    copied = copy.deepcopy(s)
                    collected_tools.append(copied)
                    if copied.get("name"):
                        known_names.add(copied["name"])
                for k in known:
                    known_names.add(k)

        # Sort sections by order then code-unit name (alphabetical)
        section_defs = sorted(
            section_by_name.values(),
            key=lambda s: (s.get("order", 0), s.get("name", "")),
        )

        complete_sections = [s for s in section_defs if s.get("complete") is True]
        if len(complete_sections) > 1:
            names_str = ", ".join(f'"{s.get("name")}"' for s in complete_sections)
            raise ValueError(f"multiple complete prompt sections are active: {names_str}")

        complete_section: Optional[Dict[str, Any]] = None
        assembled_sections: List[Dict[str, Any]] = []
        for sec in section_defs:
            text_val = sec.get("text", "")
            resolved_text = text_val(ctx_param) if callable(text_val) else text_val
            item = {"name": sec.get("name", ""), "text": resolved_text}
            if sec.get("complete") is True:
                complete_section = dict(item)
            assembled_sections.append(item)

        assembled_contexts: List[Dict[str, Any]] = []
        if not runtime_context_suppressed:
            sorted_contexts = sorted(context_by_name.values(), key=lambda c: (c.get("order", 0), c.get("name", "")))
            for c in sorted_contexts:
                c_text = c.get("text", "")
                r_text = c_text(ctx_param) if callable(c_text) else c_text
                assembled_contexts.append({"name": c.get("name", ""), "text": r_text})

        ordered_tool_schemas = order_tools(collected_tools, self.tool_order, known_names)

        assembly = {
            "sections": assembled_sections,
            "contexts": assembled_contexts,
            "tools": ordered_tool_schemas,
            "variables": variables,
        }

        # Run system-prompt/assemble waterfall
        transformed = await self.ctx.waterfall("system-prompt/assemble", assembly, ctx_param)

        if not isinstance(transformed, dict):
            return assembly

        if complete_section is None and not runtime_context_suppressed:
            return transformed

        return {
            "sections": [complete_section] if complete_section is not None else transformed.get("sections", []),
            "contexts": [] if runtime_context_suppressed else transformed.get("contexts", []),
            "tools": transformed.get("tools", []),
            "variables": transformed.get("variables", {}),
        }
