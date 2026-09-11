# Goose multi-model parity pipeline

This repository includes a Goose workflow for repeatedly migrating and independently reviewing one DeepSeek Harness parity unit at a time.

## Architecture

```text
Goose recipe coordinator (DeepSeek V4 Flash by default)
    |
    +--> parity-migrator  -- DeepSeek V4 Flash -- implementation + test porting
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
| Coordinator | `custom_deepseek` | `deepseek-v4-flash` |
| Migrator | `custom_deepseek` | `deepseek-v4-flash` |
| Reviewer | `openai` | `gpt-5.6-luna` |
| Judge | `openai` | `gpt-5.6-sol` |

Goose's current built-in DeepSeek declarative provider uses the id `custom_deepseek`, reads `DEEPSEEK_API_KEY`, and includes `deepseek-v4-flash` in its model catalog.

OpenAI uses `OPENAI_API_KEY` unless you configure another supported authentication path/provider.

If your installed Goose version exposes different provider or model identifiers, override the recipe parameters instead of editing the agents:

```powershell
goose run --recipe .goose/recipes/parity-unit.yaml `
  --params migration_unit=core/session `
  --params migrator_provider=custom_deepseek `
  --params migrator_model=deepseek-v4-flash `
  --params reviewer_provider=openai `
  --params reviewer_model=gpt-5.6-luna `
  --params judge_provider=openai `
  --params judge_model=gpt-5.6-sol
```

On a POSIX shell, use ordinary line continuations instead of PowerShell backticks.

## Typical use

From the repository root:

```powershell
goose run --recipe .goose/recipes/parity-unit.yaml --params migration_unit=core/session
```

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
