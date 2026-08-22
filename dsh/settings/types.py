"""
Types and branded namespace validation for dsh.settings.
Aligned 1:1 with reference @deepseek-ai/dsh-settings/types.
"""

import re
from typing import Any, Dict, List, Optional

NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def settings_namespace(value: str) -> str:
    """
    Validate and brand a raw string as a SettingsNamespace.
    Must be lowercase kebab-case (e.g. 'llm', 'llm-deepseek', 'general').
    """
    if not isinstance(value, str) or not NAMESPACE_PATTERN.match(value):
        raise TypeError(f'settings namespace "{value}" must match {NAMESPACE_PATTERN.pattern}')
    return value
