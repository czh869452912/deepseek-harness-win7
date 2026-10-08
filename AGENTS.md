# AGENTS.md - Developer & Agent Guide for DeepSeek Harness Win7

This document outlines the codebase standards, architectural patterns, and development guidelines for AI agents and human contributors working on `deepseek-harness-win7`.

---

## 1. Project Mission & Target Environment

The goal of this repository is to maintain a lightweight, highly extensible **Windows 7 compatible** Python 3.8.10 implementation of the [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) driven by the **Cordis** architecture, providing a zero-dependency **Portable Release** for Windows desktop environments.

### Core Targets
1. **Windows 7 SP1 Compatibility**: Must run natively on Windows 7+ without requiring Python 3.9+ runtime dependencies or modern OS API patches.
2. **Cordis Architecture ("Everything is a Plugin")**: All system capabilities (LLM, tools, filesystem, terminal, sessions, agent loop, Web GUI) must be modular plugins mounted on a unified `Context`.
3. **1:1 Official Web GUI (Cordis in Browser)**: Reuse the pinned upstream React 18 + TSX + CSS Modules frontend unchanged. Align the Python host with its Connection / Typert Remote protocol and `/api/remote.mux` WebSocket; `/plugins/events` is the client HMR SSE channel. The old dual business SSE streams and `/api/respond` bridge are not the target architecture. Derive client rows from the upstream bundle and active Loader entries, not a fixed plugin count.
4. **Preset Support**: Must support Minimal Mode (极简模式), Standard Mode (标准模式), and Creative Mode (创造模式).
5. **Portable Packaging**: Must support single-folder zero-dependency portable deployment (`dsh.bat` and `dsh-web.bat`).

---

## 2. Cordis Architectural Guidelines

When adding features or fixing bugs, follow Cordis conventions:

### A. Context & Service Ownership
- Services are registered on `ctx` via `ctx.set_service("name", instance)`.
- Plugins access services dynamically (`ctx.get("tools")`, `ctx.get("fs")`, `ctx.get("llm")`, `ctx.get("web_server")`, `ctx.get("client_modules")`).
- Avoid direct hardcoded package imports between plugins; communicate through service interfaces and event hooks.

### B. Dependency Injection (`inject`)
- Declare required services using the `inject` class field:
  ```python
  class MyPlugin(Plugin):
      id = "my-plugin"
      inject = ["tools", "fs"]
      def apply(self, ctx): ...
  ```

### C. Reversible Effects (`effect`)
- Every registration (event handler, tool definition, temporary file, HTTP route) must be reversible.
- Use `ctx.effect(disposer_fn)` or return cleanup functions so that unloading a plugin leaves no residual state.

### D. Typed Event Dispatching
Choose the correct event dispatch mode when introducing extension points:
- **`emit`**: Sync/async fire-and-forget notification (e.g., `turn/start`, `session/event`, `question/requested`).
- **`waterfall`**: Pipeline middleware pattern (`data, next_fn`) for prompt assembly, tool execution policy (`tools/pre-execute`), and request rewriting (`agent/pre-step`).
- **`parallel`**: Async concurrent fan-out (`asyncio.gather`).
- **`serial`**: Async sequential execution (e.g., `agent/turn-stopping`).

---

## 3. Python 3.8.10 & Windows 7 Compatibility Rules

To ensure strict Windows 7 and Python 3.8.10 compatibility:

1. **Python Syntax**:
   - **Do NOT** use Python 3.9+ built-in generics syntax (e.g., `list[str]`, `dict[str, Any]`). Use `typing.List[str]`, `typing.Dict[str, Any]`.
   - **Do NOT** use `str.removeprefix()` or `str.removesuffix()`.
   - **Do NOT** use `match ... case` statements (Python 3.10+).
   - Use standard `asyncio` constructs compatible with Python 3.8.

2. **Windows 7 System Compatibility**:
   - Use `powershell.exe` (PowerShell 2.0 / 5.1) with fallback to `cmd.exe`.
   - Always handle file paths with `os.path` or `pathlib.Path` using forward/backward slash normalization for Windows paths.
   - Use `encoding="utf-8"` explicitly for all file I/O operations.
   - Handle Windows terminal output encoding gracefully (`sys.stdout.reconfigure(encoding='utf-8')`).

3. **OpenAI & DeepSeek API Compatibility**:
   - Support OpenAI-compatible API endpoints using `base_url` and `api_key`.
   - Read defaults from environment variables (`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`).

---

## 4. Preset & Web GUI Conventions

- **Minimal Mode (`dsh/presets/minimal.yaml`)**:
  - Persona: `You are a helpful software engineer assistant.`
  - Tools: `str_replace_editor` + persistent shell (`pwsh` on Windows, `bash` on POSIX).
  - No complex skill or compaction overhead.

- **Standard Mode (`dsh/presets/standard.yaml`)**:
  - Full engineering toolset: `str_replace_editor`, `pwsh`, `fs_search`, `ask_user`, `todo`, `skill`, `compaction`, `plan_mode`, `goal`.

- **Creative Mode (`dsh/presets/creative.yaml`)**:
  - Includes full tool suite plus `@deepseek-ai/dsh-cordis-manager`.
  - Exposes runtime Cordis tools: `cordis_list_plugins`, `cordis_inspect_context`, `cordis_unload_plugin`, `cordis_dump_config`.

- **Web GUI Mode (`dsh-web.bat` / `dsh --profile web`)**:
  - Use the canonical Web profile and upstream bundle composition: Web runtime, WebServer, Connection, Typert Gateway, application Remote controllers, ClientModules, HMR and FrontendStatic.
  - Serve the original frontend from `apps/web/dist` and the bundles declared by active packages. Do not change browser code to accommodate an incompatible host API.
  - The legacy harness and mountable `ApiProxyPlugin` HTTP/dual-SSE carrier are retired; they are not fallbacks for missing canonical providers. Historical domain helpers still used by unit tests are not current Web parity evidence. See `docs/research/2026-10-02-web-transport-retirement-progress.md` and the earlier canonical Web records for implementation and remaining acceptance work.

### Canonical Profile CLI & Legacy Retirement
- Canonical launcher invocations use profile syntax:
  ```powershell
  dsh --profile <minimal|standard|creative|web|headless> [--patch <path>] [--dump-config]
  ```
- The canonical launcher is `apps/cli/main.py` → `parse_dsh_args` → `run_profile`. The legacy launcher flags (`--mode`, `-m`, `-p`, `--prompt`, `--web`) and interactive fallback are retired by explicit product decision. App arguments after the launcher prefix belong to the selected app; never inspect them to switch boot runtimes.
- Dual-track retirement: `dsh/cordis/profile.py` delegates all profile directory resolution, compose, heal, and manifest operations to canonical `dsh.boot.app_boot` / `dsh.boot.profile_boot`. `dsh/harness.py` and its flat `build_harness` entry are retired. Production and integration tests use `run_profile`; activation checks and telemetry privacy filtering belong to canonical boot.

---

## 5. Verification & Testing

### Continuous Migration Records

For upstream migration work, start with `migration/README.md` and the generated
`migration/status.md`. Use `scripts/migration.py check` and `ready` to inspect
the pinned target, dependencies, and current evidence. Task `expected_paths`
are advisory impact scope, not edit permissions: include necessary providers,
consumers, and regression tests in the same contract change. Coordinate active
writers before overlapping changes. Do not treat a task report, test filename,
or manifest inventory as proof of upstream parity. The current CLI does not
provide concurrent task claiming or automatic state transitions.

### Select Verification by Change Scope

Before declaring a development task complete, agents **MUST** execute verification
appropriate to the change. **Targeted verification is the default.** Select the
original failing cases, changed providers, direct consumers, and relevant
regressions; do not select tests solely by changed filenames. Documentation-only
changes normally need diff/link checks rather than pytest. When modifying tools
or CLI flags, add corresponding pytest cases under `tests/`.

State the selected verification scope and why it covers the change. Once it
passes, broaden or repeat it only for a new change, failure, or uncovered risk.
A local fix, task handoff, commit, merge, or push does **not** by itself require
the entire test collection or a Portable rebuild.

### Plan Complete Gates at Stable Milestones

Run a complete gate when a stable migration batch is ready for unified acceptance,
a cross-module architecture change is ready for overall sign-off, a Portable
release candidate is ready, or the user explicitly requests it. Before starting,
finish known fixes and targeted checks, prepare required dependencies/browser,
coordinate writers, and identify the frozen candidate and fresh output directory.

For unified migration/release qualification, use `scripts/verify_release.py`,
which already runs the complete Python collection, pinned Source configurations,
paired contracts, and actual extracted Portable/browser checks. Do not run
`pytest tests` immediately beforehand as a duplicate gate. A standalone full
Python regression may be planned when that is the actual objective, but does not
constitute release acceptance.

After a complete run fails, preserve its diagnostics, fix the identified problems,
and rerun their relevant cases/consumers. Do not automatically restart the full
gate after each individual fix. Schedule the next full run at the next stable
candidate qualification. Inspect existing timings and wait/deadline behavior
before diagnosing slow file operations as a hang. The total pytest budget is
optional (`--regression-timeout SECONDS`); individual operation deadlines remain.

Report targeted completion separately from full regression and release acceptance.
Targeted results cannot replace task acceptance requirements, promote migration
states that require missing evidence, or certify an untested commit/archive.
Reuse a complete receipt only for its exact qualified candidate, frozen inputs,
and archive; never combine partial runs into a new full acceptance claim.

### Keep Verification Outputs Bounded

Use a fresh owned output directory and the existing short pytest workspace
mechanism. Keep commands, scope, exit status, XML/logs, timings, and necessary
raw failure observations for meaningful runs. Do not overwrite unresolved failure
directories, build a Portable for every local fix, or archive every debug workspace
into migration/LFS evidence. Use existing retention rules for completed,
identified reconstructible fixtures/copies; preserve real observations, unresolved
failures, active/unknown files, formal receipts, and protected history backups.
Never bulk-delete `.goose/out` to recover space.

See [the verification guide](docs/testing.md) for the milestone matrix, examples,
artifact handling, and the distinction between this guidance and current CI.

---

## 6. Portable Release Requirements

The portable release script (`scripts/build_portable.py`) creates a standalone distribution in `dist/dsh-win7-portable/` and `dist/dsh-win7-portable-v0.1.0.zip` containing:
1. Embedded Python 3.8 dependencies (`lib/`).
2. Full `dsh/` framework and `dsh.py` entrypoint.
3. Compiled React 18 Web GUI (`apps/web/dist/`) and official client packages (`packages/client/`).
4. Dual launcher batch scripts: `dsh.bat` (CLI) and `dsh-web.bat` (Web GUI).
