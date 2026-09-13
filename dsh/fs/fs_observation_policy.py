"""
Event-only filesystem observation policy.

1:1 with reference/packages/fs/fs-observation-policy: this plugin registers no
service. A weak owner/target map records every authoritative presence/absence
observation, the single-slot intent listeners derive guards from that state, and
the provider performs the atomic freshness/no-clobber check. Without this
plugin, tools retain the bare provider's unconditional mutation behavior.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import weakref
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.fs.fs_local import FsError, FsTarget

__all__ = ["ObservedStateGate", "FsObservationPolicyPlugin"]

#: The reference's `delete-on-dispose` owner map is a `WeakMap<object, Map<...>>`;
#: the port carries the same two levels on `weakref.WeakKeyDictionary` plus a
#: plain per-owner mapping.
OWNER_FIELD = "agent"
SESSION_FIELD = "session"


class ObservedStateGate:
    """
    Per-context observed-file state and the three `fs/*` decisions over it.

    One instance is created per `apply()` so disposal can drop all state for HMR.
    Observed-file state is keyed first by the owner object (weakly held, so a
    collected session frees its state), then by `FsTarget.targetKey`. An entry's
    presence is the prior-observation record; its discriminant keeps confirmed
    absence distinct from an unseen target.
    """

    def __init__(self) -> None:
        self._observed = weakref.WeakKeyDictionary()

    def owner(self, actor: Any) -> Optional[Any]:
        """
        Derive the observed-state owner from the opaque event actor - normally
        the active agent session.

        None when no owner can be derived (e.g. a direct tool call with no
        agent); such calls read freely but cannot satisfy the write/edit
        prior-observation policy.
        """
        if actor is None:
            return None
        agent = getattr(actor, OWNER_FIELD, None)
        if agent is None:
            return None
        return getattr(agent, SESSION_FIELD, None)

    def _get(self, owner: Any, target_key: str) -> Optional[Dict[str, Any]]:
        by_target = self._observed.get(owner)
        if by_target is None:
            return None
        return by_target.get(target_key)

    def _set(self, owner: Any, target_key: str, observation: Dict[str, Any]) -> None:
        by_target = self._observed.get(owner)
        if by_target is None:
            by_target = {}
            self._observed[owner] = by_target
        by_target[target_key] = observation

    def clear(self) -> None:
        """Drop all recorded state (HMR safety / disposal)."""
        self._observed = weakref.WeakKeyDictionary()

    def write_intent(self, target: FsTarget, actor: Any) -> Dict[str, Any]:
        """
        Decide the write intent: unseen or confirmed absent -> `createIfAbsent`;
        confirmed present -> `replaceIfVersion` at the observed version.
        """
        owner = self.owner(actor)
        prior = self._get(owner, target.targetKey) if owner is not None else None
        if prior is not None and prior.get("kind") == "present":
            return {"kind": "replaceIfVersion", "version": prior.get("version")}
        return {"kind": "createIfAbsent"}

    def edit_intent(self, target: FsTarget, actor: Any) -> Dict[str, Any]:
        """
        Decide the edit version guard: unseen rejects with `FS_NOT_OBSERVED`,
        confirmed absence rejects with `FS_NOT_FOUND`, and presence supplies the
        observed version as the CAS basis.
        """
        owner = self.owner(actor)
        prior = self._get(owner, target.targetKey) if owner is not None else None
        if owner is None or prior is None:
            raise FsError(
                'edit requires reading "{}" first'.format(target.displayPath),
                "FS_NOT_OBSERVED",
            )
        if prior.get("kind") == "absent":
            raise FsError(
                'cannot edit "{}": not found'.format(target.displayPath),
                "FS_NOT_FOUND",
            )
        return {"version": prior.get("version")}

    def observe(self, target: FsTarget, observation: Dict[str, Any], actor: Any) -> None:
        """Record an authoritative present or absent observation for this owner."""
        owner = self.owner(actor)
        if owner is not None:
            self._set(owner, target.targetKey, observation)


class FsObservationPolicyPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-fs-observation-policy`.

    Registers the three `fs/*` listeners. No `inject` - this plugin reads no
    services; it operates only on its own owner map. The waterfalls are unbound
    (the tool dispatches them with no `this`), so the listeners take the raw
    `(target, actor)` arguments.
    """

    id = "fs-observation-policy"
    name = "@deepseek-ai/dsh-fs-observation-policy"
    inject = []

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def apply(self, ctx: Any) -> None:
        gate = ObservedStateGate()

        # Drop all recorded state on disposal so a reloaded plugin starts clean
        # (HMR safety). The weak map itself would be collected, but replacing it
        # makes the release observable and immediate for tests.
        ctx.disposable(gate.clear, label="fs-observation-policy observed-state teardown")

        # fs/write-intent: occupy the single decision slot - do NOT call next().
        # The decision is deferred through a coroutine so a throw rejects through
        # the waterfall instead of escaping synchronously.
        async def on_write_intent(target: FsTarget, actor: Any = None) -> Dict[str, Any]:
            return gate.write_intent(target, actor)

        # fs/edit-intent: occupy the single decision slot - do not call next().
        async def on_edit_intent(target: FsTarget, actor: Any = None) -> Dict[str, Any]:
            return gate.edit_intent(target, actor)

        # fs/observed must remain synchronous and non-throwing: emit does not
        # await promises, and successful mutations have already committed.
        def on_observed(target: FsTarget, observation: Dict[str, Any], actor: Any = None) -> None:
            gate.observe(target, observation, actor)

        ctx.on("fs/write-intent", on_write_intent)
        ctx.on("fs/edit-intent", on_edit_intent)
        ctx.on("fs/observed", on_observed)
