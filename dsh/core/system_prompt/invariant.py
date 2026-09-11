"""
Package-owned prompt-assembly invariants.
Strict 1:1 parity with reference/packages/core/system-prompt/src/invariant.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
from typing import Any, Callable, Dict, List, Optional, Set, Union
from dsh.cordis.context import Context
from dsh.core.system_prompt.types import VARIABLE_NAME

PACKAGE_NAME = "@deepseek-ai/dsh-system-prompt"

name = "system-prompt-invariant"
inject = ["invariants"]


def validate_assembly(assembly: Dict[str, Any], fail: Callable[[str], None]) -> None:
    """Validate the authoritative assembly returned by the waterfall."""
    sections = assembly.get("sections", [])
    section_names: Set[str] = set()
    for section in sections:
        sec_name = section.get("name", "") if isinstance(section, dict) else getattr(section, "name", "")
        sec_text = section.get("text", "") if isinstance(section, dict) else getattr(section, "text", "")
        if len(sec_name) == 0:
            fail("assembled section names must be non-empty")
        if sec_name in section_names:
            fail(f"assembled section name {json.dumps(sec_name)} is duplicated")
        section_names.add(sec_name)
        if not isinstance(sec_text, str):
            fail(f"assembled section {json.dumps(sec_name)} text must be a string")

    contexts = assembly.get("contexts", [])
    context_names: Set[str] = set()
    for context in contexts:
        ctx_name = context.get("name", "") if isinstance(context, dict) else getattr(context, "name", "")
        ctx_text = context.get("text", "") if isinstance(context, dict) else getattr(context, "text", "")
        if len(ctx_name) == 0:
            fail("assembled context names must be non-empty")
        if ctx_name in context_names:
            fail(f"assembled context name {json.dumps(ctx_name)} is duplicated")
        context_names.add(ctx_name)
        if not isinstance(ctx_text, str):
            fail(f"assembled context {json.dumps(ctx_name)} text must be a string")

    tools = assembly.get("tools", [])
    for tool in tools:
        t_name = tool.get("name", "") if isinstance(tool, dict) else getattr(tool, "name", "")
        if len(t_name) == 0:
            fail("assembled tool names must be non-empty")

    variables = assembly.get("variables", {})
    if isinstance(variables, dict):
        for var_name, value in variables.items():
            if not VARIABLE_NAME.match(var_name):
                fail(f"assembled variable name {json.dumps(var_name)} is invalid")
            if value is not None and not isinstance(value, str):
                fail(f"assembled variable {json.dumps(var_name)} must be a string or undefined")


def install(ctx: Context, fail: Callable[[str], None]) -> None:
    """Install validation around the authoritative assembly waterfall result."""
    async def _on_assemble(_assembly: Any, _context: Any, next_fn: Optional[Callable[..., Any]] = None) -> Any:
        if next_fn is not None:
            assembled = await next_fn()
        else:
            assembled = _assembly
        validate_assembly(assembled, fail)
        return assembled

    ctx.on("system-prompt/assemble", _on_assemble, prepend=True, global_listener=True)


def apply(ctx: Context) -> Any:
    """
    Register the system-prompt invariant companion.
    """
    invariants_svc = ctx.get("invariants")
    if invariants_svc is None:
        raise RuntimeError("invariants service required")
    return invariants_svc.register(PACKAGE_NAME, install)


class SystemPromptInvariantPlugin:
    """Plugin wrapper for Cordis compatibility."""
    name = "system-prompt-invariant"
    inject = ["invariants"]

    @staticmethod
    def apply(ctx: Context) -> Any:
        return apply(ctx)
