# Source-qualified persistence snapshots — 2026-10-04

Pinned upstream: cd5ef8148158c3a752a658978873241fdf8e2bbc. The isolated implementation is now being precisely promoted after the preceding owned-WebServer reset and Gateway closure repairs.

The old JSONL snapshot token used timestamp/size, and native SQLite used MAX event time/seq. Those identities could survive a same-size/mtime rewrite, alias a copied store, or miscount a multi-event batch. Canonical listSnapshots now uses physical source qualification; SQLite persists a store UUID, per-session incarnation and transactional per-batch revision. Actual memory stores are supported without creating a file named :memory:.

Eighteen fresh observations run the actual pinned JSONL/SQLite provider plugins and native providers. They compare lazy creation, stable reads, nonempty/no-op append, detached headers, reopening, copied namespaces and exact pre-abort. JSONL physically rewrites the tail at unchanged length and restored mtime, proving the change-time field invalidates the token. SQLite proves one increment for a two-event batch and isolated in-memory namespace/counters. Source/native raw observations agree with independently declared literals.

Windows Python 3.8 st_ctime is creation time, so a scoped attribute-handle reader obtains FileBasicInfo ChangeTime and legacy file identity. Every handle closes on success/failure; binding types are cached to avoid repeated ctypes pointer classes. Extended Unicode paths use the ordinary Windows extended-path prefix. No modern OS patch or global runtime modification is introduced.

Microsoft documents [GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex) and [FILE_BASIC_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info) as available from Windows Vista. This API availability supports the chosen Win7 implementation; it is not real-machine certification.

Native SQLite identity/revision backfill is one BEGIN IMMEDIATE transaction; a failed backfill rolls back DDL and closes its unpublished connection. Successful reopen preserves the prior incarnation. A failed event suffix rolls back both events and counter. Two actual SQLite instances share persisted store identity and see committed revision changes. JSONL checks cancellation after stat success/failure, before treating ENOENT as an omitted log.

Four actual cold JSONL/SQLite consumers and native transaction/handle/long-path boundaries pass. The isolated expanded regression passed 591 tests in 24.03 seconds. Seven WebServer reset lanes and five Gateway closure lanes remain required from the preceding repairs; the proposed complete gate requires 152 mandatory lanes, twelve unchanged source groups/920 assertions, 45 paired drivers and the actual extracted snapshot observer. Promotion and a separate clean gate remain required.

The native SQLite physical format remains legacy tables plus identity/revision columns. These logical observations do not certify upstream schema-19, compression/chunks, all ordering/duplicate artifacts, cross-process power loss, provider epochs, FTS/index generations or Win7. Non-Windows physical birthtime qualification remains unaccepted. accepted_upstream remains null.

The precise main promotion preserves its existing inspect cancellation signature and both previous socket-lifetime repairs. It passes 511 contract/gate regressions in 20.48 seconds and 48 storage/cache regressions in 1.61 seconds, including the fresh eighteen-case actual-provider paired driver. The candidate must now be committed and frozen for complete acceptance.
