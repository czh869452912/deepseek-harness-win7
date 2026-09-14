# Cordis lifecycle pilot observations

The September 13 pilot preserves the original sixth-round worktree and combines
its changes in `codex/cordis-lifecycle-pilot`. The pilot runs one acceptance owner;
necessary boot, harness, CLI, HMR and Loader settlement adaptations belong to that
owner. Complete Loader transaction semantics remain with `vendor/loader`.

## Observed causes of repeated work

* A legacy `COMPLETE` migration result failed protocol validation after real work
  completed. Recovery now retains the result as escalation, not a false pass.
* Conflicting optional plans bypassed semantic arbitration. Arbitration now runs
  before graph reconciliation, and plan-only repair retains implementation/review.
* A judge returned `BLOCKED` together with the explicit `BOTH_INCOMPLETE` verdict.
  A decided correction now proceeds by verdict instead of asking for arbitration
  again. A successful ruling can override review only with complete coverage and
  no remaining open findings.
* Completion reports rewrote existing task/contract IDs. Empty repaired plans
  now mean no graph change; consumed proposal signatures prevent replay. Actual
  implementation gaps advance the implementation round after graph repair.
* Windows sharing errors reading a live status file escaped the dashboard and
  stopped workers. Display reads/writes are now best-effort; SQLite remains the
  execution authority.
* A judge assigned a Loader defect to its independent owner in prose but put both
  tasks in one atomic group in JSON. The graph was corrected, and pilot claims
  now reject groups that expand beyond their initial membership.
* A clean pause accidentally entered publication preparation. Publication now
  requires the selected pilot task to be INTEGRATED, in addition to the existing
  tested-head and clean-input checks.
* Scoring each candidate with a different clock reading caused unstable ordering
  among equal-priority tasks. One claim now uses one timestamp.

## Implementation and review observations

Real defects remained after the earlier orchestration changes: effect wrappers
were retired before async cleanup settled; startup failure emitted an extra
FAILED transition; Loader outer tasks lacked ownership; boot could return with
root disposal still pending. Further review identified concurrent root disposal
overwriting unload inertia and a missing HMR Service.init teardown effect.

Review was useful but not infallible. One reviewer inverted upstream startup
failure cleanup; source-based arbitration corrected it. Another assigned an
existing Loader transaction defect to core; before/after probes and the existing
task contract resolved its ownership. The migration model overextended a legal
Python adaptation to justify an unowned consumer task, then introduced a circular
HMR/root teardown wait. The coordinator fixed that wait and the final two narrow
review findings, with explicit provenance and independent review still required.

These are not grounds for attributing all delay to one model. The run used the
configured migrator, reviewer and judge throughout; it was not a controlled model
comparison. Both orchestration defects and inaccurate semantic reasoning were
observed directly.

## Remaining low-cost improvements

1. Implemented: interrupted native Goose sessions resume with an explicit
   handoff and the full output schema, guarded by saved workspace and model
   identity. Round 11 reused its review context and repaired serialization
   without rerunning implementation.
2. Expose controller-owned test summaries with exit code, warnings, tested head
   and artifact path. The migration model reran full tests merely because a
   terminal tail omitted the pytest summary behind transport diagnostics.
3. Separate analysis time, tool time, tests, protocol recovery, graph repair and
   implementation rounds on the existing lightweight console. A long phase is
   not necessarily another migration iteration.
4. Keep source-backed acceptance clauses and resolved ownership decisions stable
   across rounds. Retain prior evidence and require corrections to name affected
   clauses. Full lifecycle acceptance must still be checked before publication.
5. Use short bounded concurrency probes with gated cleanup to diagnose hangs;
   do not repeat a long test without learning which task waits on which owner.
6. Keep local release artifacts distinct from source verification. The main
   checkout's old ignored portable directory fails its existing smoke test;
   isolated candidates skip that test when no portable artifact has been built.
   This pilot does not claim a rebuilt portable release.

The local run database and raw phase streams contain detailed evidence. The
checked-in plans preserve the architecture and scope decisions without requiring
those machine-local artifacts. No external model proxy or additional workspace
management layer is needed for these follow-ups.


## Published result

The round 11 independent review passed. The controller combined and tested the
integration and master candidates and published `dc0e0a19` on 2026-09-14. The
publication suite reported 1813 passed, 1 skipped, 1 warning. Cordis is INTEGRATED;
the pilot and publication are PUBLISHED; the scheduler remains PAUSED. There was
no textual merge conflict in this final candidate, so the integration-repair lane
has regression coverage but was not exercised by a real conflict in this pilot.
