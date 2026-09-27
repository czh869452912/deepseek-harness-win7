# Inventory and contract closure — 2026-09-27

This batch closes the active Cordis foundation/necessary-consumer work, not a claim
that every upstream business package has been re-certified. The upstream target is
still `cd5ef8148158c3a752a658978873241fdf8e2bbc`.

## Source inventory

`scripts/migration_inventory.py` regenerates every tracked manifest classification,
local package dependency edge (including peer/optional/dev scopes), non-package
surface ownership, official source test identity, and dynamic contract declaration
location. Classification is responsibility, not migration status. Runtime-computed
service/event expressions remain explicitly unresolved source discovery; the nearest
package owns triage. Parameter factories are not silently counted as executions.
The selected critical profile modes are explicitly expanded in the consumer audit.

The complete index extends beyond direct Cordis imports. The earlier
`cordis-inventory.json` remains a narrower foundation/consumer discovery index.
Neither Python test counts nor matching test titles establish 1:1 parity.

## Contract-first workflow

`CON-CORDIS-CORE@10` specifies the enumerated lifecycle, event, loader, include, HMR,
schema and critical preset observations. `CON-BOOT-SESSION-SPINE@1` specifies the
real profile -> tool turn -> JSONL -> shutdown -> new Context -> resume workflow.
The spine requires the core provider revision before integration. The LLM transport
is the only substituted provider in the spine regression.

An interface change belongs to one contract transaction: change the provider and
all necessary consumers together, update the contract revision, invalidate older
consumer acceptance, then run the shared regression before integration. Expected
paths describe ownership and collision risk, not hard filesystem permissions.
Unrelated work must wait on the contract dependency; it must not adapt around an
unsettled interface. Records and read-only gates are the delivered first phase;
a distributed scheduler/atomic lease service is not part of this implementation.

## Await boundary review

`cordis-await-audit.json` indexes 166 await expressions across 11 foundation and
selected consumer files, with ownership/state-boundary decisions and probe families.
The review found additional settled-result defects in serial dispatch and HMR
refresh coalescing. C63-C67 retain before/after observations. Custom awaitables and
cancellation-before-continuation have additional local regressions.

C58 deliberately demonstrates native Python completed-Future continuation versus
JavaScript resolved-Promise continuation. Python 3.8 cannot globally intercept
awaits inside arbitrary user coroutines. C59 verifies the explicit checkpoint;
Preset generation refresh, serial, and HMR own and preserve their required
boundaries. Raw oracle exit remains 1 for C58. A separate scoped gate checks the
exact known C58 signature, requires C59 and every other scenario to match, and
rejects missing, duplicate, errored, or newly different observations. This is the
Python-language adaptation allowed by the project, not a hidden test exclusion.

## Verification boundaries

All 57 official preset cases now have assertion-level Python mappings; the previous
39 missing entries and reviewed subsets are closed. The five selected upstream
suites run unchanged (80 actual executions). Preset base URL validation and nested
error reporting were repaired from reproduced failures. The full Python regression,
paired probes and fresh portable build will be recorded against the committed
candidate. Win7 real-machine/browser certification remains deferred by user.
External paid/model-provider certification is not inferred from mock LLM tests.

## Full-suite consumer follow-up

The first complete run exposed six standalone Web RPC failures: the fallback roster
was constructed without the newly enforced base URL. The adapter now supplies the
shipped import anchor on a derived Context that retains the same owner fiber, leaving
the caller unchanged. The seventh failure was negative-test contamination: intentional
late global publication left its throwing invariant observer active during teardown.
The port now mirrors the official row-owned late-service effect and explicitly unloads
the diagnostic before fixture cleanup. Teardown asserts no mounts from that root
remain; it never clears the global mount registry to make a test pass. The original
full failure and 102 passing consumer regressions are retained as separate artifacts.

## Final candidate

Product candidate: `25f59152523eccb1eb79dc8ae1090481cdee8214`.
Full Python 3.8 suite: 3064 passed, 2 skipped, 2 warnings, exit 0.
Unmodified upstream critical suites: 80 passed. C1-C67: 66 matched; C58
native divergence retained, exact-signature scoped acceptance passed.
Portable rebuilt from this candidate: 341 Python sources match, five profile
configuration smokes and isolated real boot/shutdown pass. ZIP SHA256:
`8dc19adf8af3abb66026f53c218e3729c756086faa73a4e84484d5e58ecebead`.

All six active batch tasks bind fresh passing acceptance to this candidate, with
contract revisions and input/artifact hashes. Final record-only commits do not
change this tested product candidate. Win7 machine/browser certification remains
deferred, and whole-project accepted_upstream remains unset.
