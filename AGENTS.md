# AGENTS.md - Developer & Agent Guide for DeepSeek Harness Win7

This document outlines the codebase standards, architectural patterns, and development guidelines for AI agents and human contributors working on `deepseek-harness-win7`.

---

## 1. Project Mission & Target Environment

The goal of this repository is to maintain a lightweight, highly extensible **Windows 7 compatible** Python 3.8.10 implementation of the [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) driven by the **Cordis** architecture, providing a zero-dependency **Portable Release** for Windows desktop environments.

### Core Targets
1. **Windows 7 SP1 Compatibility**: Must run natively on Windows 7+ without requiring Python 3.9+ runtime dependencies or modern OS API patches.
2. **Cordis Architecture ("Everything is a Plugin")**: All system capabilities (LLM, tools, filesystem, terminal, sessions, agent loop) must be modular plugins mounted on a unified `Context`.
3. **Preset Support**: Must support Minimal Mode (极简模式) and Creative Mode (创造模式).
4. **Portable Packaging**: Must support single-folder zero-dependency portable deployment.

---

## 2. Cordis Architectural Guidelines

When adding features or fixing bugs, follow Cordis conventions:

### A. Context & Service Ownership
- Services are registered on `ctx` via `ctx.set_service("name", instance)`.
- Plugins access services dynamically (`ctx.get("tools")`, `ctx.get("fs")`, `ctx.get("llm")`).
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
- Every registration (event handler, tool definition, temporary file) must be reversible.
- Use `ctx.effect(disposer_fn)` or return cleanup functions so that unloading a plugin leaves no residual state.

### D. Typed Event Dispatching
Choose the correct event dispatch mode when introducing extension points:
- **`emit`**: Sync/async fire-and-forget notification (e.g., `turn/start`, `step/start`).
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

## 4. Preset Conventions

- **Minimal Mode (`dsh/presets/minimal.yaml`)**:
  - Persona: `You are a helpful software engineer assistant.`
  - Tools: `str_replace_editor` + persistent shell (`pwsh` on Windows, `bash` on POSIX).
  - No complex skill or compaction overhead.

- **Creative Mode (`dsh/presets/creative.yaml`)**:
  - Includes full tool suite plus `@deepseek-ai/dsh-cordis-manager`.
  - Exposes runtime Cordis tools: `cordis_list_plugins`, `cordis_inspect_context`, `cordis_unload_plugin`, `cordis_dump_config`.

---

## 5. Verification & Testing

Before declaring work complete, agents **MUST** execute the test suite:

```powershell
.venv\Scripts\python.exe -m pytest tests
```

Ensure all tests pass cleanly. When modifying tools or CLI flags, add corresponding pytest cases under `tests/`.

---

## 6. Portable Release Requirements

The portable release script (`scripts/build_portable.py`) creates a standalone distribution in `dist/dsh-win7-portable/` with an embedded Python 3.8 runtime and launcher scripts (`dsh.bat`). Ensure any new dependencies are added to `requirements.txt`.
