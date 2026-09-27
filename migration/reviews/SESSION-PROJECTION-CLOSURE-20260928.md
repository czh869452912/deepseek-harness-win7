# Session projection registry closure

Pinned source: `cd5ef8148158c3a752a658978873241fdf8e2bbc`.
Product candidate: `7720cf03` (includes live-drive commit `28a2514e`).

## Scope and changes

`CON-SESSION-PROJECTION@1` is the registry contract, not all Session projection consumers.

- Late registrations replay the prefix before the current event. Observed events are skipped, including events already materialized by a read.
- Cells use weak exact Session identities, so recreated IDs neither inherit stale state nor retain dead sessions.
- Same-version registrations share the first definition and count owners. Cordis Service rebinding puts cleanup on the calling fiber; a stale disposer cannot remove another owner.
- Canonical definitions accept metadata in `init(header)`, distinguish host-only state from wire views, and run executable state/view parsers. Selected snapshot views still materialize every unit; cached reads never replay.
- Checkpoints clone state. Restoration anchors reads below the lowest watermark, rejects unusable tail seeds and sequence gaps, and refolds invalidated versions from the complete log.
- Hydration attaches the restored cut to the exact prepared Session, reuses identical cuts, never rewinds a newer cell, and advances later suffixes once.

The old keyword registration adapter and `projection/change` bridge remain explicit compatibility surfaces for current domains/Web. Their continued operation is tested; it is not certification of domain schemas, folds or Web transport.

## Verification

- Running the old `ab60c7dc` registry reproduces all three primary bugs: two events yield count 1 after late registration; a new empty Session with the same ID inherits count 1/watermark 1; releasing the first of two registrants removes the shared key. Raw before-observations are retained.
- 16 focused Python registry regressions cover drive, ownership, identity/GC, versions, selections, errors, checkpoints, restoration and hydration.
- Nine real upstream/Python observations compare late registration, shared owners, identity, selected/host-only reads, detached checkpoints, restoration, rejection guards, hydrate and final unregister.
- 100 unchanged upstream assertions run from registry, core Session derived-cache, fork and surface suites. They establish a source baseline; they are not 100 Python parity assertions.
- Both new oracle commands are mandatory in `scripts/verify_release.py`; runner errors and missing/extra observations fail closed.

Clean-checkout full Python result: **3235 passed, 2 skipped, 2 warnings**. Existing Windows transport cleanup warnings and mock disconnect diagnostics are retained. The package has 351 byte-identical Python sources, five own-Python profile dumps and an isolated boot; ZIP SHA-256: `239de2759ffa83698c8c08f8367769c9c4342d63a8668066057aa5b5df27304d`.

Final clean-checkout gate and package identity are retained in `SESSION-PROJECTION-20260928-*` evidence artifacts after successful execution. Development dependencies are reused at pinned versions; this is not a fresh dependency-install claim.

## Next dependency order

1. Migrate domain registrations from the compatibility adapter to executable state/wire definitions: metadata-sensitive initialization, stateVersion, host-only versus visible state, and lifecycle ownership. Audit stats/title/todo/plan/permissions plus missing token/goal/subagent projections against actual upstream definitions.
2. Audit `storageDomain` before implementing `sessionProjectionCache`. The upstream cache requires coherent per-record writes, immutable header identity (`createdAt`/`cwd`), mandatory creation/turn-end/disposal checkpoints and fail-soft durability. Registry API existence is insufficient to certify this provider.
3. Integrate cache restore with shared preparation and cancellation, preserving exact prepared Session identity and constructor-owned suffixes. Test stale versions, recreated IDs, swapped roots, shrunk logs, failed writes and retirement/reload.
4. Only then migrate cold listing/history baseline and Web projection consumers, followed by complete profile journeys after Wire/Tools/Web providers.

Native upstream SQLite, compressed JSONL, arbitrary cross-process/power-loss behavior, full historical migration, full AgentLoop settings/profile journeys and Win7 remain outside this closure. Win7 machine/browser checks remain deferred by the user.
