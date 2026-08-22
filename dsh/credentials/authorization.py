"""
Authorization Capability Seam Service (`ctx.authorization`).
1:1 with reference @deepseek-ai/dsh-authorization.
Python 3.8.10 compatible.
"""

from typing import Any, Callable, Dict, List, Optional, Union

from dsh.cordis.service import Service
from dsh.credentials.credentials import parse_credential_key
from dsh.credentials.types import (
    AuthorizationEntry,
    AuthorizationMethod,
    AuthorizationNotice,
    AuthorizationOutcome,
    AuthorizationPrompt,
)
from dsh.llm.error import HarnessError


class AuthorizationError(HarnessError):
    """Stable error taxonomy for authorization failures."""

    def __init__(self, message: str, code: str = "AUTHORIZATION_ERROR"):
        super().__init__(message, code)
        self.name = "AuthorizationError"


class AuthorizationDeclinedError(AuthorizationError):
    """Rejection used when human declines an authorization prompt."""

    def __init__(self, message: str = "the authorization prompt was declined"):
        super().__init__(message, "DECLINED")
        self.name = "AuthorizationDeclinedError"


class AuthorizationSession:
    """Session interface scoped to one authorization attempt."""

    def __init__(self, method: str, interaction: Any, observed: Dict[str, bool]):
        self.method = method
        self._interaction = interaction
        self._observed = observed

    def notify(self, notice: AuthorizationNotice) -> None:
        """Report progress or instructions fire-and-forget."""
        try:
            if hasattr(self._interaction, "notify") and callable(self._interaction.notify):
                self._interaction.notify(notice)
            elif isinstance(self._interaction, dict) and callable(self._interaction.get("notify")):
                self._interaction["notify"](notice)
        except Exception:
            pass

    def prompt(self, prompt_data: AuthorizationPrompt) -> str:
        """Ask human a question."""
        try:
            if hasattr(self._interaction, "prompt") and callable(self._interaction.prompt):
                return self._interaction.prompt(prompt_data)
            elif isinstance(self._interaction, dict) and callable(self._interaction.get("prompt")):
                return self._interaction["prompt"](prompt_data)
            else:
                raise AuthorizationDeclinedError("no prompt handler available on interaction surface")
        except AuthorizationDeclinedError as e:
            self._observed["declined"] = True
            raise e
        except Exception as e:
            raise e


class AuthorizationFlow:
    """Plugin knowledge of how to obtain one credential."""

    def __init__(
        self,
        key: str,
        label: str,
        methods: List[AuthorizationMethod],
        run_fn: Callable[[AuthorizationSession], None],
    ):
        parse_credential_key(key)
        if not methods or len(methods) == 0:
            raise ValueError("AuthorizationFlow methods list cannot be empty")
        self.key = key
        self.label = label
        self.methods = methods
        self.run_fn = run_fn

    def run(self, session: AuthorizationSession) -> None:
        self.run_fn(session)


class AuthorizationService(Service):
    """
    Authorization Service registered at `ctx.authorization`.
    1:1 with reference @deepseek-ai/dsh-authorization AuthorizationService.
    """

    name = "authorization"
    inject = ["credentials"]

    def __init__(self, ctx: Optional[Any] = None):
        super().__init__(ctx, "authorization")
        self._flows: Dict[str, AuthorizationFlow] = {}
        self._running: Dict[str, Any] = {}

    def register_flow(self, flow: Any) -> Callable[[], None]:
        """Offer a way to obtain one credential record."""
        key = getattr(flow, "key", None) or (flow.get("key") if isinstance(flow, dict) else None)
        if not key:
            raise ValueError("AuthorizationFlow must specify a key")
        parse_credential_key(key)

        if key in self._flows:
            raise AuthorizationError(f'an authorization flow for "{key}" is already registered', "DUPLICATE_FLOW")

        if isinstance(flow, dict):
            flow_obj = AuthorizationFlow(
                key=flow["key"],
                label=flow["label"],
                methods=flow["methods"],
                run_fn=flow["run"],
            )
        else:
            flow_obj = flow

        self._flows[key] = flow_obj

        def dispose() -> None:
            if key in self._flows:
                del self._flows[key]
            if key in self._running:
                ctrl = self._running[key]
                if hasattr(ctrl, "cancel"):
                    ctrl.cancel()

        ctx = getattr(self, "ctx", None)
        if ctx and hasattr(ctx, "effect"):
            return ctx.effect(lambda: dispose, "authorization.registerFlow()")
        return dispose

    def registerFlow(self, flow: Any) -> Callable[[], None]:
        return self.register_flow(flow)

    def list(self) -> List[AuthorizationEntry]:
        """List every registered flow for surface listing."""
        return [self._entry(flow) for flow in self._flows.values()]

    def describe(self, key: str) -> Optional[AuthorizationEntry]:
        """Describe one registered flow."""
        flow = self._flows.get(key)
        return self._entry(flow) if flow else None

    def _entry(self, flow: AuthorizationFlow) -> AuthorizationEntry:
        return {
            "key": flow.key,
            "label": flow.label,
            "methods": flow.methods,
            "inFlight": flow.key in self._running,
        }

    def cancel(self, key: str) -> None:
        """Withdraw attempt running for key."""
        ctrl = self._running.get(key)
        if ctrl and hasattr(ctrl, "cancel"):
            ctrl.cancel()

    def begin(self, request: Dict[str, Any]) -> AuthorizationOutcome:
        """Run one attempt to authorize a key and report status."""
        key = request.get("key")
        if not key or key not in self._flows:
            raise AuthorizationError(f'no authorization flow is registered for "{key}"', "NO_FLOW")

        flow = self._flows[key]
        method = request.get("method") or flow.methods[0]["id"]

        if not any(m.get("id") == method for m in flow.methods):
            raise AuthorizationError(
                f'authorization flow for "{key}" offers no method "{method}"', "UNKNOWN_METHOD"
            )

        if key in self._running:
            raise AuthorizationError(
                f'an authorization attempt for "{key}" is already running', "ALREADY_IN_FLIGHT"
            )

        signal = request.get("signal")
        if signal and getattr(signal, "aborted", False):
            return {"status": "cancelled"}

        self._running[key] = signal or True
        observed = {"declined": False, "committed": False}
        settlement = "failed"

        unwatch = None
        ctx = getattr(self, "ctx", None)

        def on_record_updated(updated_key: str) -> None:
            if updated_key == key:
                observed["committed"] = True

        if ctx and hasattr(ctx, "on"):
            unwatch = ctx.on("credentials/record-updated", on_record_updated)

        try:
            interaction = request.get("interaction")
            session = AuthorizationSession(method, interaction, observed)

            try:
                flow.run(session)
            except AuthorizationDeclinedError:
                settlement = "cancelled"
                return {"status": "cancelled"}
            except Exception as e:
                if (signal and getattr(signal, "aborted", False)) or observed["declined"]:
                    settlement = "cancelled"
                    return {"status": "cancelled"}
                raise e

            if signal and getattr(signal, "aborted", False):
                settlement = "cancelled"
                return {"status": "cancelled"}

            if not observed["committed"]:
                raise AuthorizationError(
                    f'authorization flow for "{key}" resolved without committing a credential record in this attempt',
                    "NOT_COMMITTED",
                )

            if ctx and hasattr(ctx, "credentials"):
                stored = ctx.credentials.describe_record(key)
                if not stored.get("configured"):
                    raise AuthorizationError(
                        f'authorization flow for "{key}" deleted its credential record instead of committing one',
                        "NOT_COMMITTED",
                    )

            settlement = "authorized"
            return {"status": "authorized"}

        finally:
            if unwatch and callable(unwatch):
                try:
                    unwatch()
                except Exception:
                    pass
            self._running.pop(key, None)
            self._settle(key, settlement)

    def _settle(self, key: str, settlement: str) -> None:
        """Fan authorization/settled out with contained listener failures."""
        invariant_failure: Optional[Exception] = None
        ctx = getattr(self, "ctx", None)
        if ctx is None:
            return

        listeners = []
        if hasattr(ctx, "events") and hasattr(ctx.events, "_dispatch_hooks"):
            listeners = ctx.events._dispatch_hooks("emit", "authorization/settled", ctx)

        for listener in listeners:
            try:
                listener(key, settlement)
            except Exception as error:
                if getattr(error, "code", None) == "INVARIANT":
                    if invariant_failure is None:
                        invariant_failure = error
                    continue
                self._warn_settled_listener_failure(key, error)

        if not listeners and hasattr(ctx, "emit"):
            try:
                ctx.emit("authorization/settled", key, settlement)
            except Exception as error:
                if getattr(error, "code", None) == "INVARIANT":
                    if invariant_failure is None:
                        invariant_failure = error

        if invariant_failure is not None:
            raise invariant_failure

    def _warn_settled_listener_failure(self, key: str, error: Exception) -> None:
        ctx = getattr(self, "ctx", None)
        logger = getattr(ctx, "logger", None) if ctx else None
        if logger:
            try:
                logger.warn('authorization: an authorization/settled listener for "%s" failed', key)
                logger.warn(str(error))
            except Exception:
                pass
