# Session filters and semantic documents — 2026-10-04

Pinned upstream: `cd5ef8148158c3a752a658978873241fdf8e2bbc`.

The native service lacked filterSessions/filterEvents. Existing helpers silently treated missing value arrays as empty, ignored explicit null bounds, accepted bool/non-finite bounds, and emitted diagnostics without the source prefix. Semantic documents marked every append event current even after replacements. Text predicates compiled only while iterating documents, so invalid whitespace text escaped validation on an empty collection.

The public calls now capture detached materialized filters before returning their awaitable. Invalid materialization becomes an awaitable rejection rather than a synchronous throw; invalid filters still precede signal/source work. The shared helpers preserve literal errors, nullable metadata and finite numeric ranges. Documents derive metadata from one canonical whole-log surface fold. Text matching uses explicit ECMAScript whitespace/BOM behavior, literal escaping and the source I/dotted-I/dotless-I equivalence rather than Python's extra matches.

Thirty-three fresh source/native observations match, including mutation after the call and before awaiting. Four real JSONL/SQLite consumer lanes cover cold surface-aware filtering, detached semantic results, invalid-before-abort and pre-abort without provider access. Isolated expanded regression: **165 passed**, 17.30 seconds; expanded gate/consumer regression: **550 passed**, 34.35 seconds. No new skipped source assertion, retry or bug exception was introduced.

The preceding clean 5c0b3c5e product passed its complete gate and has bounded acceptance recorded in 2bf8b59b. This filtering part was then promoted with provider/helpers, source/native/literal observers, durable consumers and release/extracted requirements. Main gate/consumer regression: **593 passed**, 41.86 seconds. A subsequent clean full gate with 119 mandatory lanes, eleven source groups / 910 unchanged assertions, 43 paired drivers and the actual extracted observer is required; filtering itself remains unaccepted.

Complete Unicode-version folding, additional first-party/plugin extraction types, FTS/ranking/cursors/index generations, optional-provider epochs/arbitrary Task cancellation, full current Web/profile composition and deferred Win7 remain unaccepted. `accepted_upstream` stays null.
