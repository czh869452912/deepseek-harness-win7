# Shared preparation closure

Candidate: `78f35dc2`; pinned upstream: `cd5ef8148158c3a752a658978873241fdf8e2bbc`.

## Changes

- `5414efe9`: shared preparation pool, five-entry default LRU, pinned leases, exclusive reservation/attach/release, exact abort reasons, invalidation and Python observer cancellation isolation.
- `78f35dc2`: JSONL/SQLite integration, content revision checks, repair/reread, exact restored Session reuse and mutation discard, public nonempty-write reservation guards, JSON snapshots, storage locks and unload draining. The live writer consumes the exact reservation and persists unpublished suffixes.

Prior candidate `3de19a21` was exercised with the same Python observation script against its real checkout. It returned a different Session on reuse, allowed a reserved write (physical length 3 instead of 2), and did not honor the cancelled waiter. The unmodified raw observation is retained as before-python evidence. The final paired runner requires all five scenarios and fails closed on runner/missing-case errors.

## Final result

Final clean-checkout release gate passed: **3175 passed, 2 skipped, 2 warnings**, 323.21 seconds. Existing Windows Proactor cleanup warnings and mock socket disconnect diagnostics remain visible. C58 was accepted only through the prior exact signature gate.

All 5 preparation, 4 live, 7 cold and 9 Agent paired observations passed. Portable contains 349 byte-identical Python files, five own-Python profile checks and isolated profile boot pass. ZIP SHA256: `4c698e38447dd97e14fc40afcd9c1e97e063cd5745c53797bf822546cdd7fc50`.

## Scope of evidence

197 unchanged upstream Session tests establish source behavior; they are not a claim of 197 Python matches. Local pool and both-backend integration tests cover observer cancellation, pins/LRU, exclusive ownership, invalidated/failed commit, mutation release, queued repair cancellation, storage snapshots, publication suffix and unload. Five real JSONL paired observations compare identity outcomes, event type sequences, cancellation/rejection and physical lengths. They do not compare generated timestamps or diagnostic wording. Prior Agent, cold recovery and live lifecycle gates also run at this candidate.

The final clean-checkout release gate, package identity and exact artifact hashes are recorded in RUN-SESSION-PREPARED evidence. Existing pinned development dependencies are reused; no new empty-cache installation claim. Win7 remains deferred. The package is in the managed release-repro worktree, not the main checkout dist.

## Remaining boundaries

Public lazy create, full append cursor/schema validation/adoption and complete read-side event vocabulary validation remain open. Inspection caches detached views and constructs Session on prepare; this does not claim upstream inspect-time validation equivalence. Content revision hashes are a Python adaptation, not upstream revision token formatting. Cross-process atomic materialization and native SQLite upstream verification are not certified.

Next: finish that public storage boundary, then configured Agent sessionId/resumeSessionId and launcher identity startup, restore-or-create, draining/reload, followed by full Session projection and Web consumers. MIG-SESSION-REPLAY-002 remains draft; no whole-Harness accepted_upstream is asserted.
