"""
Domain declaration vocabulary.
Aligned 1:1 with official `@deepseek-ai/dsh-storage-domain/src/spec`.
"""

from typing import Any, Callable, Dict, List, Optional
from dsh.storage.backend import UNIT_NAME_RE, KvUnitDescriptor


class SchemaValidator:
    """Validator wrapper around a parse callable or schema object."""

    def __init__(self, parse_fn: Any):
        if hasattr(parse_fn, "parse"):
            self._parse_fn = parse_fn.parse
        elif callable(parse_fn):
            self._parse_fn = parse_fn
        else:
            self._parse_fn = lambda x: x

    def parse(self, data: Any) -> Any:
        return self._parse_fn(data)

    def safe_parse(self, data: Any) -> Any:
        try:
            val = self.parse(data)
            return type("SafeParseResult", (), {"success": True, "data": val})()
        except Exception as e:
            return type("SafeParseResult", (), {"success": False, "error": e})()


class DomainGlobalSpec:
    """Global singleton declaration."""

    def __init__(self, schema: Any, initial: Any):
        self.schema = schema if isinstance(schema, SchemaValidator) else SchemaValidator(schema)
        self.initial = initial


class DomainTableSpec:
    """One table declaration."""

    def __init__(self, value_schema: Any):
        self.value_schema = value_schema if isinstance(value_schema, SchemaValidator) else SchemaValidator(value_schema)
        self.valueSchema = self.value_schema


def domain_table(value_schema: Any) -> DomainTableSpec:
    return DomainTableSpec(value_schema)


domainTable = domain_table


class DomainSpec:
    """Static declaration of one domain."""

    def __init__(
        self,
        name: str,
        version: int,
        tables: Dict[str, DomainTableSpec],
        global_spec: Optional[DomainGlobalSpec] = None,
    ):
        self.name = name
        self.version = version
        self.tables = tables
        self.global_spec = global_spec
        self.global_ = global_spec

    @property
    def global_attr(self) -> Optional[DomainGlobalSpec]:
        return self.global_spec


def define_domain(*args: Any, **kwargs: Any) -> DomainSpec:
    """
    Identity helper that validates domain spec fields.
    Accepts positional DomainSpec arguments or dict / kwargs.
    """
    if len(args) == 1 and isinstance(args[0], DomainSpec):
        spec = args[0]
        name = spec.name
        version = spec.version
        tables = spec.tables
        global_spec = spec.global_spec
    elif len(args) == 1 and isinstance(args[0], dict):
        spec_dict = args[0]
        name = spec_dict["name"]
        version = spec_dict.get("version", 0)
        tables = spec_dict.get("tables", {})
        global_spec = spec_dict.get("global", spec_dict.get("global_spec"))
    else:
        name = kwargs.get("name", args[0] if len(args) > 0 else "")
        version = kwargs.get("version", args[1] if len(args) > 1 else 0)
        tables = kwargs.get("tables", args[2] if len(args) > 2 else {})
        global_spec = kwargs.get("global_spec", kwargs.get("global", args[3] if len(args) > 3 else None))

    if not UNIT_NAME_RE.match(name):
        raise ValueError(f"domain name '{name}' must match {UNIT_NAME_RE.pattern}")
    if not isinstance(version, int) or version < 0:
        raise ValueError(f"domain '{name}' version must be a non-negative integer, got {version}")

    tables_dict = tables or {}
    for table_name in tables_dict:
        if not UNIT_NAME_RE.match(table_name):
            raise ValueError(f"domain '{name}' table name '{table_name}' must match {UNIT_NAME_RE.pattern}")

    if global_spec is not None:
        sp_res = global_spec.schema.safe_parse(None)
        if getattr(sp_res, "success", False):
            raise ValueError(
                f"domain '{name}' global schema must not accept null: "
                "null is the medium's \"never written\" sentinel, so a stored null could not round-trip"
            )

    return DomainSpec(name=name, version=version, tables=tables_dict, global_spec=global_spec)


defineDomain = define_domain


def descriptor_of(spec: DomainSpec) -> KvUnitDescriptor:
    has_g = (spec.global_spec is not None or getattr(spec, "global_", None) is not None)
    return KvUnitDescriptor(
        name=spec.name,
        version=spec.version,
        tables=list(spec.tables.keys()),
        has_global=has_g,
    )


descriptorOf = descriptor_of
