"""
PromptLayer implementation matching reference/packages/core/system-prompt/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Dict, Optional, Union
from dsh.core.scope import AnonymousEntries, NamedEntries, ScopeLayer
from dsh.core.system_prompt.types import PromptContext, PromptSection


class PromptLayer(ScopeLayer):
    """All prompt registrations owned by one global or scoped layer."""

    def __init__(self, scope: Optional[Any] = None):
        self.scope = scope
        self.sections: NamedEntries = NamedEntries(
            lambda name: ValueError(
                f'prompt section "{name}" is already registered (for a per-agent override, register through that agent\'s `agent.ctx` instead)'
                if scope is None
                else f'prompt section "{name}" is already registered in this scope'
            )
        )
        self.contexts: NamedEntries = NamedEntries(
            lambda name: ValueError(
                f'prompt context "{name}" is already registered (for a per-agent override, register through that agent\'s `agent.ctx` instead)'
                if scope is None
                else f'prompt context "{name}" is already registered in this scope'
            )
        )
        self.runtime_context_suppressors: AnonymousEntries = AnonymousEntries()
        self.tool_providers: AnonymousEntries = AnonymousEntries()
        self.variables: NamedEntries = NamedEntries(
            lambda name: ValueError(
                f'prompt variable "{name}" is already registered (for a per-agent value, register through that agent\'s `agent.ctx` instead)'
                if scope is None
                else f'prompt variable "{name}" is already registered in this scope'
            )
        )

    def is_empty(self) -> bool:
        """Test whether this layer owns no prompt registrations."""
        return (
            self.sections.is_empty()
            and self.contexts.is_empty()
            and self.runtime_context_suppressors.is_empty()
            and self.tool_providers.is_empty()
            and self.variables.is_empty()
        )

    isEmpty = is_empty
