# Cordis lifecycle ownership and acceptance

The existing `vendor/cordis` task owns Context/Registry/Fiber lifecycle semantics
and all consumer changes necessary to preserve those semantics. This is not a
new migration from scratch. Preserve the sixth-round checkpoint and the earlier
completed cases; verify them against the pinned reference before reuse.

Canonical ownership includes `dsh/cordis`, boot activation boundaries in
`dsh/boot/app_boot.py`, `dsh/harness.py`, `apps/cli/main.py`, HMR reload ordering in
`dsh/cordis/hmr.py`, diagnostics readiness and their tests. Loader, Web and CLI
feature-completeness remain separate tasks, but necessary await/settlement changes
in those consumers belong to this atomic lifecycle change, not a blocked follow-up.

Required observable invariants (use these stable IDs in findings):

1. `fiber.ts#reload-initial-microtask`: `reference/vendor/cordis/src/fiber.ts`
   `_reload` performs its initial Promise checkpoint before activation; LOADING,
   callback order and cancellation before execution must remain observable.
2. `fiber.ts#load-epoch-cancellation`: disposal or dependency changes invalidate
   pending activation. No late plugin execution, duplicate mount or leaked effect.
3. `fiber.ts#effect-settlement`: synchronous iterable, asynchronous iterable and
   awaitable effects preserve failure propagation and reverse-order cleanup;
   parent/child ownership and quiescent disposal match the reference.
4. `registry.ts#activation-settlement`: consumers explicitly wait at boot,
   harness, loader and CLI boundaries rather than assuming synchronous mount.
5. `hmr.ts#serialized-reload`: dependent reload/disposal is ordered, and stale
   callbacks cannot resurrect disposed state. Consult `reference/vendor/hmr` and
   the pinned local modifications before selecting behavior.

Acceptance must include executable event-order assertions for before-checkpoint,
after-checkpoint, early cancellation, dependency restoration, error propagation
and settled shutdown. Map each to an exact upstream function/test. Existing tests
that assume synchronous activation may gain an explicit wait; preserve their
behavior assertions. A broad number of affected tests is not a reason to defer
this core contract or to weaken it. Run targeted lifecycle/consumer tests and the
controller's full suite on the combined candidate. A PASS is bound to its tested
head, source SHA and consumed contract versions, not merely this checklist.

## Runtime repair obligations

Keep the core blocking until its contract and all necessary consumer adaptations
pass together. A core interface/ordering change must enumerate consumer entry
points and tests; directory size is not a reason to defer required adaptation.

6. `events.ts#emit-dispatch-stack-before-promise-continuations`: derive ordering
   from `reference/vendor/cordis/src/events.ts:189-196`. Distinguish listener
   invocation and eager async prefix from later continuation and final settlement.
   Test multiple listeners, exception release and owned shutdown. An inline
   asyncio.run or a free-running background loop is not by itself a parity proof.
7. `hmr.ts#registration-keyed-config-refresh-serialization`: derive identity and
   serialization from `reference/vendor/hmr/src/index.ts:296-323`. Same filename
   does not imply same registration owner. Disposing a module registration must
   not retire a live config registration's refresh state. Test a real change
   while the first callback is still blocked, and then serial dirty replay.

Before editing, state invariant, source, state keys and owners, event partial
order, required consumers and counterexamples. After editing, return these as
contract_checks with exact tests and evidence. Check all related state stores;
repair the smallest complete semantic cause rather than the smallest line count.
Use deterministic gates for ordering; retain the original failure evidence and
prove the regression distinguishes old and new behavior. Mark reused clauses,
unresolved gaps and source-backed N/A dimensions explicitly.
