"""
Schemastery: Runtime schema validation & type specification DSL for Cordis
1:1 matching reference/vendor/schemastery/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import datetime
import json
import math
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

__schemastery_index__ = 0


class ValidationError(TypeError):
    """
    Error raised when data fails schema validation.
    Matches Schemastery ValidationError with structured path and issues list support.
    """

    def __init__(self, message_or_issues: Any, options: Optional[Dict[str, Any]] = None):
        if isinstance(message_or_issues, list):
            self.issues = message_or_issues
            self.options = options or {}
            lines = []
            for issue in message_or_issues:
                if isinstance(issue, dict):
                    msg = issue.get("message", str(issue))
                    path = issue.get("path")
                    if path:
                        path_str = ".".join(str(p) for p in path) if isinstance(path, (list, tuple)) else str(path)
                        lines.append(f"  - {msg} (at {path_str})")
                    else:
                        lines.append(f"  - {msg}")
                else:
                    lines.append(f"  - {issue}")
            full_msg = "invalid config:\n" + "\n".join(lines)
            super().__init__(full_msg)
            self.message = full_msg
            self.path = []
            return

        self.options = options or {}
        self.path = self.options.get("path", [])

        prefix = "$"
        for segment in self.path:
            if isinstance(segment, str):
                prefix += f".{segment}"
            elif isinstance(segment, int):
                prefix += f"[{segment}]"
            else:
                prefix += f"[{segment}]"

        if prefix.startswith("."):
            prefix = prefix[1:]

        msg_str = str(message_or_issues)
        self.raw_message = msg_str
        full_msg = msg_str if prefix == "$" else f"{prefix} {msg_str}"
        super().__init__(full_msg)
        self.message = full_msg


def deep_equal(a: Any, b: Any, is_dict: bool = False) -> bool:
    if a == b:
        return True
    if type(a) != type(b):
        return False
    if isinstance(a, dict):
        if len(a) != len(b):
            return False
        for k in a:
            if k not in b or not deep_equal(a[k], b[k]):
                return False
        return True
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if not deep_equal(x, y):
                return False
        return True
    return False


def is_nullable(val: Any) -> bool:
    return val is None


class Schema:
    """
    Schemastery Schema definition matching reference/vendor/schemastery/src/index.ts.
    Provides fluent builder methods, validation, simplification, i18n, and JSON serialization.
    """

    resolvers: Dict[str, Callable[..., Any]] = {}

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        global __schemastery_index__
        self.uid: int = __schemastery_index__
        __schemastery_index__ += 1

        self.type: str = "any"
        self.meta: Dict[str, Any] = {}
        self.value: Any = None
        self.inner: Optional["Schema"] = None
        self.s_key: Optional["Schema"] = None
        self.list: Optional[List["Schema"]] = None
        self.dict: Optional[Dict[str, "Schema"]] = None
        self.bits: Optional[Dict[str, int]] = None
        self.callback: Optional[Callable[..., Any]] = None
        self.constructor: Optional[Any] = None
        self.builder: Optional[Callable[[], "Schema"]] = None
        self.preserve: bool = False

        if options:
            for k, v in options.items():
                setattr(self, k, v)
        if not isinstance(self.meta, dict):
            self.meta = {}

    def __call__(self, data: Any = None, options: Optional[Dict[str, Any]] = None) -> Any:
        return Schema.resolve(data, self, options or {})[0]

    # --- Standard Schema V1 compatibility (@standard-schema/spec) ---
    @property
    def standard(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "vendor": "cordis",
            "validate": self.validate,
        }

    def __getitem__(self, item: str) -> Any:
        if item in ("~standard", "standard"):
            return self.standard
        raise KeyError(item)

    def validate(self, value: Any) -> Dict[str, Any]:
        try:
            res = Schema.resolve(value, self, {})[0]
            return {"value": res}
        except ValidationError as err:
            return {
                "issues": [
                    {
                        "message": getattr(err, "raw_message", str(err)),
                        "path": getattr(err, "path", []),
                    }
                ]
            }
        except Exception as e:
            return {
                "issues": [
                    {
                        "message": str(e),
                        "path": [],
                    }
                ]
            }

    # --- Fluent modifier methods (return a clone with updated meta) ---
    def _clone(self) -> "Schema":
        s = Schema()
        s.type = self.type
        s.meta = dict(self.meta)
        s.value = self.value
        s.inner = self.inner
        s.s_key = self.s_key
        s.list = list(self.list) if self.list is not None else None
        s.dict = dict(self.dict) if self.dict is not None else None
        s.bits = dict(self.bits) if self.bits is not None else None
        s.callback = self.callback
        s.constructor = self.constructor
        s.builder = self.builder
        s.preserve = self.preserve
        return s

    def required(self, value: bool = True) -> "Schema":
        s = self._clone()
        s.meta["required"] = value
        return s

    def hidden(self, value: bool = True) -> "Schema":
        s = self._clone()
        s.meta["hidden"] = value
        return s

    def loose(self, value: bool = True) -> "Schema":
        s = self._clone()
        s.meta["loose"] = value
        return s

    def disabled(self, value: bool = True) -> "Schema":
        s = self._clone()
        s.meta["disabled"] = value
        return s

    def collapse(self, value: bool = True) -> "Schema":
        s = self._clone()
        s.meta["collapse"] = value
        return s

    def role(self, text: str, extra: Any = None) -> "Schema":
        s = self._clone()
        s.meta["role"] = text
        if extra is not None:
            s.meta["extra"] = extra
        return s

    def link(self, url: str) -> "Schema":
        s = self._clone()
        s.meta["link"] = url
        return s

    def default(self, val: Any) -> "Schema":
        s = self._clone()
        s.meta["default"] = val
        return s

    def comment(self, text: str) -> "Schema":
        s = self._clone()
        s.meta["comment"] = text
        return s

    def description(self, text: str) -> "Schema":
        s = self._clone()
        s.meta["description"] = text
        return s

    def deprecated(self) -> "Schema":
        s = self._clone()
        badges = list(s.meta.get("badges", []))
        badges.append({"text": "deprecated", "type": "danger"})
        s.meta["badges"] = badges
        return s

    def experimental(self) -> "Schema":
        s = self._clone()
        badges = list(s.meta.get("badges", []))
        badges.append({"text": "experimental", "type": "warning"})
        s.meta["badges"] = badges
        return s

    def badges(self, badge_list: List[Dict[str, str]]) -> "Schema":
        s = self._clone()
        s.meta["badges"] = list(badge_list)
        return s

    def pattern(self, regex: Union[str, re.Pattern]) -> "Schema":
        s = self._clone()
        if isinstance(regex, str):
            s.meta["pattern"] = {"source": regex, "flags": ""}
        else:
            s.meta["pattern"] = {"source": regex.pattern, "flags": str(regex.flags)}
        return s

    def max(self, value: Union[int, float]) -> "Schema":
        s = self._clone()
        s.meta["max"] = value
        return s

    def min(self, value: Union[int, float]) -> "Schema":
        s = self._clone()
        s.meta["min"] = value
        return s

    def step(self, value: Union[int, float]) -> "Schema":
        s = self._clone()
        s.meta["step"] = value
        return s

    def extra(self, key: str, value: Any) -> "Schema":
        s = self._clone()
        s.meta[key] = value
        return s

    def set(self, key: str, value: "Schema") -> "Schema":
        if self.dict is None:
            self.dict = {}
        self.dict[key] = value
        return self

    def push(self, value: "Schema") -> "Schema":
        if self.list is None:
            self.list = []
        self.list.append(value)
        return self

    def i18n(self, messages: Dict[str, Any]) -> "Schema":
        s = self._clone()
        desc = s.meta.get("description")
        desc_dict: Dict[str, str] = {"": desc} if isinstance(desc, str) else dict(desc or {})
        for locale, val in messages.items():
            if isinstance(val, dict):
                d = val.get("$description") or val.get("$desc") or val.get("")
                if d:
                    desc_dict[locale] = d
            elif isinstance(val, str):
                desc_dict[locale] = val
        if desc_dict:
            s.meta["description"] = desc_dict
        if s.dict:
            new_dict = {}
            for k, inner in s.dict.items():
                sub_msg = {}
                for loc, m in messages.items():
                    if isinstance(m, dict):
                        sub_val = m.get(k) or (m.get("$value") or m.get("$inner") or {}).get(k)
                        if sub_val is not None:
                            sub_msg[loc] = sub_val
                    elif isinstance(m, str):
                        sub_msg[loc] = m
                new_dict[k] = inner.i18n(sub_msg)
            s.dict = new_dict
        if s.list:
            s.list = [inner.i18n(messages) for inner in s.list]
        if s.inner:
            s.inner = s.inner.i18n(messages)
        return s

    def simplify(self, value: Any = None) -> Any:
        """Strip values equal to default schema values matching TS Schema.simplify()."""
        default_val = self.meta.get("default")
        if default_val is not None and deep_equal(value, default_val, self.type == "dict"):
            return None
        if is_nullable(value):
            return value

        if self.type in ("object", "dict"):
            if not isinstance(value, dict):
                return value
            res: Dict[str, Any] = {}
            for k, v in value.items():
                schema = self.dict.get(k) if self.type == "object" and self.dict else self.inner
                item = schema.simplify(v) if schema else v
                if self.type == "dict" or not is_nullable(item):
                    res[k] = item
            if default_val is not None and deep_equal(res, default_val, self.type == "dict"):
                return None
            if not res and not self.meta.get("default"):
                return None
            return res
        elif self.type in ("array", "tuple"):
            if not isinstance(value, (list, tuple)):
                return value
            arr: List[Any] = []
            for idx, v in enumerate(value):
                schema = self.inner if self.type == "array" else (self.list[idx] if self.list and idx < len(self.list) else None)
                item = schema.simplify(v) if schema else v
                arr.append(item)
            if default_val is not None and deep_equal(arr, default_val):
                return None
            return arr
        elif self.type == "intersect" and self.list:
            res = {}
            for item in self.list:
                s_res = item.simplify(value)
                if isinstance(s_res, dict):
                    res.update(s_res)
            return res
        elif self.type == "union" and self.list:
            for schema in self.list:
                try:
                    Schema.resolve(value, schema, {})
                    return schema.simplify(value)
                except Exception:
                    pass
        return value

    def to_json(self) -> Dict[str, Any]:
        """Serialize schema definition matching TS toJSON()."""
        res: Dict[str, Any] = {
            "uid": self.uid,
            "type": self.type,
            "meta": self.meta,
        }
        if self.value is not None:
            res["value"] = self.value
        if self.inner:
            res["inner"] = self.inner.to_json()
        if self.s_key:
            res["sKey"] = self.s_key.to_json()
        if self.list:
            res["list"] = [s.to_json() for s in self.list]
        if self.dict:
            res["dict"] = {k: v.to_json() for k, v in self.dict.items()}
        if self.bits:
            res["bits"] = self.bits
        return res

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert Schemastery Schema to standard JSON Schema Draft-07 matching TS Schemastery."""
        json_schema: Dict[str, Any] = {}

        if self.type == "string":
            json_schema["type"] = "string"
            if self.meta.get("pattern"):
                pat = self.meta["pattern"]
                json_schema["pattern"] = pat.get("source", pat) if isinstance(pat, dict) else str(pat)
        elif self.type == "number":
            json_schema["type"] = "number"
            if "min" in self.meta:
                json_schema["minimum"] = self.meta["min"]
            if "max" in self.meta:
                json_schema["maximum"] = self.meta["max"]
            if "step" in self.meta:
                json_schema["multipleOf"] = self.meta["step"]
        elif self.type == "boolean":
            json_schema["type"] = "boolean"
        elif self.type == "const":
            json_schema["const"] = self.value
        elif self.type == "array":
            json_schema["type"] = "array"
            if self.inner:
                json_schema["items"] = self.inner.to_json_schema()
            if "min" in self.meta:
                json_schema["minItems"] = self.meta["min"]
            if "max" in self.meta:
                json_schema["maxItems"] = self.meta["max"]
        elif self.type == "dict":
            json_schema["type"] = "object"
            if self.inner:
                json_schema["additionalProperties"] = self.inner.to_json_schema()
        elif self.type == "object":
            json_schema["type"] = "object"
            props: Dict[str, Any] = {}
            required: List[str] = []
            if self.dict:
                for k, s in self.dict.items():
                    props[k] = s.to_json_schema()
                    if s.meta.get("required"):
                        required.append(k)
            json_schema["properties"] = props
            if required:
                json_schema["required"] = required
        elif self.type == "tuple":
            json_schema["type"] = "array"
            if self.list:
                json_schema["items"] = [s.to_json_schema() for s in self.list]
                json_schema["minItems"] = len(self.list)
                json_schema["maxItems"] = len(self.list)
        elif self.type == "union":
            if self.list:
                json_schema["anyOf"] = [s.to_json_schema() for s in self.list]
        elif self.type == "intersect":
            if self.list:
                json_schema["allOf"] = [s.to_json_schema() for s in self.list]
        elif self.type == "bitset":
            json_schema["type"] = "integer"
        elif self.type == "any":
            pass
        elif self.type == "never":
            json_schema["not"] = {}
        elif self.type == "lazy" and self.builder:
            built = self.builder()
            return built.to_json_schema()
        elif self.type == "transform" and self.inner:
            return self.inner.to_json_schema()

        if "description" in self.meta:
            desc = self.meta["description"]
            json_schema["description"] = desc.get("zh", str(desc)) if isinstance(desc, dict) else str(desc)
        if "default" in self.meta and self.meta["default"] is not None:
            json_schema["default"] = self.meta["default"]

        return json_schema

    def __repr__(self) -> str:
        return f"Schema<{self.type}>"

    # --- Factory Classmethods matching TS Schemastery.Static ---
    @classmethod
    def extend(cls, type_name: str, resolve_fn: Callable[..., Any]) -> None:
        cls.resolvers[type_name] = resolve_fn

    @classmethod
    def any(cls) -> "Schema":
        return cls({"type": "any"})

    @classmethod
    def never(cls) -> "Schema":
        return cls({"type": "never"})

    @classmethod
    def const_(cls, value: Any) -> "Schema":
        return cls({"type": "const", "value": value})

    @classmethod
    def string(cls) -> "Schema":
        return cls({"type": "string"})

    @classmethod
    def number(cls) -> "Schema":
        return cls({"type": "number"})

    @classmethod
    def natural(cls) -> "Schema":
        return cls.number().step(1).min(0)

    @classmethod
    def percent(cls) -> "Schema":
        return cls.number().step(0.01).min(0).max(1).role("slider")

    @classmethod
    def boolean(cls) -> "Schema":
        return cls({"type": "boolean"})

    @classmethod
    def date(cls) -> "Schema":
        def _parse_date(val: Any, opt: Any) -> datetime.datetime:
            if isinstance(val, (datetime.datetime, datetime.date)):
                return val
            if isinstance(val, str):
                try:
                    return datetime.datetime.fromisoformat(val)
                except Exception:
                    raise ValidationError(f"invalid date '{val}'", opt)
            raise ValidationError(f"expected Date or date string but got {val}", opt)

        return cls.union([
            cls.is_(datetime.datetime),
            cls.is_(datetime.date),
            cls.transform(cls.string().role("datetime"), _parse_date, preserve=True)
        ])

    @classmethod
    def reg_exp(cls, flag: str = "") -> "Schema":
        def _parse_regex(val: Any, opt: Any) -> re.Pattern:
            if isinstance(val, re.Pattern):
                return val
            if isinstance(val, str):
                try:
                    re_flags = 0
                    if "i" in flag: re_flags |= re.IGNORECASE
                    if "m" in flag: re_flags |= re.MULTILINE
                    if "s" in flag: re_flags |= re.DOTALL
                    return re.compile(val, re_flags)
                except Exception as e:
                    raise ValidationError(str(e), opt)
            raise ValidationError(f"expected RegExp or regex string but got {val}", opt)

        return cls.union([
            cls.is_(re.Pattern),
            cls.transform(cls.string().role("regexp", {"flag": flag}), _parse_regex, preserve=True)
        ])

    @classmethod
    def array_buffer(cls, encoding: Optional[str] = None) -> "Schema":
        def _parse_str(val: Any, opt: Any) -> bytes:
            if isinstance(val, (bytes, bytearray, memoryview)):
                return bytes(val)
            if isinstance(val, str) and encoding:
                try:
                    if encoding == "base64":
                        import base64
                        return base64.b64decode(val)
                    elif encoding == "hex":
                        import binascii
                        return binascii.unhexlify(val)
                except Exception as e:
                    raise ValidationError(f"invalid binary encoding: {e}", opt)
            raise ValidationError(f"expected binary but got {val}", opt)

        branches = [
            cls.is_(bytes),
            cls.is_(bytearray),
            cls.is_(memoryview),
        ]
        if encoding:
            branches.append(cls.transform(cls.string(), _parse_str, preserve=True))
        return cls.union(branches)

    @classmethod
    def bitset(cls, bits: Dict[str, int]) -> "Schema":
        return cls({"type": "bitset", "bits": bits})

    @classmethod
    def function(cls) -> "Schema":
        return cls({"type": "function"})

    @classmethod
    def is_(cls, constructor: Any) -> "Schema":
        return cls({"type": "is", "constructor": constructor})

    @classmethod
    def array(cls, inner: Any) -> "Schema":
        return cls({"type": "array", "inner": cls.from_(inner)})

    @classmethod
    def dict(cls, inner: Any, s_key: Any = None) -> "Schema":
        return cls({
            "type": "dict",
            "inner": cls.from_(inner),
            "s_key": cls.from_(s_key) if s_key else None
        })

    @classmethod
    def tuple(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        return cls({"type": "tuple", "list": [cls.from_(x) for x in list_types]})

    @classmethod
    def object(cls, dict_types: Dict[str, Any]) -> "Schema":
        return cls({"type": "object", "dict": {k: cls.from_(v) for k, v in dict_types.items()}})

    @classmethod
    def union(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        return cls({"type": "union", "list": [cls.from_(x) for x in list_types]})

    @classmethod
    def intersect(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        return cls({"type": "intersect", "list": [cls.from_(x) for x in list_types]})

    @classmethod
    def transform(cls, inner: Any, callback: Callable[..., Any], preserve: bool = False) -> "Schema":
        return cls({"type": "transform", "inner": cls.from_(inner), "callback": callback, "preserve": preserve})

    @classmethod
    def lazy(cls, builder: Callable[[], "Schema"]) -> "Schema":
        return cls({"type": "lazy", "builder": builder})

    @classmethod
    def dynamic(cls, builder: Callable[..., "Schema"]) -> "Schema":
        """Dynamic schema factory matching TS Schemastery.dynamic."""
        return cls({"type": "lazy", "builder": builder})

    @classmethod
    def computed(cls, callback: Callable[..., Any]) -> "Schema":
        """Computed schema property based on context or sibling values."""
        def _resolve_computed(data: Any, opt: Any) -> Any:
            res = callback(opt.get("root", data)) if len(inspect_params(callback)) >= 1 else callback()
            return res
        return cls.transform(cls.any(), _resolve_computed)


    @classmethod
    def from_(cls, source: Any) -> "Schema":
        if is_nullable(source):
            return cls.any()
        if isinstance(source, Schema):
            return source
        if isinstance(source, (str, int, float, bool)):
            return cls.const_(source).required()
        if source is str:
            return cls.string().required()
        if source in (int, float):
            return cls.number().required()
        if source is bool:
            return cls.boolean().required()
        if callable(source) and not isinstance(source, type):
            return cls.function().required()
        if isinstance(source, type):
            return cls.is_(source).required()
        raise TypeError(f"cannot infer schema from {source}")

    # 1:1 camelCase and standard aliases matching Schemastery
    const = const_
    is_type = is_
    from_type = from_
    regExp = reg_exp
    arrayBuffer = array_buffer

    @classmethod
    def resolve(cls, data: Any, schema: "Schema", options: Optional[Dict[str, Any]] = None, strict: bool = False) -> Tuple[Any, Any]:
        opt = options or {}
        if not schema:
            return data, None

        if is_nullable(data) and schema.type != "lazy":
            if schema.meta.get("required"):
                raise ValidationError("missing required value", opt)
            fallback = schema.meta.get("default")
            if is_nullable(fallback):
                return data, None
            data = copy.deepcopy(fallback)

        cb = cls.resolvers.get(schema.type)
        if not cb:
            raise ValidationError(f"unsupported type \"{schema.type}\"", opt)

        try:
            return cb(data, schema, opt, strict)
        except Exception as error:
            if schema.meta.get("loose"):
                return schema.meta.get("default"), None
            raise error


# --- Built-in Type Resolvers matching TS schemastery resolvers ---

def _check_range(data: Union[int, float], meta: Dict[str, Any], description: str, opt: Dict[str, Any]) -> None:
    max_val = meta.get("max", math.inf)
    min_val = meta.get("min", -math.inf)
    if data > max_val:
        raise ValidationError(f"expected {description} <= {max_val} but got {data}", opt)
    if data < min_val:
        raise ValidationError(f"expected {description} >= {min_val} but got {data}", opt)


def _resolve_lazy(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    inner = schema.builder() if schema.builder else schema.inner
    if inner is not None:
        inner.meta = {**schema.meta, **inner.meta}
    return Schema.resolve(data, inner, opt, strict)



def _resolve_any(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    return data, None


def _resolve_never(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    raise ValidationError(f"expected nullable but got {data}", opt)


def _resolve_const(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if deep_equal(data, schema.value):
        return schema.value, None
    raise ValidationError(f"expected {schema.value} but got {data}", opt)


def _resolve_string(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, str):
        raise ValidationError(f"expected string but got {data}", opt)
    pat = schema.meta.get("pattern")
    if pat:
        src = pat.get("source", "")
        if not re.search(src, data):
            raise ValidationError(f"expect string to match regexp {src}", opt)
    _check_range(len(data), schema.meta, "string length", opt)
    return data, None


def _resolve_number(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, (int, float)) or isinstance(data, bool):
        raise ValidationError(f"expected number but got {data}", opt)
    _check_range(data, schema.meta, "number", opt)
    step = schema.meta.get("step")
    if step:
        min_v = schema.meta.get("min", 0)
        diff = abs(data - min_v)
        if abs(diff % step) > 1e-9 and abs((diff % step) - step) > 1e-9:
            raise ValidationError(f"expected number multiple of {step} but got {data}", opt)
    return data, None


def _resolve_boolean(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, bool):
        raise ValidationError(f"expected boolean but got {data}", opt)
    return data, None


def _resolve_bitset(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    bits = schema.bits or {}
    val = 0
    keys = []
    if isinstance(data, int) and not isinstance(data, bool):
        val = data
        for k, b in bits.items():
            if data & b:
                keys.append(k)
    elif isinstance(data, (list, tuple)):
        keys = list(data)
        for k in keys:
            if not isinstance(k, str):
                raise ValidationError(f"expected string but got {k}", opt)
            if k in bits:
                val |= bits[k]
    else:
        raise ValidationError(f"expected number or array but got {data}", opt)
    return val, keys


def _resolve_function(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not callable(data):
        raise ValidationError(f"expected function but got {data}", opt)
    return data, None


def _resolve_is(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    ctor = schema.constructor
    if isinstance(ctor, type):
        if isinstance(data, ctor):
            return data, None
        raise ValidationError(f"expected {ctor.__name__} but got {data}", opt)
    if isinstance(ctor, str):
        if is_nullable(data):
            raise ValidationError(f"expected {ctor} but got {data}", opt)
        if type(data).__name__ == ctor:
            return data, None
        raise ValidationError(f"expected {ctor} but got {data}", opt)
    return data, None


def _property(data: Any, key: Any, schema: Schema, opt: Dict[str, Any]) -> Any:
    cur_path = list(opt.get("path", []))
    cur_path.append(key)
    sub_opt = {**opt, "path": cur_path}
    val = data.get(key) if isinstance(data, dict) else (data[key] if isinstance(data, (list, tuple)) and 0 <= key < len(data) else None)
    res, adapted = Schema.resolve(val, schema, sub_opt)
    return res


def _resolve_array(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, (list, tuple)):
        raise ValidationError(f"expected array but got {data}", opt)
    _check_range(len(data), schema.meta, "array length", opt)
    inner = schema.inner or Schema.any()
    res = [_property(data, i, inner, opt) for i in range(len(data))]
    return res, None


def _resolve_dict(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, dict):
        raise ValidationError(f"expected object but got {data}", opt)
    inner = schema.inner or Schema.any()
    s_key = schema.s_key
    res = {}
    for k, v in data.items():
        rk = k
        if s_key:
            try:
                rk = Schema.resolve(k, s_key, opt)[0]
            except Exception as e:
                if strict:
                    continue
                raise e
        res[rk] = _property(data, k, inner, opt)
    return res, None


def _resolve_tuple(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, (list, tuple)):
        raise ValidationError(f"expected array but got {data}", opt)
    items = schema.list or []
    res = [_property(data, i, items[i], opt) for i in range(min(len(data), len(items)))]
    if not strict and len(data) > len(items):
        res.extend(data[len(items):])
    return res, None


def _resolve_object(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, dict):
        raise ValidationError(f"expected object but got {data}", opt)
    d = schema.dict or {}
    res = {}
    for k, sub_schema in d.items():
        val = _property(data, k, sub_schema, opt)
        if not is_nullable(val) or k in data:
            res[k] = val
    if not strict:
        for k, v in data.items():
            if k not in res:
                res[k] = v
    return res, None


def _resolve_union(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    items = schema.list or []
    issues = []
    for inner in items:
        try:
            return Schema.resolve(data, inner, opt, strict)
        except Exception as e:
            issues.append(str(e))
    raise ValidationError(f"expected union but got {json.dumps(data, default=str)}", opt)


def _resolve_intersect(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    items = schema.list or []
    if not items:
        return data, None
    res = None
    for inner in items:
        val = Schema.resolve(data, inner, opt, True)[0]
        if is_nullable(val):
            continue
        if is_nullable(res):
            res = val
        elif type(res) != type(val):
            raise ValidationError(f"expected intersect matching types but got {data}", opt)
        elif isinstance(val, dict):
            res.update(val)
        elif res != val:
            raise ValidationError(f"expected intersect but got {data}", opt)
    if not strict and isinstance(data, dict):
        if res is None:
            res = {}
        for k, v in data.items():
            if k not in res:
                res[k] = v
    return res if res is not None else data, None


def _resolve_transform(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    inner = schema.inner or Schema.any()
    res, adapted = Schema.resolve(data, inner, opt, True)
    if schema.callback:
        transformed = schema.callback(res, opt) if len(inspect_params(schema.callback)) >= 2 else schema.callback(res)
        return transformed, (data if schema.preserve else adapted)
    return res, None


def inspect_params(fn: Callable[..., Any]) -> List[str]:
    import inspect
    try:
        sig = inspect.signature(fn)
        return list(sig.parameters.keys())
    except Exception:
        return ["val"]


# Register all standard resolvers
Schema.extend("lazy", _resolve_lazy)
Schema.extend("any", _resolve_any)
Schema.extend("never", _resolve_never)
Schema.extend("const", _resolve_const)
Schema.extend("string", _resolve_string)
Schema.extend("number", _resolve_number)
Schema.extend("boolean", _resolve_boolean)
Schema.extend("bitset", _resolve_bitset)
Schema.extend("function", _resolve_function)
Schema.extend("is", _resolve_is)
Schema.extend("array", _resolve_array)
Schema.extend("dict", _resolve_dict)
Schema.extend("tuple", _resolve_tuple)
Schema.extend("object", _resolve_object)
Schema.extend("union", _resolve_union)
Schema.extend("intersect", _resolve_intersect)
Schema.extend("transform", _resolve_transform)

# Export shorthand alias 'z' matching Schemastery / Zod convention
z = Schema
