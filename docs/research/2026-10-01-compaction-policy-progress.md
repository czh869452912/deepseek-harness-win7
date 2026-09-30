# Routed compaction policy and overflow recovery

Date: 2026-10-01. Work continues from product `c5180644`. Reference target:
`cd5ef8148158c3a752a658978873241fdf8e2bbc`.

This implements the request-pressure policy consumer following
[TokenMeter replay](2026-10-01-token-meter-replay-progress.md). It is not a
declaration of complete compaction, whole-project parity or Win7 certification.

## Implemented behavior

- Compaction configuration rejects unknown/retired settings and invalid values
  at plugin construction. Defaults match the reference: thresholdRatio 0.8,
  retainRatio 0.16, maxTokens 8192, compactionRetries 1, maxOverflowRetries 1,
  auto true, no separate summary target. Configuration and nested policy rows
  are detached and immutable.
- modelPolicies is an array of partial overrides keyed by exact provider/model.
  Retention uses one of retainRatio/retainTokens. Each summary target is omitted,
  cleared or replaced as a pair at its own scope. Inherited ratio conflicts are
  rejected at load; absolute retention conflicts are rejected against resolved
  model capacity.
- Automatic pressure uses the latest durable routed request, not AgentOptions
  fallback or a fixed 32000-token capacity. Adapter-owned model metadata scales
  the threshold and retained tail. Equality qualifies; a headerless request is
  skipped, and missing capacity produces a target-specific warning suppressed
  after its first occurrence. Cancellation is passed to metadata resolution.
- The optional model-free pruner runs only after pressure qualifies, followed
  by remeasurement through the singleton TokenMeter. Summary attempts retain the
  routed budget, remeasure after each replacement, and fail if the configured
  additional-attempt budget cannot relieve pressure.
- Canonical context overflow bypasses pressure/capacity/retention requirements.
  Recovery retries only after surface replacement generation advances. A landed
  prune still proves progress if optional summary work then fails. Cancellation
  prevents retry. Per-Agent retry caps reset on idle and on successful durable
  assistant messages. Agent/Session ownership uses weak keys and weak Agent
  values, so the Session-indexed reset lookup does not retain an Agent through
  its own Session.
- Default summary requests select the same exact route policy, retaining the
  original system/tools prefix and configured summary provider/model/maxTokens.
  The existing transaction now dispatches its summarizer through the engine.
- Basic plugin injection declares llm/tokenMeter/sessions; event registrations
  and the service follow Cordis fiber disposal. auto false suppresses automatic
  hooks while explicit compaction remains available.
- Removed the engine's flat message-list concatenation fallback, arbitrary
  default-Session selection, fixed threshold settings and constructor overrides.
  Automatic no-op now returns None, matching upstream null. Existing tests were
  moved to canonical request-header/capacity inputs rather than preserving the
  retired behavior.

## Migration deviation fixed

The Python AgentLoop previously accepted in-band terminal `error`/`aborted`
finish chunks as a successful assistant message. This bypassed the request-error
waterfall and prevented context-overflow recovery. The pinned AgentLoop handles
these terminal finishes before publishing an assistant message
(`reference/packages/core/agent-loop/src/agent.ts`, error branch around line 389).

The native loop now dispatches both thrown and in-band failures through the same
request-error seam. An unrecovered in-band failure retains chunks in the log,
publishes no successful/partial assistant message, and closes the turn as error.
Recovered requests rebuild from the replacement surface within the same open
step. This is a migration bug fix, not an upstream bug.

## UPSTREAM-COMPACTION-POLICY-001

The reference configuration validator creates the duplicate-policy key with
`provider + NUL + model` in `compaction-basic/src/config.ts`. Its declared string
validation accepts embedded NUL. Therefore the distinct pairs
`("a\\0b", "c")` and `("a", "b\\0c")` produce the same key and the second valid
override is falsely rejected as a duplicate. This is a configuration edge case;
no security impact is claimed.

The native validator uses the actual `(provider, model)` tuple. Identical pairs
are still rejected and lookups remain exact. The paired recipe
`embedded-nul-routes` executes the untouched reference resolver and native
resolver. Its reviewed difference gate requires the exact pinned SHA, exact
input, exact original duplicate error, and every field of the corrected frozen
config/policy/scaled spec. Other differences fail the gate. No reference source
was modified and no upstream issue was published.

## Verification

Commands and evidence:

```powershell
.venv\Scripts\python.exe scripts/compaction_oracle.py
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.compaction.config.mts
.venv\Scripts\python.exe -m pytest tests/test_compaction.py tests/test_compaction_policy.py tests/test_compaction_transaction.py tests/test_compaction_http.py tests/test_compaction_agent_loop.py -q
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/compaction-final.xml
```

- Untouched reference compaction tests: **197 passed / 12 files**. This is source
  baseline evidence, not 197 native parity assertions.
- Paired actual config/runtime observations: **22 matched + 1 exact reviewed
  upstream bug**. Compares resolved policies/specs, frozen snapshots, validation,
  full auxiliary request text/route/budget/prefix, metadata resolutions,
  selections, heuristic shadow prices, lifecycle positions and final replay
  measurements. Error prose is retained in reports but excluded from ordinary
  cross-language validation comparison; target identity and failure/success
  must still agree. The reviewed bug compares the original error text exactly.
- Native focused checks: initial policy/transaction/HTTP scope **68 passed**;
  actual AgentLoop **4 passed**, including thrown and in-band overflow, rebuilt
  replacement input, one start/end step pair, and unrecovered terminal failures.
- Full `.venv\Scripts\python.exe -m pytest tests`: **3913 passed, 2 skipped,
  1 warning**, 310.13 seconds, exit code 0. JUnit failures/errors are zero.
  The warning is the existing Windows Proactor transport destructor after loop
  closure, observed at the WebServer injection-row contract test. The existing
  pytest-asyncio loop-scope hint and HTTP abort/reset diagnostics remain; this
  is not a zero-warning or Win7 certification.
- The reviewed-bug gate was also checked against changed target SHA, input
  capacity, original error and corrected maxTokens; each unrelated difference
  was rejected.
- Actual `run_profile(web)` with a temporary home and a standard Agent passed:
  standing-preset compaction defaults, shared underlying TokenMeter state and
  LLM adapter registry, headerless no-op, Session flush, and server shutdown.
  The initial smoke incorrectly read the isolated compaction service from the
  Agent context and then compared caller-bound service proxy identity. The
  corrected check uses agentPresets.serviceFor and underlying service state.
  Both early failed checks still closed their servers, but exposed the known
  projection-cache/domain-close race diagnostic. The successful check drained
  cache work before shutdown; it does not certify general cache close ordering.
- Python 3.8 compileall and whitespace checks passed; the reference checkout
  remained unmodified. Migration check/ready are record validation only.

The paired report and raw producer logs are generated under
`.goose/out/compaction-paired.*`. Source and native fixtures invoke real Session,
TokenMeter and compaction implementations. The paired summary provider is a
deterministic adapter through each real LLM runtime; the AgentLoop tests also
use a controlled provider. These are not real remote-model acceptance or
browser interaction results.

## Remaining migration and delivery

The existing surface transaction, custom summarizer contract, full compaction
invariants, client projections and browser/history journeys still require a
complete combined audit. These bounded policy observations do not certify those
remaining contracts. Arbitrary JS Workflow/dynamic Host execution, Inspect and
other unaccepted modules also remain in the full migration objective.

Release direction remains the
[Python plugin distribution assessment](2026-09-30-python-plugin-distribution-assessment.md)
and [local implementation](2026-09-30-python-plugin-local-delivery.md): fixed
Python 3.8.10 Portable, Python Host plugins, optional prebuilt original clients,
profile/Loader identity, local-directory and ZIP installation, followed by
persistent creative-mode export, upgrade/rollback, locked dependency closure,
client compatibility and unified GitHub Release/npm/PyPI acquisition. This work
introduces no production dependency, QuickJS, Node Host or browser source change.
The existing portable builder copies the changed dsh modules; no new Portable
was built or published in this turn. Win7 hardware and target-browser validation
remain user-deferred; current Windows/Python 3.8 tests do not substitute for them.
