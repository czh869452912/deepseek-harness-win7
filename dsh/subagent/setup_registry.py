"""Owned child setup grants with immediate revocation and publication fencing."""
from types import SimpleNamespace

from dsh.subagent.errors import SubagentError


class SetupRegistry:
    def __init__(self):
        self.registrations = []
        self.children = {}

    def register(self, contribution):
        registration = {"contribution": contribution, "removed": False, "installations": []}
        self.registrations.append(registration)
        def dispose():
            if registration["removed"]:
                return
            registration["removed"] = True
            self.registrations.remove(registration)
            self.release_all(list(registration["installations"]), "contribution removal")
        return dispose

    def apply(self, child_ctx):
        transaction = {"installations": [], "invalidated": False}
        try:
            for registration in list(self.registrations):
                if registration["removed"]:
                    continue
                disposer = registration["contribution"](child_ctx)
                if not callable(disposer):
                    raise TypeError("continuable setup must synchronously return a disposer")
                installation = {"registration": registration, "child": child_ctx, "dispose": disposer,
                                "released": False, "transaction": transaction}
                registration["installations"].append(installation)
                transaction["installations"].append(installation)
                self.children.setdefault(child_ctx, []).append(installation)
                if registration["removed"]:
                    self.release(installation)
        except Exception:
            try:
                self.release_all(list(transaction["installations"]), "setup rollback")
            except Exception:
                pass
            raise
        child_ctx.effect(lambda: lambda: self.release_all(list(self.children.get(child_ctx, [])), "child scope disposal"),
                         "subagents.activationSetup()")
        def commit():
            if transaction["invalidated"]:
                raise SubagentError("a continuable-subagent setup contribution was revoked while this child was being built; the child was not established", "ACTIVATION_SETUP_REVOKED")
            for installation in transaction["installations"]:
                installation["transaction"] = None
        return SimpleNamespace(commit=commit)

    def release(self, installation):
        if installation["released"]:
            return
        installation["released"] = True
        registration = installation["registration"]
        registration["installations"].remove(installation)
        children = self.children.get(installation["child"])
        if children is not None:
            children.remove(installation)
            if not children:
                self.children.pop(installation["child"], None)
        if installation["transaction"] is not None:
            installation["transaction"]["invalidated"] = True
        installation["dispose"]()

    def release_all(self, installations, during):
        failures = []
        for installation in installations:
            try:
                self.release(installation)
            except Exception as error:
                failures.append(error)
        if failures:
            raise SubagentError("continuable-subagent setup {} failed to release {} installation(s): {}".format(
                during, len(failures), "; ".join(str(error) for error in failures)), "ACTIVATION_SETUP_RELEASE_FAILED")
