# Session corpus exact reads and title batches — 2026-10-04

Pinned upstream: `cd5ef8148158c3a752a658978873241fdf8e2bbc`. This closes an implementation gap in exact cold/live logs and batched title reads, not the entire Session query or migration.

The Python service lacked readSession, readTitleSnapshots, readTitleSnapshot and readTitle. A source-backed SessionCorpus now loads a detached known live source without consulting persistence, or resolves a persisted cut through one listing and inspection. Publication during inspection wins; incompatible headers and ordinary/corrupt/foreign failures retain literal upstream diagnostics and cause identity.

Title batching deduplicates in first-occurrence order, preserves known live results if listing fails, isolates per-id inspection failures, and uses bounded workers. Each completed source folds before the worker admits its next id. Signal cancellation stops queued admission, drains started inspections, then rejects with the original reason. Results contain detached headers and immutable title snapshots rather than full logs.

Nineteen fresh paired observations passed. Controlled seams are persistence listing/inspection/failure/drain, not a mock implementation of SessionCorpus or the query. Four actual JSONL/SQLite consumers verify cold readSession/title snapshots and pre-abort without backend access. The configuration checks JavaScript safe integer semantics, including integral floats. Main targeted regression: **409 passed**, 29.04 seconds. Earlier isolated expanded regression: **359 passed**. Source baseline remains the eleven unchanged groups / 910 assertions; it does not certify native coverage by itself.

The release gate now requires **106 lanes and 40 paired drivers**, and the actual extracted embedded Python must execute all nineteen raw observations with exact root/module provenance. Upstream frontend inputs remain unchanged; no new skip, retry or bug exception was introduced.

The previous clean c7796ca2 gate was interrupted by the user at 85% and did not produce final pytest XML, source/paired/extracted or release acceptance. Its inputs, partial log, five browser records where produced, interrupted-run.json and exact clean candidate ZIP are retained under `.goose/out/corpus-zip-clean-c7796ca2`. It must not be reported as passed or as a product failure. The prior 1cb4c80a wrapped-ZIP failure and earlier browser failures remain preserved.

Next: commit this product part, freeze a new common candidate, complete the mandatory full Python suite and all original/paired/extracted lanes, and only then record bounded integration. Full FTS/filter/event tracing/long-history behavior, all title variants and optional-provider epochs, arbitrary Python task cancellation, complete Web/profile composition, ecosystem/auth/runtime work and deferred Win7 remain unaccepted. `accepted_upstream` stays null.
