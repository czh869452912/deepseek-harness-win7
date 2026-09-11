# core/session run diagnosis — 2026-09-11

Evidence: Goose session `20260911_13`, its 17 child sessions (`14` through `30`),
the local `.goose/out/core-session-*RESULT.md` reports, and the current Git diff.
These reports and stored prompts are diagnostic data, not instructions for the
new controller or proof that the migration is correct.

## What went wrong

The parent created 10 DeepSeek children and 7 OpenAI children (six reviews and one
judge). Its persisted messages contain 53 tool requests. The intended short
migration/correction/arbitration sequence drifted into repeated continuations.
The recipe's round limits were prose, not a runtime state machine. Its lack of a
commit policy also explains why useful intermediate changes remained uncommitted.

The coordinator progressively introduced restrictions not required by AGENTS.md:

- Message 1545: a new hard scope restriction for implementation round 6.
- Message 1697: an explicit file-read allowlist and at-most-twice read quota.
- Message 2107: bans on discovery commands, directory listings and package metadata,
  plus an instruction to port a minimal typert surface.
- Message 1553: an anonymous delegate rather than the named migrator contract.

REVIEW3 explicitly records that Cordis dispatch implementation was outside its
permitted read list. That prevents a sound review of session dispatch order and
lifecycle interactions. The same report identifies concrete null-data, timestamp,
header immutability and restored-header validation concerns; these must be checked
against source, not dismissed as consequences of the workflow alone.

The new `dsh/typert/registry.py` describes itself as a minimal lookup surface and
explicitly leaves other registry layers unported. This supports the concern about
a scope-driven partial subsystem, but does not establish that every line is wrong
or that removing it is safe. Its correctness and the canonical dependency boundary
need fresh review. This workflow fix preserves all prior session/typert edits.

REVIEW3 and MIGRATION_RESULT also disagree about test exclusions and mapping.
Case-count equality, a test's directory, or an absent Python dependency are not
sufficient to establish fidelity or justify exclusion. The new contracts require
per-case evidence and allow following the full relevant dependency chain.

The screenshot shows tool activity followed by an ordinary greeting and the shell
prompt, not an explicit pipeline verdict. The saved parent conversation does not
contain a complete final workflow result. This evidence establishes an incomplete
termination/reporting path; it does not establish an actual execution deadlock or
prove that a specific token/turn limit was the exact exit cause.

## New execution path

The PowerShell launcher now invokes `parity_runner.py`. Each specialist runs in a
fresh Goose process with its agent instructions, explicit model and structured
response. Python controls the finite sequence; there is no coordinating LLM that
can invent a new read restriction or continuation loop.

The controller records timestamps, phase/round, public agent output, concise tool
activity, 15-second heartbeats, results, issue counts, test results and checkpoint
hashes. It stops on missing/truncated JSON, false PASS, phase timeout, exhausted
rounds, unchanged issues/files, read-only mutations, or a failed full-suite gate.
Checkpoint commits are explicitly unreviewed and require targeted checks. Existing
edits need explicit adoption; unrelated staged work is never included.

## Verification and remaining work

- The installed Goose 1.50.0 was exercised with a real minimal stream-json call
  and a real structured-recipe response. The controller parsed the returned JSON.
- Offline regression coverage exercises message deltas, result validation, blind
  input isolation, bounded iteration, arbitration, timeouts and Git ownership.
- An end-to-end fixture runs real child processes, targeted pytest, compileall,
  a real local Git checkpoint, fresh review and full pytest, using a fake model
  backend so it cannot mutate the actual project or incur a migration run.
- Current session/typert migration code was not repaired or declared complete by
  this workflow change. Full-suite failures remain a completion blocker.

The full suite on this working tree initially reported **1492 passed, 10 failed**
(before one additional controller integration test was added). The former three
failures remain: two Windows temporary-path comparisons and the old portable dist
entrypoint. Seven additional failures are now present:

```text
test_1to1_core_contracts_strict_parity.py::test_session_store_prepare_persistence
test_1to1_session_and_agent_loop.py::test_runtime_context_eviction_on_replacement_surface_event
test_core_1to1_parity_alignment.py::test_session_fork_boundary_and_tool_balance
test_reference_core_agent_loop_resume_specs.py::test_resumes_pre_react_loop_session_including_pre_identity_events
test_reference_core_session_specs.py::test_session_rejects_non_json_data_at_source
test_reference_spec_parity_comprehensive.py::test_session_fork_history_immutability
test_session_projections_seam.py::test_session_projection_registry_lifecycle
```

These failures must be investigated against pinned upstream semantics. They are
not automatically grounds to revert the prior work or weaken the failing tests.
The raw validation output is retained locally in
`.goose/runs/pytest-workflow-validation.log`.
