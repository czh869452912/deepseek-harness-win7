# Goose parity workflow

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
- a heartbeat every 15 seconds, with elapsed time and time since last output;
- structured verdict, dependency expansions, open issue count and coverage flag;
- targeted/full-test command results;
- checkpoint hash, or the explicit reason a checkpoint was skipped;
- a final status and artifact directory, including failures and interruptions.

The heartbeat indicates liveness of the controller, not proof that the model is
making progress. It deliberately does not invent a percentage-complete estimate.
Model-private thinking is not displayed or retained in the event transcript.

Each run has its own ignored `.goose/runs/<timestamp-id>/` directory:

| Artifact | Contents |
| --- | --- |
| `status.json` | Latest phase, round, verdict, open issues, commits and stop reason |
| `progress.jsonl` | Timestamped user-visible activity |
| `NN-role.events.jsonl` | Goose stream events (thinking blocks excluded) |
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
| Migrator | `custom_deepseek` | `deepseek-flash` | 1,000,000 in local provider JSON |
| Reviewer | `openai` | `gpt-5.6-luna` | 1,050,000 in Goose's built-in catalog |
| Judge | `openai` | `gpt-5.6-sol` | 1,050,000 in Goose's built-in catalog |

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
