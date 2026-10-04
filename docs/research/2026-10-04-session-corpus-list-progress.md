# Session corpus listing progress — 2026-10-04

Pinned source: `cd5ef8148158c3a752a658978873241fdf8e2bbc`. This is bounded listing work, not full Session replay or search acceptance.

The actual upstream SessionCorpus forwards the caller signal into persistence.list, retains the original error or foreign rejection as cause, and reports the conflicting Session identity. The Python query previously called list without that signal, shortened both diagnostics, and retained the ThrownValueError wrapper instead of its foreign value.

Twelve fresh source/native observations now match literally: no provider, live/persisted overlay, ASCII tie ordering, duplicate durable headers, conflicting headers, ordinary and foreign listing failures, abort before and during listing, exact signal forwarding, live publication during listing, and cloned metadata detachment. Persistence listing gains an optional signal and actual JSONL/SQLite pre-abort checks precede backend access. Existing no-argument callers remain valid.

Main targeted regression: **365 passed**, including the actual paired driver, strict observer counterexamples, both durable providers and release-gate refusal tests. Source baseline: **70 unchanged assertions** across session-query, tracing and search helpers; this is a source baseline, not seventy native parity cases. The complete gate now requires 99 lanes, eleven source groups / 910 assertions and 39 paired drivers; the extracted runtime must execute the same twelve declared listing observations.

Previous clean candidate `1cb4c80a` failed full regression: **5849 passed, 1 failed, 6 skipped, 1 existing Proactor warning**, 1341.84 seconds. Failure was wrapped-ZIP reinstallation at the redundant post-extraction directory rename, WinError 5. All five mandatory browser journeys passed in that run; historical startup cancellations remain unclassified. Its full output and actual JSON/NetLog records are retained under `.goose/out/point-read-clean-1cb4c80a`. No original frontend input, skip policy or upstream bug exception changed.

Next: independently commit the installer staging fix, then freeze a fresh candidate for complete regression and extracted verification. Full corpus exact reads and concurrent title observations, FTS generations and long replay, arbitrary locale collation, full Web/profile composition and deferred Win7 remain open. `accepted_upstream` remains null.
