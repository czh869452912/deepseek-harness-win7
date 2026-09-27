# Public Session storage closure

Candidate: `8201d7dc23251387bd9094539d81b856f12f4bfd`; pinned upstream: `cd5ef8148158c3a752a658978873241fdf8e2bbc`.

## Changes and observed baseline

- `0ca41c6a`: shared public persistence cursor, lazy detached creation, whole-batch contiguity, cold source adoption, inspect-time Session validation, retired/unknown vocabulary guards, serialized cancellable physical reads and explicit empty live-session materialization. JSONL and SQLite use the same coordinator; live ownership and preparation consumers were changed together.
- `8201d7dc`: remove the replaced JSONL overwrite publisher. The old unused queue facade was replaced in the first commit, including its stale test consumer.
- Candidate `78f35dc2` was actually rerun before switching the release checkout: creation already appeared in list, duplicate create was allowed and a seq-2 first append was allowed. The raw before observation is retained.
- First JSONL header and batch publish together through exclusive write-through `MoveFileExW` on Windows; missing directories also use durable publication. The API is available on Win7, but this is not Win7 hardware certification. SQLite commits header and events together with INSERT, without replacing prior rows.

## Verification

The exact clean candidate passed the full Python suite: **3200 passed, 2 skipped, 2 warnings**, 193.00 seconds. Existing Windows Proactor cleanup warnings and mock socket disconnect diagnostics remain visible. The final clean-checkout release gate passed, including isolated package boot. All 8 storage, 5 preparation, 4 live, 7 cold and 9 Agent paired observations matched. Unmodified upstream suites passed: Cordis 80, Agent 100, Session 197. Cordis C1-C67 retained 66 matches plus only the previously approved exact C58 Python-native signature. Existing pinned development dependencies were reused; this is not a new empty-cache installation claim.

The added local contract has 25 cases, including both backends, first-write faults and competing backend objects. Eight real JSONL upstream/Python observations compare lazy creation/detachment, duplicate identity, contiguous sequence, retired vocabulary, unknown read refusal, cold cursor adoption, explicit empty materialization and invalid inspect/load envelopes. Their runner requires the exact case set and fails closed on runner errors. Previous preparation/live/cold/Agent paired gates remain part of the release gate.

Upstream Session tests are source baselines, not an assertion-for-assertion Python parity certificate. Diagnostics and generated timestamps are not compared in the new observations. Python async snapshotting happens when the coroutine starts, before it awaits the per-ID lock.

## Remaining boundaries and next dependency

`CON-SESSION-STORAGE@1` is bounded to the stated scenarios. It does not certify arbitrary cross-process/multi-cwd concurrency, power-loss behavior, compressed JSONL, native upstream SQLite execution, complete historical-event migration or all Session projections. Win7 machine/browser verification remains deferred by the user.

Next implement configured Agent startup/reload using `reference/packages/core/agent-loop/tests/config-session-id.spec.ts` and its 14 source cases. The current Python `AgentLoopPlugin.apply` only installs services/factory and teardown; it does not consume the configured agents list. Required order:

1. Validate configured IDs and mutually exclusive sessionId/resumeSessionId before publishing; apply launcher identities by configured entry ID.
2. Mount exact/fresh/resume startup under owned effects. Existing exact IDs restore, missing exact IDs create, and explicit missing resumes report contained failures.
3. Wait for the prior exact lifecycle to drain on reload; cancellation/disposal must suppress late publication and failure reports.
4. Prove real persisted-history continuation across AgentLoop-only reload before proceeding to full Session projection and Web replay consumers.

This next transaction depends on the public Agent factory and shared Session cold/live/preparation/storage contracts. Provider and consumer files stay in one change when an interface changes; expected_paths remains advisory. Do not mark the entire Harness accepted from this storage closure.

Portable own-Python checks for minimal/standard/creative/web/headless passed; 350 Python source files are byte-identical to the candidate. ZIP SHA256: `c540d85e912005ee5e95c656bb0b54dedcde62fc0ba59af90a71af503f14aeda`. Package location: `C:/Users/Administrator/.codex/worktrees/release-repro/deepseek-harness-win7/dist/dsh-win7-portable-v0.1.0.zip`; the main checkout dist is not the latest package.
