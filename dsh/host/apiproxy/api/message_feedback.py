"""
Message Feedback Domain Handler (`@deepseek-ai/dsh-apiproxy/api/message-feedback`).

The shipped Web Host serves the `messageFeedback` Remote namespace over
`/api/messageFeedback/{list,put,delete}`. The reference exposes it through the
Typert Remote gateway (`reference/packages/api/gateway/src/index.ts`), which
never lets a raw request reach the business method:

  - `remoteRequest` requires a payload of exactly one plain-object `args` field
    (`Remote payload must contain exactly one plain-object args field`);
  - `assertExactArguments` requires the args keys to match the descriptor's
    declared wire fields exactly (`args fields do not match the descriptor:
    missing "request"` / `unexpected "x"`);
  - `decode` runs the generated strict codec for the field, and any failure
    becomes `wire field "request" failed boundary validation`;
  - the gateway maps any non-business error onto
    `{ ok: false, error: { code: 'internal', message, details: {} } }`
    (`rpcFailure`), while the business result itself travels inside the
    successful server-response value.

The codec is generated from the declared request types by
`reference/packages/typert/generator/src/emitter.ts`, whose `typeSchema`
projects a `Branded<B>` id as `z.intersection(z.string(), z.unknown())`
(`reference/packages/util/brand/src/index.ts` — a brand is a type-only
primitive), a string union as `z.union([z.literal(...), ...])`, a `| null`
union as `z.union([..., z.null()])`, and `note?: string` as
`z.string().optional()`. So, per method:

  list:   { sessionId: string }
  put:    { sessionId: string, messageId: string,
            rating: 'positive' | 'negative',
            note?: string, ifVersion: string | null }
  delete: { sessionId: string, messageId: string, ifVersion: string }

A zod object requires every non-optional key to be present, accepts any string
(an id brand has no runtime refinement, so an empty string is a boundary-legal
value the business union then judges), rejects a present `null` for an optional
string, strips unknown keys, and rejects a non-object value outright.

This handler reproduces that boundary for the three messageFeedback endpoints:
the `request` argument is validated against the declared request shape before
the service is touched, so an invalid rating is rejected before any write.
"""

from typing import Any, Callable, Dict, Tuple

NAMESPACE = "messageFeedback"

#: The exact Gateway namespace method names, in the reference's declaration order.
METHOD_NAMES: Tuple[str, ...] = ("list", "put", "delete")

RATINGS = ("positive", "negative")

#: `remoteRequest`'s payload-shape refusal, verbatim.
PAYLOAD_ERROR = "Remote payload must contain exactly one plain-object args field"

#: `decode`'s per-field refusal, verbatim (`field` is always `request` here).
BOUNDARY_ERROR = 'wire field "request" failed boundary validation'

#: `resolveDescriptor`'s refusal for an endpoint nothing exports.
UNEXPORTED_ERROR = "no active Remote method exports this endpoint"

#: The single wire field every messageFeedback method declares.
WIRE_FIELDS: Tuple[str, ...] = ("request",)

#: Absence marker distinguishing an omitted key from a present `None` (JS
#: `undefined`-vs-`null` for a JSON body), as `Object.hasOwn` does upstream.
_MISSING = object()


class TypertGatewayError(Exception):
    """A gateway-boundary failure: category, canonical endpoint, diagnostic."""

    def __init__(self, code: str, endpoint: str, message: str):
        super().__init__("typert gateway: %s: %s" % (endpoint, message))
        self.code = code
        self.endpoint = endpoint
        self.message = message


def _endpoint(method: str) -> str:
    return "%s/%s" % (NAMESPACE, method)


def _is_plain_object(value: Any) -> bool:
    """`isPlainObject`: a JSON object, never a list or a scalar."""
    return isinstance(value, dict)


def _boundary(endpoint: str) -> TypertGatewayError:
    return TypertGatewayError("input-invalid", endpoint, BOUNDARY_ERROR)


def _require_string(endpoint: str, request: Dict[str, Any], field: str) -> str:
    """
    One required wire string.

    The generated codec is a runtime string brand, so every string passes —
    including `''`; only absence or a non-string fails the boundary.
    """
    value = request.get(field, _MISSING)
    if value is _MISSING or not isinstance(value, str):
        raise _boundary(endpoint)
    return value


def endpoint_request(method: str, payload: Any) -> Any:
    """
    Extract the strict `args.request` wire field, exactly like the gateway's
    `remoteRequest` + `assertExactArguments` pair.
    """
    endpoint = _endpoint(method)
    if not _is_plain_object(payload) or len(payload) != 1 or "args" not in payload:
        raise TypertGatewayError("arguments-invalid", endpoint, PAYLOAD_ERROR)
    args = payload["args"]
    if not _is_plain_object(args):
        raise TypertGatewayError("arguments-invalid", endpoint, PAYLOAD_ERROR)
    missing = [field for field in WIRE_FIELDS if field not in args]
    extra = [key for key in args.keys() if key not in WIRE_FIELDS]
    if missing or extra:
        clauses = []
        if missing:
            clauses.append("missing " + ", ".join('"%s"' % field for field in missing))
        if extra:
            clauses.append("unexpected " + ", ".join('"%s"' % str(key) for key in extra))
        raise TypertGatewayError(
            "arguments-invalid",
            endpoint,
            "args fields do not match the descriptor: " + "; ".join(clauses),
        )
    return args["request"]


def validate_wire_request(method: str, request: Any) -> Dict[str, Any]:
    """
    Validate one decoded `request` value against the declared request shape.

    The codec is a zod object: the value must be a plain object, every declared
    non-optional field must be present, a present field must match its declared
    type, and unknown fields are dropped rather than rejected.
    """
    endpoint = _endpoint(method)
    if not _is_plain_object(request):
        raise _boundary(endpoint)
    decoded: Dict[str, Any] = {"sessionId": _require_string(endpoint, request, "sessionId")}
    if method == "list":
        return decoded

    decoded["messageId"] = _require_string(endpoint, request, "messageId")
    if method == "delete":
        # `MessageFeedbackVersion` (never nullable) is required by presence.
        decoded["ifVersion"] = _require_string(endpoint, request, "ifVersion")
        return decoded

    rating = request.get("rating", _MISSING)
    if rating is _MISSING or rating not in RATINGS:
        raise _boundary(endpoint)
    decoded["rating"] = rating
    note = request.get("note", _MISSING)
    if note is not _MISSING:
        # `z.string().optional()` admits absence, never an explicit `null`.
        if not isinstance(note, str):
            raise _boundary(endpoint)
        decoded["note"] = note
    ifVersion = request.get("ifVersion", _MISSING)
    if ifVersion is _MISSING:
        raise _boundary(endpoint)
    if ifVersion is not None and not isinstance(ifVersion, str):
        raise _boundary(endpoint)
    decoded["ifVersion"] = ifVersion
    return decoded


class MessageFeedbackDomainHandler:
    """Serves the `messageFeedback` Remote namespace over the `/api` carrier."""

    def __init__(self, ctx: Any):
        self.ctx = ctx

    def _service(self) -> Any:
        service = None
        if hasattr(self.ctx, "get"):
            service = self.ctx.get("messageFeedback") or self.ctx.get("message_feedback")
        return service

    async def invoke(self, method: str, payload: Any) -> Dict[str, Any]:
        """
        Decode one wire invocation and return the business result.

        Ordering is the gateway's: the endpoint resolves (an unexported method
        is refused before its fields are looked at), the payload and args shapes
        are checked, the receiver is required, and only then is the strict codec
        run over the declared wire field.
        """
        endpoint = _endpoint(method)
        if method not in METHOD_NAMES:
            raise TypertGatewayError("invocation-unavailable", endpoint, UNEXPORTED_ERROR)
        request = endpoint_request(method, payload)
        service = self._service()
        if service is None:
            raise TypertGatewayError("invocation-unavailable", endpoint, UNEXPORTED_ERROR)
        decoded = validate_wire_request(method, request)
        if hasattr(service, "ensure_initialized"):
            await service.ensure_initialized()
        operation: Callable[[Dict[str, Any]], Any] = getattr(service, method)
        return await operation(decoded)

    async def list(self, payload: Any) -> Dict[str, Any]:
        return await self.invoke("list", payload)

    async def put(self, payload: Any) -> Dict[str, Any]:
        return await self.invoke("put", payload)

    async def delete(self, payload: Any) -> Dict[str, Any]:
        return await self.invoke("delete", payload)


__all__ = [
    "BOUNDARY_ERROR",
    "METHOD_NAMES",
    "NAMESPACE",
    "PAYLOAD_ERROR",
    "MessageFeedbackDomainHandler",
    "TypertGatewayError",
    "UNEXPORTED_ERROR",
    "WIRE_FIELDS",
    "endpoint_request",
    "validate_wire_request",
]
