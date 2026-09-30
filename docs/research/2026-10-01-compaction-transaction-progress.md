# Compaction snapshots, provenance and cancellation

Date: 2026-10-01. Product baseline: `ff49dedd`. Pinned upstream:
`cd5ef8148158c3a752a658978873241fdf8e2bbc`. Environment: native Python
3.8.10 on the current Windows development machine. This continues the
[policy work](2026-10-01-compaction-policy-progress.md). It covers the listed
transaction behavior, not full compaction, full migration or Win7 certification.

## Implemented contracts

- The replaceable hook receives `summarize(input, agent, signal)` with selected
  derived messages and optional system/tools captured before awaiting the hook.
  The default summarizer consumes this snapshot, while routing resolves against
  the current Agent/session at call time. A hook that changes the request header
  retains the old prefix and uses the new route, matching source behavior.
- Shadow accounting uses prepared meter nodes' `heuristicTokens`; shrink
  comparison uses route-priced `tokens`. Custom summary output cannot replace
  the measured count, transaction identity or replacement range.
- Durable summaries contain only supported output fields. Private fields do not
  enter the log. `llmStreamCall` is written only for an exact true marker;
  unmarked raw output does not claim an LLM seam call. Optional usage and token
  caps preserve presence semantics.
- Automatic transactions forward the signal without the manual transaction's
  explicit abort checks. Manual checks preserve an exception abort reason by
  identity, including after flush. Non-exception reasons are carried on Python
  `CancelledError.reason`, since Python cannot throw arbitrary JS values.
- Manual maintenance subscribes to Agent/caller cancellation through an owned
  AbortController, tracks first observed origin, removes relays on exit, and
  classifies Agent-origin cancellation as `cancelled`. An already-aborted caller
  precedes busy validation. Historical asyncio.Event inputs use the existing
  asynchronous adapter; this does not certify synchronous AbortSignal ordering
  for Events.
- Automatic surface changes remain unclassified exceptions; manual callers get
  `changed`. Hook-thrown manual errors are classified by transaction stage.
- Flush callbacks may return nothing. A flush failure is `persistence` after a
  closed bracket; caller cancellation takes precedence. Failed close is tried
  once, retains the durable lock and remains a commit failure.
- Positional `compactRegion(start, end, agent, signal)` forwards argument four.
  Region/manual entry points no longer implicitly select default-session.
- Empty-summary validation uses ECMAScript whitespace rather than Python strip.
  The BOM/NEL difference has focused coverage. Images are checked recursively
  through the shared content helper; recursive image integration is not
  separately certified by this report.

## UPSTREAM-COMPACTION-SUMMARY-001

Pinned `compaction-basic/src/region.ts::summarizeCompaction` constructs its result
with `{ ...prepared, ...summaryResult, checkpointMessage }`. Declared
SummaryResult excludes transaction metadata, but a runtime custom summarizer
can return extra fields that overwrite prepared metadata before stability
checking and commit. The reproduced hook returns `shadowedTokenCount: -1`.
Original code writes and returns -1 although the selected node's heuristic
price is 1208, corrupting shadow accounting consumed by replay. Other prepared
field overwrites are possible from this spread but not independently certified.

Native code retains prepared metadata separately and copies supported summary
fields only. The same recipe writes/returns 1208; identity, prefix, raw output,
replacement nodes and event sequence otherwise match. Native tests additionally
exercise identity/command/private field spoofing with absent/false/true markers.

The paired gate permits only both complete fixed output rows at the pinned SHA
and exact `transaction-private-fields` recipe. It verifies source -1 and native
1208 without removing accounting fields from ordinary comparisons. Mutations
of target, marker, source count, native count and an extra native output field
were rejected. The earlier NUL route-key bug has a separate exact gate.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/test_compaction.py tests/test_compaction_transaction.py tests/test_compaction_http.py tests/test_compaction_policy.py -q
.venv\Scripts\python.exe scripts/compaction_oracle.py --output .goose/out/compaction-transaction-paired.json
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.compaction.config.mts
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/compaction-transaction-final.xml
```

- Focused native checks: **79 passed**, covering actual loopback HTTP summary,
  custom hook dispatch, prefix snapshot, provenance, void/failed flush, caller
  reason identity, Agent cancellation, relay removal and surface stability.
  The initial snapshot fixture expected empty tools to survive canonical header
  normalization. It was corrected to a nonempty tool prefix; final run passed.
- Paired observations: **30 matched + 2 exact reviewed upstream bugs**. Nine
  added recipes use real original/native region transactions, Session and
  TokenMeter. They cover snapshot/routing, private fields, marked output,
  manual/automatic outside-span changes, hook error classification,
  void/failed flush and caller cancellation after flush.
- Original source baseline: **197 passed / 12 files**, not 197 additional
  Python parity cases.
- Full suite: **3924 passed, 2 skipped, 1 warning**, 305.91 seconds, exit code 0.
  The warning is the existing Windows Proactor destructor after loop closure.
  The pytest-asyncio loop-scope hint and HTTP abort diagnostics remain.
- Python 3.8 compileall, migration check/ready and whitespace checks passed;
  original checkout unchanged. Record validity does not certify parity.

Paired rows and raw producer logs are under
`.goose/out/compaction-transaction-paired.*`; full-suite JUnit is
`.goose/out/compaction-transaction-final.xml`. Controlled providers/custom hooks
are not real remote-model or browser-interaction acceptance.

## Remaining migration and distribution

The `/compact` command's signal/command identity, argument validation, error
presentation and unload drain still need migration. Full error-chain rendering,
maintenance admission with waking queued work, combined cancellation ordering,
all transaction invariants and client/history/browser journeys need a complete
audit. Arbitrary JS Workflow/dynamic Host, Inspect and other unaccepted modules
remain within the full objective.

The [distribution assessment](2026-09-30-python-plugin-distribution-assessment.md)
and [local delivery](2026-09-30-python-plugin-local-delivery.md) continue to govern
release: fixed Python 3.8.10 Portable; profile/Loader-managed Python plugins
from directories and ZIP; optional prebuilt clients; then persistent creative
export, upgrade/rollback, locked offline dependencies and unified GitHub
Release/npm/PyPI acquisition. Those remaining stages are not implemented or
certified here. No production dependency, QuickJS, Node Host or browser source
was added; no Portable was rebuilt/published. Win7 hardware/browser validation
remains user-deferred; current Windows tests cannot substitute for it.
