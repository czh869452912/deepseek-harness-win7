import fnmatch
import os
import re
from typing import Any, Dict, List, Optional, Tuple


def validate_include(include: str) -> None:
    trimmed = include.strip()
    if not trimmed:
        raise ValueError("include must be a non-empty glob when given")
    if trimmed.startswith("!"):
        raise ValueError('include must be a positive glob filter; negated patterns ("!…") are not supported')
    brace_depth = 0
    for char in trimmed:
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(0, brace_depth - 1)
        elif char == "," and brace_depth == 0:
            raise ValueError("include must be one glob, not a comma-separated list (use {a,b} alternation instead)")
