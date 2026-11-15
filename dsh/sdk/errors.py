"""Errors shared by the SDK process client and its external-agent consumer."""
from dsh.sdk.transport import JsonRpcResponseError


class TransportClosedError(RuntimeError):
    pass


class RequestTimeoutError(RuntimeError):
    pass


class SdkProtocolError(RuntimeError):
    pass
