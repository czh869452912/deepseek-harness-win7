# Goose multi-model parity pipeline

This repository includes a Goose workflow for repeatedly migrating and independently reviewing one DeepSeek Harness parity unit at a time.

## Architecture

```text
Goose recipe coordinator (DeepSeek Flash by default)
    |
    +--> parity-migrator  -- DeepSeek Flash -- implementation + test porting
    |
    +--> parity-reviewer  -- GPT-5.6 Luna      -- fresh blind review
    |
    `--> parity-judge     -- GPT-5.6 Sol       -- only on ESCALATE / unresolved conflict
```

Project agents live in:

```text
.agents/agents/
```

The executable recipe lives in:

```text
.goose/recipes/parity-unit.yaml
```

Goose discovers project-local agents from `.agents/agents/` and project-local recipes from `.goose/recipes/`.

## Why this shape

The workflow deliberately separates implementation from verification:

1. Flash performs the migration and ports upstream tests.
2. Luna receives a fresh isolated subagent session and is not given Flash's reasoning or claimed fixes.
3. Flash gets concrete reviewer findings only if correction is required.
4. Sol is invoked only if either worker escalates or a concrete disagreement survives one correction cycle.
5. A green local pytest suite is not sufficient for COMPLETE; official upstream test mapping is also required.

The pinned `reference/` submodule remains the sole upstream authority.

## Goose requirements

Use a recent Goose version with:

- project-local agent discovery;
- the `summon` platform extension;
- `delegate(source=..., provider=..., model=...)` support;
- Recipe parameters and structured response support.

The current Goose implementation discovers project agents from `.agents/agents/`, creates delegated agents as independent sessions, and allows each delegate call to override provider, model, extensions, temperature, and max turns.

## Provider setup

Do not commit API keys to this repository.

The recipe defaults are:

| Role | Goose provider id | Model |
| --- | --- | --- |
| Coordinator | `custom_deepseek` | `deepseek-flash` |
| Migrator | `custom_deepseek` | `deepseek-flash` |
| Reviewer | `openai` | `gpt-5.6-luna` |
| Judge | `openai` | `gpt-5.6-sol` |

The verified local `custom_deepseek` provider uses `deepseek-flash` and reads `CUSTOM_DEEPSEEK_API_KEY` from Goose's credential store. The upstream built-in provider can instead use `DEEPSEEK_API_KEY`; inspect the local JSON's `api_key_env` rather than assuming they are interchangeable.

OpenAI uses `OPENAI_API_KEY` unless you configure another supported authentication path/provider.

If your installed Goose version exposes different provider or model identifiers, override the recipe parameters instead of editing the agents:

```powershell
goose run --recipe .goose/recipes/parity-unit.yaml `
  --params migration_unit=core/session `
  --params migrator_provider=custom_deepseek `
  --params migrator_model=deepseek-flash `
  --params reviewer_provider=openai `
  --params reviewer_model=gpt-5.6-luna `
  --params judge_provider=openai `
  --params judge_model=gpt-5.6-sol
```

On a POSIX shell, use ordinary line continuations instead of PowerShell backticks.

## Typical use

From the repository root (the wrapper also locates the installed CLI when it is not on PATH):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-parity.ps1 -Smoke
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-parity.ps1 -MigrationUnit core/session
```

For a different installation, pass `-GooseExe C:/path/to/goose.exe` or set `GOOSE_EXE`. The wrapper normalizes a Markdown-formatted `OPENAI_BASE_URL` for the child process and restores the original environment afterward. Do not add `--no-profile`: on the tested Goose 1.50.0 it suppresses recipe extensions as well. The recipe explicitly loads `summon`, `developer`, and `analyze`; delegate extension lists filter already-loaded extensions.

You may also provide a more explicit unit when the mapping is not obvious, for example:

```powershell
goose run --recipe .goose/recipes/parity-unit.yaml --params migration_unit="reference/packages/core/agent-loop <-> dsh/core/agent_loop.py <-> tests/1to1/core/agent-loop"
```

The recipe should finish with structured output containing:

- migration unit;
- `COMPLETE`, `INCOMPLETE`, or `BLOCKED`;
- reviewer verdict;
- whether the judge was invoked;
- remaining gaps;
- verification commands/results.

## Reasoning-effort limitation

The current Goose `delegate` schema exposes per-delegate provider/model/temperature/max-turn overrides, but not a generic per-delegate `reasoning_effort` field.

Therefore this repository fixes the model routing in Goose but does **not** pretend to enforce `Flash=max`, `Luna=high`, or `Sol=high` through Recipe YAML. Configure reasoning/thinking behavior through the selected provider's supported Goose/provider configuration when available. Model routing and escalation policy remain deterministic at the Recipe-contract level.

## Reviewer isolation and write safety

The blind reviewer is hard-isolated at the **session/context** level: Goose delegates run independently and do not share parent conversation history.

There is an important current limitation: Goose's built-in `developer` extension bundles inspection, shell, and edit capabilities together. The reviewer agent therefore has a strict no-mutation contract, but this is not a filesystem-level read-only sandbox.

If hard write isolation is required, add a dedicated read-only filesystem/search MCP extension and change the reviewer/judge delegate calls to use only that extension (plus `analyze`) instead of `developer`.

Until then, any reviewer-caused worktree mutation invalidates the review. Restore the worktree and rerun a fresh blind review.

## Validation expectations

The migrator must follow repository policy and, before COMPLETE, run the appropriate unit/regression checks plus the full suite:

```powershell
.venv\Scripts\python.exe -m pytest tests
```

It must also perform Python 3.8 `compileall` validation for changed Python code.

The workflow must not weaken or rewrite tests merely to make the current port pass.

## Files

```text
.agents/agents/parity-migrator.md
.agents/agents/parity-reviewer.md
.agents/agents/parity-judge.md
.goose/recipes/parity-unit.yaml
.goose/README.md
```

## Verified local setup (2026-09-11, Goose 1.50.0)

Local configuration is in `%APPDATA%/Block/goose/config/`, outside the repository.
Existing config and both DeepSeek provider JSON files were backed up in
`backup-parity-20260911-194837/` before modification. API keys were not changed.
Restart the desktop app to reload disk configuration; use the wrapper for CLI runs
from terminals that still carry the malformed environment URL.

| Setting | Effective configuration | Meaning |
| --- | --- | --- |
| DeepSeek context | `context_limit: 1000000` in both local DeepSeek provider JSONs | Replaces null / fallback metadata |
| Luna / Sol context | 1,050,000 in Goose's built-in OpenAI model catalog | Already defined; no global context override needed |
| Single-response output | `GOOSE_MAX_TOKENS: 16384` | Operational budget, not the model's maximum capability |
| Automatic compaction | `GOOSE_AUTO_COMPACT_THRESHOLD: 0.7` | Start compacting at 70% of context |
| Request timeout | DeepSeek `timeout_seconds: 600`; OpenAI `OPENAI_TIMEOUT: "600"` | Allow longer inference |
| OpenAI routing | Plain HTTPS `OPENAI_BASE_URL`, matching `OPENAI_HOST` and `OPENAI_BASE_PATH` | Use the configured proxy, not the official default host |
| Thinking | Existing `GOOSE_THINKING_EFFORT: high` retained | Not a per-role max/high guarantee |
| Turn budgets | Coordinator 40; migrator 60; reviewer 45; judge 35 | Every follow-up must repeat its role routing and budget |

Context includes instructions, history, tool definitions/results and generated
output; it is not a separate promise that a full context window of input plus
another full output budget will fit. `GOOSE_INPUT_LIMIT` is for Ollama's `num_ctx`,
not a generic OpenAI-compatible input-token field. Avoid a global
`GOOSE_CONTEXT_LIMIT` override when different models have different windows.
The proxy's `/models` response confirms Luna/Sol names but does not publish its
own context caps. The catalog values above are not a long-context stress test of
the proxy. Lower the operational context if the proxy imposes a smaller limit.

Sources: [Goose configuration variables](https://goose-docs.ai/docs/guides/environment-variables/),
[Goose OpenAI model catalog](https://github.com/aaif-goose/goose/blob/main/crates/goose-providers/src/openai.rs),
[DeepSeek context documentation](https://api-docs.deepseek.com/quick_start/pricing/).

The live smoke session `20260911_9` returned `SMOKE_PASS`. Its three independent
child sessions (`20260911_10`, `20260911_11`, `20260911_12`) used Flash, Luna and Sol
respectively, executed the permitted read-only AGENTS.md command, and confirmed
analyze tools. Their saved model configs confirm the 16,384-token output budget.
This verifies routing, credentials and tool execution, not completion of a real
migration unit. The production recipe's correction and arbitration decisions
remain model-followed instructions rather than a programmatically enforced state
machine.

Validation: launcher regression tests: **4 passed**; Python 3.8 compile check and
both recipe validators passed. Full `pytest tests` run: **1479 passed, 3 failed**
(before the final two launcher verdict cases were added and passed separately).
The same three failures were present before the Goose edits:

- `test_hmr_config.py::test_normalizes_refresh_failures_and_broadcasts_them_without_escaping_watcher`
- `test_user_patches.py::test_watches_add_failure_recovery_and_removal_through_transactional_hmr`
- `test_portable_smoke.py::test_smoke_dist_portable_directory`

The first two compare Windows short and long temporary paths (`ADMINI~1` versus
`Administrator`); the portable smoke launches an existing `dist` entrypoint that
rejects `--profile minimal`. These remain unresolved and will prevent the real
migration recipe's full-test completion gate from passing until addressed.
