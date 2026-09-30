# TokenMeter replay, projection and upstream input-anchor fix

Date: 2026-10-01. Product parent: `49523b98`. Pinned upstream:
`cd5ef8148158c3a752a658978873241fdf8e2bbc`.
Environment: current Windows, native Python 3.8.10. This records implemented
behavior and executed verification, not whole-project or Win7 certification.

## Implemented

`TokenMeter` now owns isolated weak per-Session replay cells and registers the
canonical `tokenMeter` service. The plugin retains `token_meter` as a Python
service-name adapter. Production compaction and pruning read `tokenMeter` and
canonical measurement fields, including `totalTokens` and `heuristicTokens`.

The measured positional surface replays appends and inclusive replacements,
including zero-priced empty assistant nodes. Each event plans all fallible
changes before committing state or advancing its consumed log revision;
malformed boundaries, replacement ranges and cited provider chunks fail again
on retry without double-counting. Session objects with equal IDs stay isolated
and are not retained by the replay map.

Measurements are detached, deeply immutable snapshots. A matching canonical
envelope uses the latest successful provider usage only when its disjoint
input/cache/output buckets cover the complete estimated anchor. Otherwise it
uses an estimated baseline. Signed surface deltas track subsequent additions,
rewrites and replacements. Explicit request-header overrides reprice the
surface without changing logged routing or retrieving older success anchors.
Reasoning output is not counted twice.

Exact source chunk sequences reassemble provider output independently of a
rewritten durable assistant message; an absent legacy provenance list uses the
durable output, while an explicit empty list means known empty provider output.
Route image pricing replaces structural estimates occurrence by occurrence,
including nested tool-result images. Wrong occurrence counts fail explicitly.
Current and anchored input surfaces use the same routed pricing.

Pure estimates now count UTF-16 units, compact ECMAScript JSON text, empty
present system prompts and recursively nested blocks. The established Number
renderer is shared through `dsh/cordis/json_text.py`, also used by repeat-call
canonicalization and request-header schema equality. Integer-index property
enumeration, paired/lone surrogates, `1` versus `1.0`, and legitimate
`__proto__` data keys are covered. This is a plain-JSON renderer, not a JS engine.

Optional `sessionProjections` injection registers three executable, versioned
definitions: `tokenUsage@2`, `contextPressure@4`, `contextBreakdown@2`. They
preserve identical state objects for unchanged observations, reject invalid
checkpoint shapes, register when the provider arrives later, and unregister
with the owning fiber. Usage samples replace within an attempt and accumulate
across retry-start boundaries. Prompt pressure excludes output; window and
usage slots are independent. Pressure and breakdown keep bounded state via
adjacent shadow-price claims; mismatched claims fail, expired claims are
cleared, and historical unmetered replacements retain the upstream neutral
projection delta. Actual meter nodes still reprice those replacements.

Older test fixtures appended assistant messages without step boundaries.
They now construct bounded requests for meter/compaction integration tests;
the production replay validation was not weakened to accommodate them.

## UPSTREAM-TOKEN-METER-001

The pinned AgentLoop writes `step/start` before its accepted `user/message`
inputs (`reference/packages/core/agent-loop/src/agent.ts:286`). TokenMeter
captures its request surface at `step/start`, then uses that snapshot for the
successful request anchor (`reference/packages/llm/token-meter/src/index.ts`).
Consequently the accepted input, already included in provider input usage, is
also counted as a positive post-request surface delta.

The committed source probe runs the actual pinned AgentLoop and MockAdapter,
with two requests receiving `first` and `second`, each reporting 1000 input and
20 output tokens. It verifies that the actual requests contain those inputs.
For both requests the original meter reports baseline 1020, delta 10, total
1030. The Python actual-AgentLoop test reports baseline 1020, delta 0, total
1020, deduplicated usage totals across both requests, and equal pressure after
cold reconstruction apart from its new `session/end-seed` log revision.

The migration freezes the request input surface at the first matching provider
chunk. With no chunks it captures the surface immediately before the final
assistant message. This includes accepted inputs after `step/start` and keeps
later output-time injections as deltas. It preserves the original lifecycle
event order. A durable explicit request-sent surface boundary would provide
stronger attribution for arbitrary plugin writes between transport opening and
the first chunk; that boundary is not part of the pinned protocol. The current
fix does not claim to resolve that ambiguity or arbitrary concurrent writes.

The paired fixture additionally reproduces an input of `abcd` arriving after
step/start, with 100 input and 20 output tokens: original 129, corrected 120.
The gate permits only this exact fixture, target SHA, baseline, original delta
9 and total 129, corrected delta 0 and total 120. Every other measurement,
projection and checkpoint field must match. Negative tests reject different
targets, recipes, surface prices and projections. No upstream source was edited.

## Verification

- Python scoped estimator/replay, DeepSeek route pricing, compaction, pruning
  and repeat-reminder suite: **117 passed**. The new replay file contributes
  **35 cases**, including actual AgentLoop, weak ownership, malformed replay,
  optional provider arrival, checkpoint restore/hydrate and reversible unload.
- Pinned source tests: **109 passed / 5 files** via
  `vitest.token-meter.config.mts`. This includes turn-usage source tests as a
  source baseline, not a claim that Python turn-usage disclosure is migrated.
- `scripts/token_meter_oracle.py`: **15 matched + 1 reviewed upstream bug**.
  Both runners use real Session and projection services over shared recipes;
  the source probe separately reproduces the bug through actual AgentLoop.
  Artifacts: `.goose/out/token-meter-paired.json`, `.ts.json`, `.python.json`,
  `.0.log`, `.1.log`, and `.ts.json.loop.json`.
- Shared-JSON consumer revalidation: repeat-tool paired oracle remains
  **13 matched + 1 previously reviewed upstream bug**.
- Canonical `run_profile(web)` smoke: a real standard-preset Agent inherits the
  base-bundle meter, exposes all three projection values, measures a post-start
  input request as total 120 with delta 0, and flushes Session persistence.
  The temporary host was shut down; this was not browser or remote-LLM testing.
- Full `.venv/Scripts/python.exe -m pytest tests`: **3859 passed, 2 skipped,
  1 warning**, 304.67 seconds, exit code 0. JUnit failures/errors are both zero.
  Artifacts: `.goose/out/token-meter-final.xml` and `.log`. The warning remains
  the existing Windows Proactor transport destruction after loop closure;
  pytest-asyncio loop-scope hints and HTTP connection abort/reset diagnostics
  are not a zero-warning or Win7 certification.
- Python 3.8 compileall, reference-clean and diff whitespace checks passed.
  `scripts/migration.py check` passed; `ready` returned no ready tasks. These
  record checks do not certify the new behavior or whole-project parity.

Initial fixture/import failures and the real input-anchor assertion were
corrected before the final regression. The first Web smoke incorrectly looked
for the meter inside the standing preset; the base bundle owns it globally.
The corrected lookup passed. Its early shutdown also emitted the known
projection-cache/domain-close race diagnostic; the successful smoke drained
cache work before host shutdown. This does not certify general cache shutdown.

## Remaining migration and release work

`deriveTurnTokenUsage`, full billing disclosure, complete compaction policy and
its threshold/routing/retry contracts, all clients and actual browser pressure
journeys still require migration and joint verification. General JS Workflow
and dynamic JS Host execution, Inspect and other unaccepted modules remain
necessary for full pinned-source migration. No substitute completion scope is
declared here. No production dependency, QuickJS or browser source was added.

Release direction remains the fixed Python 3.8.10 Portable body and unified
profile/Loader plugin composition described in
[the plugin assessment](2026-09-30-python-plugin-distribution-assessment.md)
and [local directory/ZIP implementation](2026-09-30-python-plugin-local-delivery.md).
Source export, upgrade/rollback, locked dependency closures, optional client
verification and unified GitHub Release/npm/PyPI acquisition remain pending.
The Portable builder copies these Python modules with the existing `dsh` tree;
no new Portable was built or published. Win7/device-browser verification
remains deferred by the user; current Windows tests do not replace it.
