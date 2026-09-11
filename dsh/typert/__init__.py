"""
`@deepseek-ai/dsh-typert-protocol` / `@deepseek-ai/dsh-typert-registry` parity
package: the minimal Typert runtime consumed through dependency inversion.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from dsh.typert.protocol import (  # noqa: F401
    TypertDisposer,
    TypertLookupDefinition,
    TypertLookupProvider,
    lookup_or_none,
)
from dsh.typert.registry import LookupRegistry, TypertRegistry, default  # noqa: F401

__all__ = [
    "LookupRegistry",
    "TypertDisposer",
    "TypertLookupDefinition",
    "TypertLookupProvider",
    "TypertRegistry",
    "default",
    "lookup_or_none",
]
