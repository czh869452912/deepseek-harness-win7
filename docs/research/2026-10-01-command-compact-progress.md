# Manual compaction command and shared command runtime

Date: 2026-10-01. Baseline: `400b54d8`. Pinned original:
`cd5ef8148158c3a752a658978873241fdf8e2bbc`. Native runtime is Python 3.8.10
on the current Windows development machine. This continues the
[compaction transaction work](2026-10-01-compaction-transaction-progress.md).
The scope below is not full compaction, full migration or Win7 certification.

## Implemented behavior

`command-compact` requires both `commands` and `compaction`, so a missing backend
keeps the row inactive rather than publishing a command with a fallback error.
It uses the original argument-free description, rejects arguments with the
original usage text and ECMAScript whitespace rules, and passes the invocation's
exact Agent, signal and command ID to the backend. No ambient initiator is used.

Success reports the shadowed item/token counts and points `sourceEventSeq` to
the summary. No-history uses the original direct outcome. All six expected
manual errors have the original human-facing text. Unexpected backend failures
propagate to the command executor, which owns the run/done error pair. Unknown
manual error codes fail loudly. Caller cancellation retains executor abort
behavior rather than being converted into an ordinary completed command.

Each handler starts an owned Task, tracks it until settlement and observes its
exception. The composite Cordis effect collects drain before registration, so
LIFO teardown unregisters first and then waits for already-started calls through
close and flush. The command executor can stop awaiting a cancelled request
without cancelling the underlying handler. Late settlement remains observed.

Manual compaction now classifies failure to enter Agent maintenance as `busy`.
Python `run_maintenance` reports admission failure when its coroutine is awaited;
the `entered` latch distinguishes this from an error inside the admitted job.
This is the adaptation of the source's synchronous admission throw. An Agent
already in maintenance publicly reports idle but cannot admit a second job;
the second command gets the expected error and opens no compaction bracket.

## Shared runtime defects fixed

The formal Web profile revealed that standing presets registered the command,
but the root command runtime could not find it. Configured Python Agent scope
keys live on `agent.ctx`; they are not always the Agent object itself. Lookup
now uses the bound Context key when present and retains the Agent-key fallback
for direct scope users. Parent preset contributions become visible only to
their descendant Agents; other preset scopes remain isolated. Disposing the
registration removes it from both discovery and execution.

The paired `command-caller-abort` recipe then exposed a second native defect.
A backend aborts its signal and rejects in one turn; the plugin produces its
internal cancelled outcome, but the source executor already rejected with the
exact caller reason. Python's asynchronous abort waiter could report both tasks
done and prefer the handler result. The shared runtime now records abort
settlement synchronously in the listener and races it against the handler's
settlement callback. It removes listeners on exit and consumes detached task
failures. Both the exact caller reason and command/done text match the source.
Wait-only historical signal adapters still have their native asynchronous
notification boundary; this work does not claim synchronous JS ordering for
arbitrary non-native signals.

These are migration defects; no new original bug was identified. The earlier
NUL route-key and custom-summary metadata bugs retain their separate exact
reviewed gates.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests/test_command_compact.py tests/1to1/interaction/test_commands.py tests/test_compaction_transaction.py -q
.venv\Scripts\python.exe scripts/compaction_oracle.py --output .goose/out/command-compact-paired.json
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.compaction.config.mts
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/command-compact-final.xml
```

- Focused native checks: **99 passed**, including shared command assertions,
  compaction transactions, exact cancellation, unregister-before-drain,
  maintenance overlap, argument whitespace, error presentation and scoped
  registrations. Earlier scopes passed 40, then 75 checks; those do not replace
  the final 99-case scope after cancellation-race repair.
- Three actual `run_profile(web)` journeys execute `/compact` under standard,
  PTC and Cordis standing presets. Each uses the composed command runtime,
  actual LLM seam with a deterministic adapter, TokenMeter, Agent maintenance,
  summary replacement and persistent Session. Each closes/restarts the profile
  and cold-reads the exact command/compaction event sequence and identities.
  Cache work is explicitly drained before shutdown; this does not certify
  arbitrary projection-cache/domain close races.
- The initial profile tests failed because the command lookup did not see the
  scoped registration. Correcting the shared runtime made all three pass;
  the failures were not bypassed by a test-only command registration.
- Paired observations: **45 matched + 2 exact reviewed original bugs**, with
  15 added command recipes. They compare original command plugin/runtime and
  native plugin/runtime over real Sessions, controlled capability backends,
  full command/compaction log payloads, Agent/signal/command identity forwarding,
  success/no-history, BOM/NEL arguments, six errors, unexpected errors,
  pre-abort, same-turn caller abort and close/flush drain. Random executor IDs
  normalize to one literal while their equality is independently observed.
- Original source baseline: **197 assertions / 12 files passed**; these are
  not 197 additional Python parity cases.
- Final full suite: **3942 passed, 2 skipped, 1 warning**, 336.06 seconds, exit
  code 0; JUnit failures/errors are zero. The warning is the existing Windows
  Proactor transport destructor after loop closure at the WebServer injection
  test. The pytest-asyncio loop-scope hint and HTTP abort diagnostic remain.
  This is not a zero-warning result or Win7 certification. JUnit is retained at
  `.goose/out/command-compact-final.xml`.

The intermediate full suite before the cancellation-race fix passed **3941
tests, 2 skipped, 1 warning**, 314.27 seconds. It is historical evidence only,
not validation of the final shared cancellation implementation. Current source
and Python producer logs/rows are under `.goose/out/command-compact-paired.*`.
Python 3.8 compileall and diff checks passed; the pinned reference is unchanged.
Migration check/ready validate records, not project parity.

## Remaining migration and distribution

Full compaction invariants, durable error-chain rendering, all combined
cancellation/maintenance ordering and browser/client history presentation still
need a complete audit. These Host integration journeys are not actual browser
interaction or real remote-model acceptance. Arbitrary original JS Workflow,
dynamic JS Host, Inspect and other unaccepted modules remain within the goal.

The [distribution assessment](2026-09-30-python-plugin-distribution-assessment.md)
and [local delivery](2026-09-30-python-plugin-local-delivery.md) still govern:
fixed Python 3.8.10 Portable; profile/Loader-managed Python plugins; local
directory/ZIP delivery already implemented; optional prebuilt clients; then
persistent creative export, upgrade/rollback, locked offline dependency closure
and unified GitHub Release/npm/PyPI acquisition. These remaining stages are not
implemented by this command work. No production dependency, QuickJS, Node Host
or browser source was added. No Portable was rebuilt or published; Win7 hardware
and target-browser acceptance remain user-deferred.
