# Upstream Plugin Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the upstream `dsh-base`, `dsh-web-app`, headless, and agent-preset compositions to Python 3.8.10 with one implementation agent per upstream plugin entry.

**Architecture:** The source of truth is upstream commit `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. Preserve the upstream host-plane versus per-session agent-preset ownership boundary and patch order; do not preserve Python classes that merge independent upstream services merely for convenience. Browser-only packages remain original compiled client modules, while every host half is ported.

**Tech Stack:** Python 3.8.10, asyncio, pytest, original React client packages and Web build.

---

### Task 1: Composition and Configuration Chain

**Files:**
- Modify: `dsh/harness.py`
- Modify: `apps/cli/main.py`
- Modify: `dsh/cordis/loader.py`
- Create: `tests/test_profile_boot_parity.py`

- [ ] Add failing tests for bundle → profile `cordis.patch.yml` → `$DSH_HOME/cordis.patch.yml` → repeated `--patch` → telemetry-disable ordering.
- [ ] Add failing tests proving Web mounts host rows once and mounts selected agent presets per session, while headless mounts the direct runner plane.
- [ ] Translate `apps/cli/src/profile-boot.ts`, `packages/boot/app-boot`, and bundle patch composition without manual pre-mount duplication.
- [ ] Verify CLI and Web resolve the same launch environment, settings file, credentials, model routes, and preset roots.

### Task 2: P0 Base Service Plugins

**Files:**
- Modify/Create: the matching `dsh` module and one focused test module per upstream plugin row.

- [ ] Dispatch one implementation agent each for `dsh-llm`, `dsh-session`, `dsh-user-questions`, `dsh-agent-default-model`, `dsh-attachment-local`, `dsh-session-projection`, `dsh-subprocess-local`, `dsh-sandbox-local`, `dsh-sandbox-policy`, `dsh-pwsh-sandbox`, `dsh-system-prompt`, `dsh-fs-sandbox`, `dsh-storage-json`, and `dsh-storage-domain`.
- [ ] For each plugin, first run its new focused test red, translate only its upstream package, then run focused and dependent tests green.
- [ ] Keep `bash-sandbox` and `tool-bash` as explicit Windows platform-disabled rows; do not invent Windows equivalents.

### Task 3: P0 Web Host Plugins

**Files:**
- Modify: `dsh/host/apiproxy/**`
- Modify: `dsh/host/client_modules/**`
- Modify/Create: matching host service modules
- Test: one focused test module per plugin plus `tests/test_web_profile_e2e.py`

- [ ] Dispatch one implementation agent each for `dsh-host-webserver`, `dsh-host-frontend-static`, `dsh-host-apiproxy`, the host half of `dsh-client-connection`, `dsh-client-modules`, `dsh-host-directory-picker-auto`, `dsh-host-plugin-inventory`, `dsh-api-gateway`, `dsh-agent-presets`, and `dsh-session-projection-cache`.
- [ ] Match all unary RPC request, success, and typed error schemas, including required `details` fields.
- [ ] Match `/api/respond` `client-response` carrier validation and never infer approval from malformed input.
- [ ] Match `/api/events/mux` and `/api/events/host` envelope, baseline, ordering, disconnect, and reconnection contracts.

### Task 4: P1 Split Merged Registries from Tools

**Files:**
- Modify/Create: `dsh/jobs/**`, `dsh/skill/**`, `dsh/subagent/**`, `dsh/workflow/**`
- Test: one focused test module per upstream plugin row.

- [ ] Dispatch separate agents for `dsh-jobs-local` and `dsh-tool-jobs`.
- [ ] Dispatch separate agents for `dsh-skill`, `dsh-skill-filesystem`, `dsh-skill-badge`, and `dsh-tool-skill`.
- [ ] Dispatch separate agents for `dsh-subagent`, spawn/fork providers, control, list-agents, report, spawn tool, and fork tool.
- [ ] Dispatch separate agents for `dsh-workflow-worker-thread`, `dsh-tool-workflow`, and `dsh-tool-ralph`.
- [ ] Prove unloading a tool never removes or strands its host registry and unloading a registry disposes all owned providers.

### Task 5: Remaining Base Plugins

**Files:**
- Modify/Create: matching `dsh` modules and focused tests.

- [ ] Dispatch one agent per upstream row for timer, HMR fallback, title/title-LLM, pi-ai, shell-env, fs-observation-policy, command-feedback, goal service/driver/command/tool, command-compact, spill store/policy, session checkpoint, session persistence, session query, session telemetry, tools, persona/system prompt compatibility, agent, agent loop, agent instructions, token meter, compaction, plan mode, todo, repeat reminder, timeout policy, web registry/search/tool, filesystem/tool/search/editor, terminal/pwsh tools, credentials, settings, workspace, approvals, permissions, commands, and LLM retry.
- [ ] Mark only unavailable OS capabilities as explicit Windows 7 trims and retain the upstream disabled-row behavior.

### Task 6: Remaining Web Domain Plugins

**Files:**
- Modify/Create: matching session, feedback, extension, startup, and runtime modules.

- [ ] Dispatch one agent each for message-feedback, session-log-download, session-reference, session-stats, cordis-host-runner, web-startup, web-runtime, code-runtime, and client-HMR fallback.
- [ ] Verify agent-preset list/select/read/copy/open/remove, shipped preset read-only protection, and session-specific preset mounts.
- [ ] Verify model providers/catalog/discovery, credentials writes, settings mutations, session model selection, workspace archive, session history wrappers, and cold-start no-route behavior.

### Task 7: Original Web Client Synchronization

**Files:**
- Replace from upstream: `apps/web/**`
- Replace from upstream: `packages/client/**`
- Rebuild: `apps/web/dist/**`
- Test: upstream Web unit/E2E suites plus Python-host E2E.

- [ ] Remove the legacy handwritten JS client source and synchronize the upstream TypeScript Web app and client package sources at the pinned commit.
- [ ] Build using the upstream workspace toolchain; do not hand-edit generated bundles.
- [ ] Run model settings, onboarding, agent preset authoring/selection, session lifecycle, question/approval, and fresh round-trip E2E against the Python host.

### Task 8: Final Verification

**Files:**
- Test only, except for defects exposed by verification.

- [ ] Run `.venv\Scripts\python.exe -m pytest tests` on Python 3.8.10 and require zero failures and no pending-agent tasks at shutdown.
- [ ] Run the original Web build and selected upstream browser E2E suites against the Python server.
- [ ] Build the portable release and smoke-test `dsh.bat` and `dsh-web.bat` with an empty DSH home and an existing layered configuration.
- [ ] Review the plugin matrix row by row and record every explicit Windows 7 trim with its upstream row and reason.
