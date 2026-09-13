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
