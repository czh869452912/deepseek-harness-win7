"""
Compiler-independent Typert protocol records.

Ported 1:1 from the runtime half of reference
`packages/typert/protocol/src/types.ts` (the `TypertLookupProvider` /
`TypertLookupDefinition` / `TypertDisposer` runtime declarations consumed
through dependency inversion). The type-level lookups
(`TypertLookup`/`TypertLookupMap` merge declarations, unique-symbol host/wire
brands and the strict-generator type model) have no runtime observable and no
Python 3.8.10 equivalent, so only the runtime provider contract is ported.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Callable, Dict, Optional

#: A disposer withdrawing one registration, 1:1 with `TypertDisposer`.
TypertDisposer = Callable[[], None]


class TypertLookupProvider:
    """
    Runtime provider for one declared Host object lookup, 1:1 with reference
    `TypertLookupProvider` (types.ts:322-337):

    - `parameter`: source parameter name recognized by the SRC weak parser;
    - `wire`: wire field replacing the Host object parameter;
    - `hostTypeSymbol` / `wireTypeSymbol`: canonical type symbols used by
      strict generation;
    - `resolve(id)`: resolve a wire identity through the provider's default
      policy, returning the object, `undefined` (`None`) when unavailable, or
      either asynchronously.
    """

    def __init__(
        self,
        parameter: str,
        wire: str,
        host_type_symbol: str,
        wire_type_symbol: str,
        resolve: Callable[[Any], Any],
    ):
        self.parameter = parameter
        self.wire = wire
        self.host_type_symbol = host_type_symbol
        self.wire_type_symbol = wire_type_symbol
        self.resolve = resolve

    # camelCase aliases 1:1 with the reference field names
    @property
    def hostTypeSymbol(self) -> str:
        return self.host_type_symbol

    @property
    def wireTypeSymbol(self) -> str:
        return self.wire_type_symbol

    def to_dict(self) -> Dict[str, Any]:
        """The provider's stable declaration fields (no resolver)."""
        return {
            "parameter": self.parameter,
            "wire": self.wire,
            "hostTypeSymbol": self.host_type_symbol,
            "wireTypeSymbol": self.wire_type_symbol,
        }

    def __repr__(self) -> str:
        return f"<TypertLookupProvider {self.parameter!r}->{self.wire!r}>"


class TypertLookupDefinition:
    """
    Stable wire declaration retained after a lookup provider unloads, 1:1 with
    reference `TypertLookupDefinition` (types.ts:340-351).
    """

    def __init__(
        self,
        key: str,
        parameter: str,
        wire: str,
        host_type_symbol: str,
        wire_type_symbol: str,
    ):
        self.key = key
        self.parameter = parameter
        self.wire = wire
        self.host_type_symbol = host_type_symbol
        self.wire_type_symbol = wire_type_symbol

    @classmethod
    def from_provider(cls, key: str, provider: TypertLookupProvider) -> "TypertLookupDefinition":
        return cls(
            key=key,
            parameter=provider.parameter,
            wire=provider.wire,
            host_type_symbol=provider.host_type_symbol,
            wire_type_symbol=provider.wire_type_symbol,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "parameter": self.parameter,
            "wire": self.wire,
            "hostTypeSymbol": self.host_type_symbol,
            "wireTypeSymbol": self.wire_type_symbol,
        }


def lookup_or_none(registry: Any, key: str) -> Optional[TypertLookupProvider]:
    """`registry.lookups.get(key)` shorthand returning `undefined` (`None`)."""
    return registry.get(key)
