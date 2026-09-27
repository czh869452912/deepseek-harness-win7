# Configured Agent startup/reload closure

Candidate: `5131a712`; pinned upstream: `cd5ef8148158c3a752a658978873241fdf8e2bbc`.

## Changes

- `0e9e92c5`: collect returned Fiber/FiberHandle disposal through its exact parent effect wrapper. Deferred children now nest under their labeled owner and dispose once. The provider-layer change includes a focused Cordis regression.
- `1532401d`: configured identity validation and launcher overrides; UUID fresh identities; exact restore-or-create; deferred explicit resume; overlapping lifecycle drain/cancellation; startup tracking and failure containment. The old factory cleanup cannot clear a replacement factory. The service publishes both existing snake-case and upstream camelCase names.
- `5131a712`: hung failure observers are isolated from teardown; late observer errors remain observed.

The prior real checkout `8201d7dc` was exercised before switching the release worktree: a configured exact Agent was not published and duplicate configured exact identities were not rejected. Raw baseline observations are retained.

## Verification

Final clean-checkout release gate passed: **3219 passed, 2 skipped, 2 warnings**, 176.30 seconds. Existing Windows Proactor cleanup warnings and mock socket disconnect diagnostics remain visible. Seven configured, nine factory, eight storage, five preparation, four live and seven cold paired observations match. Unmodified source suites passed: Cordis 80, Agent 100, Session 197. Cordis C1-C67 has 66 matches plus only the previously approved exact C58 Python-native signature. Isolated package boot passed. Pinned development dependencies were reused; no new empty-cache installation is claimed.

18 configured startup tests cover identity validation/overrides, generated identities, exact history reload, overlapping scope drain, cancellation, delayed storage, labeled child ownership, unrenderable startup/observer errors, late preparation resolution/rejection, missing explicit resume, hung index cancellation, two actual mock-LLM driver turns across reload and hanging failure observer isolation. The separate Fiber regression tests one exact nested child cleanup.

Seven real upstream/Python observations compare launcher selection, invalid configuration, missing explicit resume, history reload, overlapping drain, cancellation and deferred effect nesting. Prior public Agent factory and Session storage/preparation/live/cold comparisons remain part of the release gate. Source test counts are not translated into Python parity claims. The upstream config file includes parameterized cases: counting literal `it` declarations alone is not a reliable executed-test total.

## Boundaries and next direction

`CON-AGENT-CONFIG@1` covers this configured lifecycle boundary. It does not certify all AgentLoop behavior, runtime settings/maxParallelToolCalls policy, system-prompt variables or full launcher/profile integration. Python fresh configured agents finish via asynchronous plugin initialization; the result at the awaited mount boundary is tested. Win7 machine/browser validation remains deferred.

Next establish the full Session projection contract before Web replay consumers: use source tests `session.spec.ts`, `surface.spec.ts`, `derived-cache.spec.ts`, `request-header.spec.ts`, `fork.spec.ts`, `invariant.spec.ts` and `properties.spec.ts`. Compare actual event graphs, message/cache invalidation, context/header folding and fork boundaries with paired observations. Existing files named parity or counts of translated tests are not sufficient proof. Review historical migration and compressed JSONL/native SQLite separately.

Complete profile journeys remain dependent on the Session/Wire/Tools/Web contracts. If a projection interface changes, update its providers, persistence consumers and replay readers together rather than restricting edits to a single module's expected_paths.

Portable own-Python checks passed for minimal/standard/creative/web/headless; 351 Python files match the clean candidate byte-for-byte. ZIP SHA256: `bb53e97cbf4f3c196b2a9d028855b48b0a9db6616b0ee4362ad614872ea22f25`. The latest package is in `C:/Users/Administrator/.codex/worktrees/release-repro/deepseek-harness-win7/dist`, not the main checkout dist.
