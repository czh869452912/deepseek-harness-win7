"""Read the pinned generator's declarative host artifacts without a JS runtime.

This is a restricted data/schema grammar, not eval or a JavaScript interpreter.
Unsupported executable exports fail activation. Local Python artifacts can
provide executable schema objects directly via TYPERT.
"""
import ast
import copy
import math
import re

UNDEFINED = object()


class Schema:
    def __init__(self, kind, args=(), bindings=None):
        self.kind, self.args, self.bindings = kind, args, bindings

    def parse(self, value):
        kind, args = self.kind, self.args
        if kind == "lazy":
            return self.bindings[args[0]].parse(value)
        if kind == "readonly":
            return args[0].parse(value)
        if kind == "optional":
            return UNDEFINED if value is UNDEFINED else args[0].parse(value)
        if kind in ("undefined", "void"):
            if value is UNDEFINED:
                return value
        elif kind == "unknown":
            return copy.deepcopy(value) if value is not UNDEFINED else UNDEFINED
        elif kind == "string" and isinstance(value, str):
            return value
        elif kind == "number" and type(value) in (int, float) and math.isfinite(value):
            return value
        elif kind == "boolean" and type(value) is bool:
            return value
        elif kind == "literal" and type(value) is type(args[0]) and value == args[0]:
            return value
        elif kind == "array" and isinstance(value, list):
            return [args[0].parse(item) for item in value]
        elif kind == "object" and isinstance(value, dict):
            parsed = {}
            for key, schema in args[0].items():
                item = schema.parse(value.get(key, UNDEFINED))
                if item is not UNDEFINED:
                    parsed[key] = item
            return parsed
        elif kind == "record" and isinstance(value, dict):
            return {args[0].parse(key): args[1].parse(item) for key, item in value.items()}
        elif kind == "union":
            for schema in args[0]:
                try:
                    return schema.parse(value)
                except ValueError:
                    pass
        elif kind == "intersection":
            left, right = args[0].parse(value), args[1].parse(value)
            if isinstance(left, dict) and isinstance(right, dict):
                return dict(left, **right)
            if left == right or left is right:
                return left
        raise ValueError("typert: value does not satisfy " + kind + " schema")

    def to_json_schema(self, params=None):
        definitions, active = {}, set()
        def project(schema):
            kind, args = schema.kind, schema.args
            if kind == "lazy":
                name = args[0]
                if name not in definitions and name not in active:
                    active.add(name)
                    definitions[name] = project(schema.bindings[name])
                    active.remove(name)
                return {"$ref": "#/$defs/" + name}
            if kind in ("readonly", "optional"):
                return project(args[0])
            if kind in ("string", "number", "boolean"):
                return {"type": kind}
            if kind == "unknown":
                return {}
            if kind in ("undefined", "void"):
                raise ValueError("typert: undefined has no JSON Schema representation")
            if kind == "literal":
                return {"const": args[0]}
            if kind == "array":
                return {"type": "array", "items": project(args[0])}
            if kind == "record":
                return {"type": "object", "propertyNames": project(args[0]), "additionalProperties": project(args[1])}
            if kind == "object":
                required = []
                for key, child in args[0].items():
                    try:
                        child.parse(UNDEFINED)
                    except ValueError:
                        required.append(key)
                return {"type": "object", "properties": {key: project(child) for key, child in args[0].items()},
                        "required": required, "additionalProperties": False}
            if kind == "union":
                return {"anyOf": [project(child) for child in args[0]]}
            if kind == "intersection":
                return {"allOf": [project(child) for child in args]}
            raise ValueError("typert: unsupported schema projection: " + kind)
        result = project(self)
        if definitions:
            result["$defs"] = definitions
        return result


TOKEN = re.compile(r'''\s+|/\*[\s\S]*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|(?:\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|[A-Za-z_$][\w$]*|=>|[{}\[\]().,:;=\-]''')


class ArtifactParser:
    def __init__(self, source):
        self.tokens, self.position, self.bindings = [], 0, {}
        cursor = 0
        for match in TOKEN.finditer(source):
            if match.start() != cursor:
                raise ValueError("typert: unsupported artifact syntax at offset " + str(cursor))
            cursor = match.end()
            token = match.group()
            if not token.isspace() and not token.startswith(("/*", "//")):
                self.tokens.append(token)
        if cursor != len(source):
            raise ValueError("typert: unsupported artifact suffix")

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or expected is not None and token != expected:
            raise ValueError("typert: expected {!r}, received {!r}".format(expected, token))
        self.position += 1
        return token

    def parse(self):
        for token in ("import", "{", "z", "}", "from"):
            self.take(token)
        if ast.literal_eval(self.take()) != "zod":
            raise ValueError("typert: generated schema artifact must import zod")
        if self.peek() == ";":
            self.take()
        exported = None
        while self.peek() is not None:
            public = self.peek() == "export"
            if public:
                self.take()
            self.take("const")
            name = self.take()
            self.take("=")
            value = self.expression()
            if name in self.bindings:
                raise ValueError("typert: duplicate artifact binding: " + name)
            self.bindings[name] = value
            if public:
                if name != "TYPERT" or exported is not None:
                    raise ValueError("typert: unsupported generated export: " + name)
                exported = value
            if self.peek() == ";":
                self.take()
        if exported is None:
            raise ValueError("typert: artifact has no TYPERT export")
        return exported

    def expression(self):
        token = self.take()
        if token == "z":
            self.take(".")
            kind = self.take()
            self.take("(")
            if kind == "lazy":
                for part in ("(", ")", "=>"):
                    self.take(part)
                args = [self.take()]
            else:
                args = self.sequence(")")
            if kind not in {"lazy", "unknown", "undefined", "void", "string", "number", "boolean", "literal", "object", "array", "record", "union", "intersection"}:
                raise ValueError("typert: unsupported schema constructor: " + kind)
            self.take(")")
            value = Schema(kind, args, self.bindings)
        elif token == "{":
            value = {}
            while self.peek() != "}":
                key = self.take()
                key = ast.literal_eval(key) if key.startswith(("'", '"')) else key
                self.take(":")
                if key in value:
                    raise ValueError("typert: duplicate object key")
                value[key] = self.expression()
                if self.peek() != ",":
                    break
                self.take()
            self.take("}")
        elif token == "[":
            value = self.sequence("]")
            self.take("]")
        elif token.startswith(("'", '"')):
            value = ast.literal_eval(token)
        elif token in ("true", "false", "null"):
            value = {"true": True, "false": False, "null": None}[token]
        elif token[0].isdigit() or token == "-":
            value = ast.literal_eval(token + self.take() if token == "-" else token)
        else:
            if token not in self.bindings:
                raise ValueError("typert: unbound artifact identifier " + token)
            value = self.bindings[token]
        while self.peek() == ".":
            self.take()
            modifier = self.take()
            if modifier not in ("readonly", "optional") or not isinstance(value, Schema):
                raise ValueError("typert: unsupported artifact method " + modifier)
            self.take("(")
            self.take(")")
            value = Schema(modifier, [value], self.bindings)
        return value

    def sequence(self, close):
        values = []
        while self.peek() != close:
            values.append(self.expression())
            if self.peek() != ",":
                break
            self.take()
        return values


def read_generated_artifact(path):
    with open(path, "r", encoding="utf-8") as stream:
        return ArtifactParser(stream.read()).parse()
