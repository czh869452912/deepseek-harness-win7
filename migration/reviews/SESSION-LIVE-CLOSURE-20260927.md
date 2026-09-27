# Shared Session live writes acceptance

Candidate: `3de19a21` (full SHA recorded in evidence). Upstream remains `cd5ef8148158c3a752a658978873241fdf8e2bbc`.

## Implementation

- `76d9084a`: independent SessionWriteBehind controller. Fixed batching window, owned copies, shared flush barrier, active-tail deadlines, retained failed batches and paused automatic retry.
- `71eea41b`: shared JSONL/SQLite live coordinator, exact Session ownership, per-ID serialization, seed/adoption, retirement, ordered drain/close, observer cancellation isolation, storage append rollback. Both backends now use the same live write path.
- `3de19a21`: Python retirement/unload scheduling fix. Capture exact drain state before scheduling children so an already-retired Session is never reinitialized during shutdown.

The earlier failure evidence (pending 2 -> 0 after failed append; no artifact after unload) is retained alongside this run. Storage fault injection now covers JSONL fsync rollback and SQLite failed-batch transaction rollback, preventing duplicate or partial retries.

## Final result

Clean checkout release gate passed: **3142 passed, 2 skipped, 2 warnings**, 322.81 seconds. The existing Windows Proactor cleanup warnings and mock socket disconnect output remain visible; this is not a zero-warning claim. All paired gates passed and Cordis C58 was accepted only by the existing exact signature.

Portable contains 347 byte-identical Python source files and passes five own-Python profile checks plus isolated boot. ZIP SHA256: `b95174bf1328a7fabf321fc9fbd3315f60a294702fb5cd46476afd151421f0a3`.

## Verification scope

The release gate runs full Python regression, pinned Cordis consumers, Agent suites, 174 Session source assertions, 9 Agent paired scenarios, 7 cold-recovery paired scenarios and 4 live JSONL paired journeys. C58 retains its previously accepted exact Python-native scheduling signature. The four live journeys compare event type/seq/data and conflict rejection, excluding generated timestamps and diagnostic wording; they do not certify every upstream persistence assertion. SQLite shares local lifecycle/rollback probes but has no upstream native SQLite parity claim.

The final clean-checkout result and package hash are recorded in `RUN-SESSION-LIVE-*` and `artifacts/SESSION-LIVE-20260927-*`. Existing pinned development dependencies are reused, not reinstalled from an empty cache. Portable source identity, own-Python five-profile dump-config and isolated boot are verified. Current Windows/Python 3.8 validation does not replace Win7 validation, which the user deferred.

## Remaining work

Shared preparation cache/reservation/observer cancellation and public persistence create/append coordination remain outside this bounded live-write contract. Cross-process materialization and full schema/SQLite upstream verification also remain open. Next, establish that shared preparation and public storage boundary, then migrate configured sessionId/resumeSessionId, launcher identities, restore-or-create and Agent reload/draining, followed by full Session projection/Web consumers.

MIG-SESSION-REPLAY-002 remains draft with explicit findings. No overall accepted_upstream is asserted.
