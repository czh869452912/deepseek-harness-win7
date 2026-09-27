# Shared cold Session preparation

Pinned upstream: cd5ef8148158c3a752a658978873241fdf8e2bbc.

The previous SessionPersistence.prepare called load and constructed a fresh Session for every caller. Concurrent preparation did not reserve IDs, failed setup discarded exact identity, and cached reads had no invalidation/revision coordination. This closure ports the upstream pool phases (loading, ready, committing, reserved), LRU/pinned leases, observer cancellation and exact reservation operations, then integrates both backends.

The shared coordinator compares revisions around reads and before commit, rereads after durable repair, preserves an untouched unpublished Session on release and discards a mutated one. Session/end-seed is part of the restored Session length, so it must not itself count as setup mutation. The live writer consumes exact reservations before adoption, preserving publication identity and persisting unpublished suffixes.

Public writes now snapshot JSON, wait on per-ID storage locks, reject nonempty writes/create against reserved identities, and invalidate cached reads after success. Public load waits for an existing reservation. Empty append remains a no-op. JSONL/SQLite use internal repair append methods so a reservation does not reject its own durable repair. Teardown invalidates reservations and drains loader/commit jobs before closing storage; waiting observers fail instead of hanging or using a closed connection.

Python adaptations: exception abort reasons remain exact; non-exception reasons are carried on RuntimeError.reason. Observer Task cancellation never cancels shared work. JSONL content hashes and SQLite metadata/event hashes detect changed content; these are not upstream stat token formats. Inspection returns detached copies; a Session is instantiated when prepare is first requested, so full inspect-time schema-validation parity remains unclaimed. Async Python coroutine admission is not a claim of identical JS microtask timing.

Validation includes 197 unchanged upstream Session assertions, source-derived pool tests, both-backend integration tests, and five real JSONL paired scenarios: reuse, mutated release, reserved write, cancelled waiter, revision refresh. Paired observations compare identity outcomes, event type sequences and rejection/cancellation, not generated timestamps or diagnostic wording. Existing cold/live/Agent gates remain required.

Remaining boundaries: fully lazy public create, complete public append cursor/schema validation and adoption, full read-side schema/vocabulary validation, cross-process atomic materialization, comprehensive SQLite upstream baseline, configured Agent startup/reload and complete Session projection/Web. They are tracked separately; this change does not certify entire Session or Harness parity.
