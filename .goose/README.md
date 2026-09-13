# Goose parity workflow

## Lightweight local console

```powershell
.\.goose\run-project.ps1 -Action console -Port 8766
# Open http://127.0.0.1:8766 (does not resume workers)
.\.goose\run-project.ps1 -Action overview
.\.goose\run-project.ps1 -Action follow -Task vendor/cordis
```

The console offers task filtering, per-worker output/tool-result/thinking streams,
an aggregate timeline, and model allocation editing. No gateway, container, Node
build, external service or extra Python package is required. The API binds only to
loopback; configuration writes require the same origin and a local request token.

`.goose/agent-config.json` is the controller's canonical model allocation for
architect/migrator/reviewer/judge. Edit it through the console or Git. Existing
Goose provider IDs are used directly; credentials remain in Goose/environment
configuration. The next newly started phase reads the new allocation; an in-flight
request or resumed native session keeps its original model. Each worker records
the requested provider/model, configuration revision and interpreter. This is the
requested model, not a claim about a gateway's undisclosed backend routing.

Worker events are persisted separately before rendering. Tool arguments/results
are complete on disk; public provider thinking is displayed separately and never
parsed as a verdict. Redacted thinking cannot be reconstructed. Historical logs
previously stripped by the controller cannot recover those missing fields.
Per-run byte sequence cursors support reconnects; retries archive old raw logs and
stop/complete drains queued output. A forced OS kill cannot guarantee flushing
events that the child never delivered. Heartbeats update liveness without replacing
the last useful activity or flooding terminal output.

`run` defaults to concise, attributed lifecycle/tool summaries. For complete
prefixed terminal output use `-OutputMode plain`; use a separate `overview` or
`follow` terminal for inspection. UI preview truncation never truncates the retained
event. Test subprocesses inherit the controller interpreter on PATH and
`DSH_TEST_PYTHON`; phase preflight checks Python 3.8, pytest and pytest_asyncio.

Invalid incremental plans enter `PLAN_REPAIR`, retaining implementation/review
and the round cursor. The architect repairs only graph data, without source tools;
unresolved repairs remain visible and escalate after two repair attempts. Explicit
ESCALATE and recurring upstream findings are adjudicated before optional planning.
Recovering a historical READY record with a plan error routes it to plan repair
before invoking implementation. The console itself never resumes the scheduler.

Cross-host export/import and multi-tag campaign management remain separate future
work; this console does not make existing absolute-path task databases portable.

## Whole-project scheduling

### One-task lifecycle pilot and integration ownership

```powershell
.\.goose\run-project.ps1 -Action pilot -Task vendor/cordis
```

`pilot` forces one worker, claims only the selected task's atomic group, and stops
if prerequisites or adjudication need attention. It never starts unrelated READY
tasks. On integration success it tests a master publication candidate, publishes
it by fast-forward, and leaves scheduling PAUSED. Clean publication inputs are
required; the ignored `.goose/out/` directory is reserved for local reports.

`20260913-cordis-lifecycle-pilot.json` assigns the existing Cordis owner the
necessary boot/harness/CLI/HMR/diagnostics consumers and their test write sets.
Acceptance is in `cordis-lifecycle-contract.md`; this does not waive full Cordis
parity or turn downstream feature completeness into a prerequisite of the core.

Text conflicts, changed consumed contracts and integration regressions enter
`INTEGRATION_REPAIR`, retaining both heads and prior review. One integrator owns
the combined candidate. Shared-contract disputes go to judge before implementation;
`integrate` uses the configured migrator model and `integration_review` uses the
reviewer model. The latter reuses unaffected evidence and expands review when
affected contracts expand. Full tests still gate every integrated combination.
The original source worker is not sent back through the entire migration audit.

Use the project launcher to schedule the entire pinned reference, rather than
manually selecting one migration unit:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action run -Jobs 3
```

### Pausing and resuming

Pause a running scheduler without force-closing it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action pause
```

The scheduler stops claiming new groups, parks running groups as READY (their
round, worktree and logs are preserved) and exits with code 0. Ctrl+C parks the
same way. Rerunning `-Action run` resumes from the saved phases. If a controller
was killed hard, the next startup automatically reclaims every RUNNING or
FAILED_INFRA task whose owner PID is dead (`recover_stale`), and
`-Action recover` without `-Task` reclaims all of them on demand, so no manual
per-task recovery is required after an interruption.

The first run discovers package and peer dependencies, calls the architecture
agent to refine runtime services/events, acceptance contracts and core-first
priorities, then starts ready task groups. Later runs reuse the SQLite graph.
The default is two concurrent groups; `-Jobs` selects resource concurrency, not
a work quota. There are no default round, action or model-work time limits.
The architect uses the existing judge provider/model configuration; migration,
review and arbitration retain their existing role configurations.
Plans rejected by graph validation return to the same architect session for
correction, without a retry quota. Missing contract definitions are reported
together with their referring tasks. Proposals and repair status are retained in
`architecture-*.proposal.json` and `architecture-status.json`. Restarting `run`
or `plan` resumes unfinished planning, including accepted output saved by the
earlier controller, rather than discarding the completed architecture analysis.

```powershell
# Discovery/status only: no model calls or source edits.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action init
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action status
# Explicitly refine the plan again, or apply a source-backed incremental plan.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action plan
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action apply -PlanFile plan.json
# Resume an interrupted/failed group after stopping the previous controller.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action recover -Task core/session
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action run -Jobs 3
```

Progress is in `.goose/runs/project/index.html` (open in a browser, refreshes every
10 seconds), `status.json`, and `state.sqlite3`. The dashboard shows task state,
current phase, latest activity, dependency blockers, rounds, commits and log paths.
Console messages identify each task group. Integrated/discovered counts describe
the current graph; new dependency discovery can increase the total.

The controller persists four edge kinds: implementation, contract, acceptance and
change. Cyclic dependencies form one atomic task group. Ready groups are ordered
by architectural wave, downstream impact, priority and age. Providers must be
integrated before external consumers run. Contract fingerprints and evidence are
bound to the pinned upstream, implementation revision, tests and environment.
Changes to known contract paths invalidate affected providers and transitive
consumers, including changes made by another module's worker. Empty path mappings
are discovery placeholders; the architect/workers must refine them from source.

Each group uses a dedicated Git worktree under `.goose/runs/project/worktrees/`.
Worktree creation initializes the `reference` submodule from the main checkout's
local module store (`git -c submodule.reference.url=...`), so no network access to
the upstream remote is required; a worktree left without its submodule heals in
place on the next run. Repositories must have run `git submodule update --init`
once in the main checkout before scheduling.
Targeted tests and Python 3.8 compile checks produce local `(unreviewed)` checkpoint
commits before a fresh blind review. Agents can follow and modify relevant
cross-module source in their own worktree; there is no directory read allowlist.
Missing providers and interface changes can produce a structured `work_plan`.
The controller saves these proposals and applies them between active waves, so a
running peer's acceptance scope cannot silently change. Invalid plans go back to
the proposer with validation errors. Identical plans are not repeatedly applied.

Integration is serial, on a dedicated `codex/parity-integration-*` branch and
worktree at `.goose/runs/project/integration/`. Candidates are retained under
`candidates/`. A changed relevant contract or conflicting baseline requires fresh
review on the combined code. Unrelated baseline changes retain the source review
but still run the combined full suite. Conflict handoffs preserve both branches,
conflict markers, source/base commits, acceptance contracts and prior reports;
full-suite failures return the combined candidate and failure log to the migrator.
Only independently reviewed changes passing `python -m pytest tests` enter the
integration branch. The launcher does not move the user's checkout or push.
It starts from committed project code; commit intended project edits before the
first run. The initial baseline is frozen when execution starts.

### Coordination and publication (2026-09-13)

The current project was paused before applying `plans/20260913-rebalance.json`.
The pre-change SQLite backup and status snapshot are in
`runs/project/backup-orchestration-20260913-142514/`. No worker restarts on plan apply.
The plan preserves all acceptance requirements, splits served-Web/resolver mechanisms
from product acceptance, and makes Schemastery adopt the integrated deep-equal contract.
Historical shared worktrees are retained and forked at dispatch, never reset or discarded.

Task specs can declare `write_paths` (repository-relative files/directories). The scheduler
reserves these plus provided-contract paths and observed cross-module changes. Overlap
serializes writers even when contract IDs differ. This is coordination, not a directory
permission boundary: workers may modify both ends of an interface. Before changing an
active peer's contract, propose ownership/dependency changes in `work_plan` and hand off
at the checkpoint. Unexpected overlapping writes are retained but wait before review.
Undeclared writes cannot be prevented by this advisory model; they are detected at phase
completion. No claim is made that worktree isolation is a filesystem sandbox.

Cycles no longer silently become giant workers. They appear in `unresolved_cycles` and
wait for a corrected plan. Only an explicit shared `atomic_group` authorizes an atomic
multi-task writer. Acceptance edges remain real gates: put them on the product acceptance
task, not backwards on its providers. Contract-only registration does not certify behavior.
Unrelated work continues while a graph proposal waits for the affected owner to finish.

Phase instructions and feedback are JSON data in `NN-phase.context.json`, outside the
Goose recipe template. This preserves literal fixture tokens such as `{{cwd}}`. Reviewer
context remains neutral. Judge decisions use `verdict`; old unambiguous textual verdicts
remain readable. Issue states distinguish open blockers, resolved items, informational
findings and deferred work; deferred work must retain a responsible acceptance task.

Publication is explicit and requires the scheduler to be stopped:

```powershell
.goose/run-project.ps1 -Action prepare-main -Target master
.goose/run-project.ps1 -Action publish-main
```

`prepare-main` merges integration into a new candidate based on the latest local target,
retains conflicts for repair, and runs the full suite. It never changes master.
`publish-main` requires the exact tested candidate, unchanged target/integration heads and
clean worktrees; it fast-forwards both master and integration. It does not push. Source
review evidence is retained separately from combined-test evidence in the event history.
Commit intended controller changes before preparing; do not publish an untested baseline.

Resume only when desired with `.goose/run-project.ps1 -Action run -Jobs 3`. After a pause,
READY means parked/eligible for dependency evaluation, not actively running. The dashboard
shows scheduler state, writer waits, unresolved cycles and publication state separately.

Recovery retains worktrees/checkpoints/logs. A completed result is reused only
when its recorded code/scope still match (and review HEAD is identical). An
unfinished or unbound phase runs fresh. A live scheduler PID prevents a second
controller or recovery command from taking ownership. Ctrl+C stops owned process
trees; a stale lock is reclaimed only after its PID is no longer running. Windows
Job Objects also terminate assigned descendants if the controller crashes.
Historical single-unit runs are not automatically imported as project evidence.

`FAILED_INFRA` and `NEEDS_ARBITRATION` retain the exact error/evidence and stop
only that group. Other ready groups continue. An explicitly approved atomic group with
multiple clean saved worktrees combines their commits; if a separate old tree
contains unfinished uncommitted edits, consolidation stops visibly with that path
instead of dropping those edits. Resolve/checkpoint those edits, then recover the
group. `PROJECT COMPLETE` means all discovered tasks are integrated; it does not
claim a Windows 7 VM or a portable release was exercised by this controller.

The schema for incremental plans is in `project_runner.py` (`TASK_SCHEMA` and
`CONTRACT_SCHEMA`); `.goose/runs/project/seed-plan.json` is an editable example.
Definitions are validated transactionally. Every dependency/contract needs source
evidence; current reports and architecture suggestions are not instructions to
weaken upstream acceptance.

Validation on 2026-09-12: 41 Goose controller/launcher/project tests passed,
including a real-process fake-Goose parallel run with real Git worktrees, targeted
and integration pytest, conflicts, plan updates, result recovery and checkpoints.
Replaying the observed stalled review recognized its accepted MUST_FIX result
(four issues) and complete event. Full `pytest tests`: 1609 passed, three existing
failures (two Windows short/long TEMP path comparisons and the old portable
distribution rejecting `--profile`). Live model-driven whole-project convergence
and execution on a Windows 7 machine have not been verified by these tests.

## Single-unit compatibility

`run-parity.ps1` uses a Python 3.8 controller to run the three specialist agents
in separate Goose sessions. Python owns phase transitions, continuing correction,
verification, visible progress, and checkpoint commits. By default it continues until correct, without workflow quotas. It loads agent instructions
from `.agents/agents/` and provider/model defaults from `recipes/parity-unit.yaml`.
A coordinator model can no longer silently invent narrow another worker's read scope.

## Run

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-parity.ps1 -MigrationUnit core/session
```

To include **existing migration edits** in verified checkpoints:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-parity.ps1 -MigrationUnit core/session -AdoptExisting
```

`-AdoptExisting` authorizes inclusion of prior edits only for files the migrator
explicitly lists as verified migration work. It does not stage the whole repository.
Without it, overlapping pre-existing edits cause the checkpoint to be skipped with
an explanation, while work can continue. Existing staged changes always prevent an
automatic checkpoint. No reset, cleanup or automatic rollback is performed.

Useful options:

| Option | Default | Effect |
| --- | --- | --- |
| `-MaxRounds` | 0 | Unlimited; a positive value is an optional user-selected cap |
| `-MaxTurns` | 0 | No workflow cap; automatically resume Goose native action-limit stops |
| `-PhaseTimeoutSeconds` | 0 | No timeout; positive values opt into a wall-time cap |
| `-NoCommit` | off | Keep all migration edits uncommitted |
| `-AdoptExisting` | off | Include verified prior migration edits as described above |
| `-GooseExe` | PATH, then local desktop install | Override CLI location; `GOOSE_EXE` also works |
| `-PythonExe` | `.venv/Scripts/python.exe` | Must be Python 3.8 for runtime checks |
| `-Smoke` | off | Original read-only named-agent delegation/credential smoke test |

The wrapper normalizes a Markdown-formatted `OPENAI_BASE_URL` in the child
process environment and restores the original afterward. Do not add `--no-profile`
to phase recipe calls: Goose 1.50.0 suppresses their extensions with that flag.

## What you will see

Each console entry includes a timestamp, phase and round. Output includes:

- role/provider/model at phase start;
- the agent's public text as it arrives and a concise tool description;
- a heartbeat recorded every 15 seconds, with elapsed time and time since last output;
- structured verdict, dependency expansions, open issue count and coverage flag;
- targeted/full-test command results;
- checkpoint hash, or the explicit reason a checkpoint was skipped;
- a final status and artifact directory, including failures and interruptions.

The heartbeat indicates liveness of the controller, not proof that the model is
making progress. It deliberately does not invent a percentage-complete estimate.
Provider-returned thinking is retained and available in the console/follow view.
Unavailable or redacted reasoning is not reconstructed.

Each run has its own ignored `.goose/runs/<timestamp-id>/` directory:

| Artifact | Contents |
| --- | --- |
| `status.json` | Latest phase, round, verdict, open issues, commits and stop reason |
| `progress.jsonl` | Timestamped user-visible activity |
| `NN-role.events.jsonl` | Full received Goose stream; retries archive the preceding file |
| `NN-role.result.json` | Parsed result for that exact phase |
| `NN-role.yaml` | Exact generated phase recipe |
| `NN-targeted.log`, `NN-full-suite.log` | Verification output |

For example, in another terminal:

```powershell
Get-Content .goose/runs/<run-id>/progress.jsonl -Tail 20 -Wait
Get-Content .goose/runs/<run-id>/status.json -Encoding UTF8
```

Only one controller may operate this checkout at a time. `active.lock` stores its
PID. After a hard process kill, verify the PID is no longer running before removing
that stale lock. Ctrl+C normally stops the child process tree, records INTERRUPTED,
and releases the lock. A non-COMPLETE result exits nonzero; an ordinary greeting,
truncated result, or Goose exit code 0 alone cannot be treated as success.

## Dependency scope

The unit is a semantic goal, **not a directory allowlist**. Every role may follow
relevant imports, callers, Cordis dispatch/lifecycle, typert services, generators
and tests across the repository. There are no per-file read quotas or fixed line
ranges. Migration fixes belong in the canonical owning plugin/service, even when
that owner is outside the unit's directory.

A missing subsystem is real missing work. Do not disguise it with an artificial
bridge, stub, duplicated service, skipped test, or platform exclusion. Record why
each dependency is needed; split large dependencies into coherent testable chunks.
Read access to dependencies is separate from review write policy: reviewers and
judges still must not mutate source. The controller detects worktree/HEAD/index
changes after phases and stops on violations; this is **not an OS sandbox**.
Existing changes are preserved for inspection, never automatically discarded.

Blind reviews use a fresh process/session with the role contract and unit only.
They receive no migration report, previous findings, test pass counts or judge
conclusions. Migration correction sessions receive the preceding structured
results; arbitration receives disputed evidence. Reviewers must not consult
`.goose/out/`, `.goose/runs/`, or historical review reports.

Case-by-case mapping requires upstream titles, Python test locations and explicit
classification. Matching counts is insufficient. A root-level regression test may
be a valid port if its assertions match: its directory alone is not grounds to
reject it or to call it equivalent.

## State and commits

Each round runs MIGRATE -> targeted pytest / compileall -> checkpoint when eligible
-> fresh REVIEW. Corrections continue until independent review and the full suite
pass. There is no default round limit, action quota, timeout or repeat-tool cutoff.
Goose's own action-limit message automatically resumes the same session with tools
and context intact. The controller does not switch to a report-only/no-tools mode.

Repeated findings trigger arbitration to help change approach, not an automatic
STALLED exit. Arbitration is not limited to one invocation. A failed full suite is
fed back to the migrator for correction rather than automatically terminating.
True infrastructure errors, user interruption, or a judge's unresolved BLOCKED
verdict are still reported honestly. COMPLETE still requires actual verification.
Optional positive limits remain available only when the user explicitly supplies
those flags. Zero means unlimited.

After a coherent chunk passes targeted tests and Python 3.8 compile checks, an
eligible checkpoint is committed with `(unreviewed)` in its message. This saves
progress before another lengthy review, but **does not claim parity completeness**.
No pushes are made. Checkpoints are restricted to observed migration changes (plus
explicitly adopted prior files); unrelated dirty/staged work is never swept in.
The full `pytest tests` gate runs after independent PASS. Failures are returned for
correction; they are never relabeled as a pass.

A new invocation starts a new run and inspects the current worktree. Native Goose action-limit stops within a running phase resume automatically. A
new launcher invocation does not automatically adopt an old interrupted session. Prior commits
and logs remain available; fresh blind reviewers must still ignore old conclusions.

Direct `goose run --recipe .goose/recipes/parity-unit.yaml` remains the legacy
model-coordinated path. It does not provide the Python controller's automatic continuation,
checkpoint policy or durable progress display. Use the PowerShell launcher.

## Verified model setup (2026-09-11, Goose 1.50.0)

| Role | Provider | Model | Context |
| --- | --- | --- | --- |
| Architect | `custom_deepseek` | `deepseek-flash` | 1,000,000 in local provider JSON |
| Migrator | `custom_deepseek` | `deepseek-flash` | 1,000,000 in local provider JSON |
| Reviewer | `openai` | `gpt-5.6-luna` | 1,050,000 in Goose's built-in catalog |
| Judge | `custom_openai_sol` | `gpt-5.6-sol` | 272,000 in local provider JSON |

All four controller roles now use `.goose/agent-config.json`, editable in the local
console. The table above is a historical configuration snapshot; recipe defaults
and agent markdown frontmatter do not override the controller allocation.
`gpt-5.6-sol` context is declared per model in
the local `custom_providers/custom_openai_sol.json` (`context_limit: 272000`),
because the global `GOOSE_CONTEXT_LIMIT` would apply to every model in the process.

Local `%APPDATA%/Block/goose/config/config.yaml` uses an operational output budget
of `GOOSE_MAX_TOKENS: 16384`, auto-compaction threshold `0.7`, the configured HTTPS
OpenAI proxy and existing thinking effort `high`. Provider timeouts are 600 seconds.
Context metadata is not a long-context stress test of the proxy. `GOOSE_INPUT_LIMIT`
is primarily Ollama's `num_ctx`, not a generic input-budget field. Avoid overriding
all three models with a single global context limit.

The local custom DeepSeek provider reads `CUSTOM_DEEPSEEK_API_KEY`; the upstream
built-in definition may instead read `DEEPSEEK_API_KEY`. Check `api_key_env` locally.
Credentials and local provider configuration remain outside Git. The earlier
configuration backup is `backup-parity-20260911-194837/` beside `config.yaml`.
Restart Goose Desktop after changing disk configuration.

References: [Goose CLI streaming](https://goose-docs.ai/docs/guides/goose-cli-commands/),
[recipe schemas](https://goose-docs.ai/docs/guides/recipes/recipe-reference/),
[configuration variables](https://goose-docs.ai/docs/guides/environment-variables/).

See [the core/session run diagnosis](diagnosis-core-session.md) for the observed
old-loop failures and verification limits of this change.
