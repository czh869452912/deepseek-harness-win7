# Cordis Runtime Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the upstream Cordis runtime and loader semantics to Python 3.8.10 so upstream plugins can be ported without compensating designs.

**Architecture:** Preserve the upstream file boundaries and state machine: Context owns scope, Registry owns plugin scheduling, Fiber owns lifecycle/effects, Reflect owns services and dependency notifications, Events owns scoped dispatch, and Loader owns the mutable composition tree. Python-only compatibility wrappers may remain only when they delegate to the translated behavior.

**Tech Stack:** Python 3.8.10, asyncio, pytest; source of truth is `reference/deepseek-harness/vendor/cordis/src` and `reference/deepseek-harness/vendor/loader/src`.

---

### Task 1: Event Dispatch Contract

**Files:**
- Modify: `dsh/cordis/events.py`
- Test: `tests/test_cordis_events_upstream_parity.py`

- [ ] Add focused tests for upstream `emit`, `parallel`, `serial`, `waterfall`, listener priority, `once`, bail values, scope filtering, and `internal/update` fiber-local hooks.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_cordis_events_upstream_parity.py -v` and confirm failures identify the existing transformed-data waterfall and swallowed `emit` exceptions.
- [ ] Translate `vendor/cordis/src/events.ts` dispatch composition exactly: waterfall listeners receive original arguments plus the nested `next`, and omission of `next()` vetoes the chain.
- [ ] Re-run the focused tests and existing `tests/test_cordis.py tests/test_cordis_1to1_parity.py`.

### Task 2: Fiber and Effect Lifecycle

**Files:**
- Create: `dsh/cordis/utils.py`
- Modify: `dsh/cordis/fiber.py`
- Modify: `dsh/cordis/plugin.py`
- Test: `tests/test_cordis_fiber_upstream_parity.py`

- [ ] Add tests for function/class/object plugins, `(ctx, config)` invocation, sync/async/iterable setup results, reverse disposer collection, failed-load rollback, parent-child disposal, reload inertia, and awaitable completion.
- [ ] Run the focused test and confirm each new behavior fails for the expected missing lifecycle reason.
- [ ] Translate the upstream runner/effect/disposable-list semantics; remove name-based setup/disposer guessing and treat only setup return values as disposers.
- [ ] Re-run focused and Cordis lifecycle tests.

### Task 3: Reflect, Service Ownership, and Dynamic Injection

**Files:**
- Modify: `dsh/cordis/reflect.py`
- Modify: `dsh/cordis/service.py`
- Modify: `dsh/cordis/registry.py`
- Modify: `dsh/cordis/context.py`
- Modify: `dsh/cordis/utils.py`
- Test: `tests/test_cordis_injection_upstream_parity.py`

- [ ] Add tests proving duplicate provide rejection, same-fiber `set`, provider-owned cleanup, declared-inject access, provider replacement/removal reload, inject-map interception/check predicates, epoch changes, caller-bound traceable services, and isolation filters.
- [ ] Run the focused test and confirm failures expose root-owned services and static dependency activation.
- [ ] Translate `reflect.ts`, `service.ts`, `registry.ts`, and traceable utilities without flattening inject maps to lists.
- [ ] Re-run focused tests and `tests/test_context_injections.py tests/test_cordis_scheduling.py`.

### Task 4: Context Scope and Public Runtime Surface

**Files:**
- Modify: `dsh/cordis/context.py`
- Modify: `dsh/cordis/registry.py`
- Modify: `dsh/cordis/reflect.py`
- Modify: `dsh/cordis/__init__.py`
- Test: `tests/test_cordis_context_upstream_parity.py`

- [ ] Add tests for prototype-like scope inheritance, late ancestor intercept visibility, registry map iteration, internal event argument order, async unload completion, and exported upstream symbols.
- [ ] Verify the tests fail against copy-based scope inheritance and fire-and-forget unload.
- [ ] Translate the Context and public map/export surfaces, retaining Python aliases only as compatibility shims.
- [ ] Re-run focused and existing Cordis tests.

### Task 5: Composition Loader and Entry Tree

**Files:**
- Modify: `dsh/cordis/loader.py`
- Create: `dsh/cordis/loader_entry.py`
- Create: `dsh/cordis/loader_tree.py`
- Create: `dsh/cordis/loader_group.py`
- Create: `dsh/cordis/loader_isolate.py`
- Test: `tests/test_cordis_loader_upstream_parity.py`

- [ ] Add tests for module resolution, unknown-plugin fail-loud behavior, `!!js` evaluation in entry context, include/group/isolate realms, create/update/remove, rollback, persistence, injected entries, and service-gated activation independent of row order.
- [ ] Run the focused test and confirm failures against the current registry-map/list-recursion loader.
- [ ] Translate `vendor/loader/src/index.ts`, `internal.ts`, and `config/*` by source file responsibility, using Python import resolution and explicit Win7-compatible filesystem operations.
- [ ] Re-run focused loader tests plus preset and Cordis manager tests.

### Task 6: Runtime Integration Gate

**Files:**
- Modify: only files required by failing parity tests
- Test: `tests/test_cordis_*.py`

- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_cordis.py tests/test_cordis_1to1_parity.py tests/test_cordis_scheduling.py tests/test_context_injections.py tests/test_cordis_*_upstream_parity.py`.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests` and record pass/fail counts and lifecycle warnings.
- [ ] Compare each translated public symbol and behavior against the upstream source checklist before beginning ordinary plugin ports.
