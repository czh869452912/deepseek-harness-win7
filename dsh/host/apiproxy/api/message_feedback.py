"""
Message Feedback Domain Handler (`@deepseek-ai/dsh-apiproxy/api/message-feedback`).

The shipped Web Host serves the `messageFeedback` Remote namespace over
`/api/messageFeedback/{list,put,delete}`. The reference exposes it through the
Typert Remote gateway (`reference/packages/api/gateway/src/index.ts`), which
decodes each declared wire field before the business method runs:

  - a field that fails its declared boundary schema throws a
    `TypertGatewayError('input-invalid', endpoint, 'wire field "request" failed
    boundary validation')`, and
  - the gateway maps any non-business error onto
    `{ ok: false, error: { code: 'internal', message, details: {} } }`
    (`rpcFailure`), while the business result itself travels inside the
    successful server-response value.

This handler reproduces that boundary for the three messageFeedback endpoints:
the `request` argument is validated against the declared request shape before
the service is touched, so an invalid rating is rejected before any write.
"""

from typing import Any, Callable, Dict, Tuple

NAMESPACE = "messageFeedback"

#: The exact Gateway namespace method names, in the reference's declaration order.
METHOD_NAMES: Tuple[str, ...] = ("list", "put", "delete")

RATINGS = ("positive", "negative")


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
    return isinstance(value, dict)


def endpoint_request(method: str, payload: Any) -> Any:
    """
    Extract the strict `args.request` wire field, exactly like the gateway's
    `assertExactArguments` + `decode` pair.
    """
    endpoint = _endpoint(method)
    if not _is_plain_object(payload):
        raise TypertGatewayError("arguments-invalid", endpoint, "args must be a plain object")
    args = payload.get("args", None)
    if not _is_plain_object(args):
        raise TypertGatewayError("arguments-invalid", endpoint, "args must be a plain object")
    if "request" not in args:
        raise TypertGatewayError(
            "arguments-invalid",
            endpoint,
            'args fields do not match the descriptor: missing "request"',
        )
    return args["request"]


def _require_string(endpoint: str, request: Any, field: str) -> str:
    value = request.get(field, None)
    if not isinstance(value, str) or len(value) == 0:
        raise TypertGatewayError(
            "input-invalid", endpoint, 'wire field "request" failed boundary validation'
        )
    return value


def validate_wire_request(method: str, request: Any) -> Dict[str, Any]:
    """
    Validate one decoded `request` value against the declared request shape.

    The codec is a zod object, so unknown fields are dropped rather than
    rejected; a field that is present but does not match its declared type
    fails the boundary.
    """
    endpoint = _endpoint(method)
    if not _is_plain_object(request):
        raise TypertGatewayError(
            "input-invalid", endpoint, 'wire field "request" failed boundary validation'
        )
    decoded: Dict[str, Any] = {"sessionId": _require_string(endpoint, request, "sessionId")}
    if method == "list":
        return decoded

    decoded["messageId"] = _require_string(endpoint, request, "messageId")
    if method == "delete":
        ifVersion = request.get("ifVersion", None)
        if not isinstance(ifVersion, str) or len(ifVersion) == 0:
            raise TypertGatewayError(
                "input-invalid", endpoint, 'wire field "request" failed boundary validation'
            )
        decoded["ifVersion"] = ifVersion
        return decoded

    rating = request.get("rating", None)
    if rating not in RATINGS:
        raise TypertGatewayError(
            "input-invalid", endpoint, 'wire field "request" failed boundary validation'
        )
    decoded["rating"] = rating
    note = request.get("note", None)
    if note is not None:
        if not isinstance(note, str):
            raise TypertGatewayError(
                "input-invalid", endpoint, 'wire field "request" failed boundary validation'
            )
        decoded["note"] = note
    ifVersion = request.get("ifVersion", None)
    if ifVersion is not None:
        if not isinstance(ifVersion, str) or len(ifVersion) == 0:
            raise TypertGatewayError(
                "input-invalid", endpoint, 'wire field "request" failed boundary validation'
            )
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
        """Decode one wire invocation and return the business result."""
        request = validate_wire_request(method, endpoint_request(method, payload))
        service = self._service()
        if service is None:
            raise TypertGatewayError(
                "invocation-unavailable",
                _endpoint(method),
                "no active Remote method exports this endpoint",
            )
        if hasattr(service, "ensure_initialized"):
            await service.ensure_initialized()
        operation: Callable[[Dict[str, Any]], Any] = getattr(service, method)
        return await operation(request)

    async def list(self, payload: Any) -> Dict[str, Any]:
        return await self.invoke("list", payload)

    async def put(self, payload: Any) -> Dict[str, Any]:
        return await self.invoke("put", payload)

    async def delete(self, payload: Any) -> Dict[str, Any]:
        return await self.invoke("delete", payload)


__all__ = [
    "METHOD_NAMES",
    "NAMESPACE",
    "MessageFeedbackDomainHandler",
    "TypertGatewayError",
    "endpoint_request",
    "validate_wire_request",
]
