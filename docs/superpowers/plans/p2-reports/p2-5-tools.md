# P2-5: Core Tools 1:1 Blind Audit & Discrepancy Report

**Audit Target**: `reference/packages/core/tools/` (TypeScript, 10 src files, 12 test specs) vs `dsh/core/tools.py`, `dsh/core/tool_calls.py`, `dsh/core/agent_tool_presentation.py`, and related files in `dsh/`.

---

## Executive Summary

| Dimension | TypeScript Reference (`@deepseek-ai/dsh-tools`) | Python Harness (`dsh/`) | Parity Status |
| :--- | :--- | :--- | :--- |
| **Source Volume** | 10 files, 5,662 LOC | 3 files, 926 LOC | **Critical Gaps (~84% missing)** |
| **Spec Tests** | 12 spec files, 8,261 LOC | 2 partial test files, 169 LOC | **Severe Deficit (~98% missing)** |
| **Schema Validation** | Custom stack-safe JSON Schema validator & DSL compiler | Arbitrary dict parameters, zero argument validation | **Missing** |
| **Output Contract** | Mandatory canonical JSON output schema + render + presentationMeta | Arbitrary handler return types, raw strings/dicts | **Missing** |
| **PTC (run_code)** | Full multi-language execution bridge, sub-call scheduler, session events | Stub presentation mode string only, no `run_code` | **Missing** |
| **PTC Codegen** | Full Python (`py-types.ts`) & TS (`ts-types.ts`) SDK generator | None | **Missing** |
| **Scoping & Guards** | Scoped layers, `restrict()`, `guard()`, scoped `presentAs()` | Flat dictionary, no scoping, no restriction/guards | **Missing** |
| **Pipeline Waterfalls** | `pre-execute`, `execute` (around), `post-execute`, `ptc-dispatch-log`, `result`, `change` | `pre-execute` (simplified), `post-execute` (simplified) | **Major Architecture Gaps** |
| **Cancellation** | Signal fusing (`fuseToolSignals`), `TOOL_ABORTED` vs `BEFORE_DISPATCH` | Ad-hoc `TOOL_ABORTED_BEFORE_DISPATCH` in scheduler | **Partial** |
| **Presentation Intent** | Typed tagged unions (`Generic`, `Terminal`, `Diff`, `Search`, `Read`, `Web`) | None (untyped callbacks) | **Missing** |
| **Package Invariants** | Monotonic pipeline stage tracking & frozen snapshot validation | None | **Missing** |

---

## Detailed Itemized Discrepancy Report

### Category 1: Schema DSL, Enforced Subset & Validation (`src/schema.ts`, `src/json-schema.ts`)

#### [D1] Missing Enforced JSON Schema Subset Validator
- **TS Reference**: `reference/packages/core/tools/src/json-schema.ts:1-657`
- **TS Details**:
  - Defines the enforced JSON Schema subset (`JsonSchemaNode`, `ObjectJsonSchema`).
  - Implements stack-safe recursive-descent validator (`checkSchemaNode`, `checkValue`) with explicit frame queues (`ValueFrame`, `SchemaWalkTask`).
  - Implements `assertSupportedJsonSchema(schema)` and `assertObjectJsonSchema(schema)` which reject invalid/misplaced keywords (e.g. `anyOf`, `allOf`, `not`, `$ref`, `pattern`, `minimum`, `items` on object, misplaced `enum`/`const`).
  - Implements `validateJsonSchemaValue(schema, value, path)` which validates data against schema, enforcing exact types, scalar matches, `oneOf` (exact one match), `additionalProperties: false`, and lossless numbers (no `-0`, finite).
  - Defines `JsonSchemaError` extending `HarnessError` with code `UNSUPPORTED_SCHEMA` and `violations: string[]`.
- **Python Status**: `dsh/core/tools.py` has **no** JSON schema validator, no keyword whitelist/blacklist, no `assertSupportedJsonSchema`, no `validateJsonSchemaValue`, and no `JsonSchemaError`. Any dictionary is accepted blindly as `parameters`.

#### [D2] Missing Unified Schema DSL & Compiler
- **TS Reference**: `reference/packages/core/tools/src/schema.ts:1-459`
- **TS Details**:
  - Defines author-facing schema specifications: `StringValueSchemaSpec`, `NumberValueSchemaSpec`, `IntegerValueSchemaSpec`, `BooleanValueSchemaSpec`, `NullValueSchemaSpec`, `ArrayValueSchemaSpec`, `ObjectValueSchemaSpec`, `JsonValueSchemaSpec` (`type: 'json'`), and `OneOfValueSchemaSpec`.
  - Defines implicit open parameter root `ParameterSchemaSpec` with per-property `required: true`.
  - Implements iterative compilation: `valueSchemaSpecToJsonSchema` and `parameterSchemaSpecToJsonSchema`.
  - Handles circular schema detection, symbol key rejection, and `__proto__` data safety.
- **Python Status**: In `dsh/core/tools.py`, tool parameters are uncompiled dictionaries. Neither `valueSchemaSpecToJsonSchema` nor `parameterSchemaSpecToJsonSchema` exists.

#### [D3] Missing Argument Validation & `ToolArgsError`
- **TS Reference**: `reference/packages/core/tools/src/schema.ts:461-480, 586-588`
- **TS Details**:
  - Defines `ToolArgsError` extending `HarnessError` (`INVALID_ARGS`) with `violations: string[]`.
  - Implements `validateArgs(spec, args)` returning path-qualified violations.
  - `defineTool` wraps execution with argument validation (`const violations = validate(args); if (violations.length > 0) throw new ToolArgsError(violations);`).
- **Python Status**: In `dsh/core/tools.py:53-119`, `Tool.execute()` directly unpacks raw model arguments into function arguments without validating arguments against `parameters` schema. No `ToolArgsError` exists.

#### [D4] Missing Mandatory Tool Output Schema Contract
- **TS Reference**: `reference/packages/core/tools/src/schema.ts:491-498, 573-583`, `src/index.ts:211-219, 1038-1044, 1792-1822`
- **TS Details**:
  - Every tool registered via `defineTool` or `register()` MUST declare an `output` contract:
    ```typescript
    output: {
      schema: JsonSchemaNode,
      render(args: unknown, value: JsonValue): ContentBlock[],
      presentationMeta?(args: unknown, value: JsonValue): JsonValue,
    }
    ```
  - Execution returns a canonical JSON value (`InferValue<O>`), NOT raw text.
  - The registry validates the returned value against `output.schema` using `validateJsonSchemaValue`. If violated, raises `ToolOutputError` (`INVALID_TOOL_OUTPUT`).
  - Calls `output.render(args, value)` to produce model-facing `ContentBlock[]`.
- **Python Status**: In `dsh/core/tools.py:18-145`, `Tool` has no `output` field. Handlers return raw text or arbitrary objects, and `ToolExecutionResult.from_raw` simply stringifies/JSON-dumps the returned value into text blocks. No canonical output value, output validation, or `render()` method exists.

#### [D5] Missing Soft Argument Validation for Presenters & Concurrency Safe Classifier
- **TS Reference**: `reference/packages/core/tools/src/schema.ts:598-615`
- **TS Details**:
  - `defineTool` wraps `presentCall` and `presentResult` with soft validation:
    `if (validate(args).length > 0) return undefined;`
    This guarantees session-log replay over obsolete or invalid arguments never throws.
  - Wraps `isConcurrencySafe` with soft validation: `if (validate(args).length > 0) return false;`.
- **Python Status**: In `dsh/core/tools.py:341-348`, `execution_mode()` invokes `tool.is_concurrency_safe(call_args)` directly with no argument schema validation; `present_call` and `present_result` are invoked raw without soft-validation guards.

---

### Category 2: Tool Presentation Vocabulary (`src/presentation.ts`)

#### [D6] Missing Tool Presentation Type Hierarchy & Intent Cards
- **TS Reference**: `reference/packages/core/tools/src/presentation.ts:1-390`
- **TS Details**:
  - Standardized UI render-intent vocabulary:
    - `ToolCallKind`: `'read' | 'edit' | 'delete' | 'move' | 'search' | 'execute' | 'fetch' | 'other'`
    - `FileLocation`: `{ path: string, line?: number }`
    - `FileDiff`: `{ path: string, oldText: string | null, newText: string }`
    - `ToolCallView`: `GenericCallView`, `TerminalCallView`, `DiffCallView`.
    - `ToolResultView`: `GenericResultView`, `TerminalResultView`, `DiffResultView`, `SearchResultView` (`SearchMatchesResultView` vs `SearchPathsResultView`), `ReadResultView`, `WebResultView` (`WebSearchResultView` vs `WebFetchResultView`).
- **Python Status**: In `dsh/core/tools.py`, `present_call` and `present_result` are typed as `Optional[Callable[..., Any]]`. None of the `*CallView`, `*ResultView`, `FileLocation`, or `FileDiff` structures or protocols are defined in `dsh`.

#### [D7] Missing Presentation Metadata Projection (`output.presentationMeta`)
- **TS Reference**: `reference/packages/core/tools/src/schema.ts:497, 578-582`, `src/index.ts:218, 1805-1813`
- **TS Details**:
  - For top-level calls, `output.presentationMeta(args, value)` computes pure replayable presentation metadata persisted verbatim in `ToolExecutionResult.meta` and stored on `tool/result` session events.
  - Presenters (`presentResult(args, result)`) read `result.meta` to reconstruct structured views (e.g. `ReadResultView` reading offset/totalLines, `WebSearchResultView` reading cited sources).
- **Python Status**: In `dsh/core/tools.py`, `meta` is optionally passed in `ToolExecutionResult`, but there is no `output.presentationMeta` projection pipeline on tool execution.

---

### Category 3: Programmatic Tool Calling (PTC) Architecture (`src/ptc.ts`, `src/types.ts`)

#### [D8] Missing `run_code` Tool Implementation & Concurrency Bridge
- **TS Reference**: `reference/packages/core/tools/src/ptc.ts:297-682`
- **TS Details**:
  - `createRunCodeTool(registry, options)` creates the presentation tool `run_code`.
  - Takes `code` (async program) and `description` (concise label).
  - Creates a dedicated sub-call scheduler inside `execute()` with:
    - Ordered driver lane (`pendingQueue`, `commitQueue`, `inFlight`, `logWork`).
    - Deterministic sub-call IDs: `<exec.callId>:code:<n>`.
    - Concurrency bounding: parallel-classified sub-calls overlap up to `maxParallelSubCalls`; exclusive calls wait for pool drain, hold barriers through post-execute commit.
    - Abort drain: cancels in-flight dispatches and drains commitments before program closes.
    - Binds `tools.<name>(args)` to `CodeRuntime.run()`.
- **Python Status**: Completely missing! `run_code` is nowhere to be found in `dsh/core/tools.py` or anywhere in `dsh/`. `dsh/core/agent_tool_presentation.py` merely registers a dummy `mode`, but no `run_code` tool exists and no code-runtime bridge is mounted.

#### [D9] Missing PTC Sub-Dispatch Event Logging
- **TS Reference**: `reference/packages/core/tools/src/types.ts:11-58`, `src/ptc.ts:513-525, 538-544`
- **TS Details**:
  - Emits `tool/code-dispatch-start` with `{ rootCallId, parentCallId, subCallId, name, arguments }` when a subcall begins.
  - Emits `tool/code-dispatch` with `{ rootCallId, parentCallId, subCallId, name, arguments, isError, content }` when a subcall settles.
  - Normalizes arguments before dispatch and detaches a sibling snapshot for logging so tool argument mutation cannot desync durable logs.
- **Python Status**: Completely missing. Neither event type exists in Python session events or tools pipeline.

#### [D10] Missing PTC Mode Collapse & Model-Direct Call Denial
- **TS Reference**: `reference/packages/core/tools/src/index.ts:58, 994-1000, 1323-1325, 1422-1444`
- **TS Details**:
  - Under `mode: 'ptc'`, `wireSchemas()` emits ONLY `[run_code]`.
  - In `resolveExecution()` / `createExecution()`, any model-direct call naming a tool other than `run_code` is intercepted and denied before pre-execute waterfall:
    `ToolNotFoundError(name, "only `run_code` is callable directly — call `<name>` from inside a `run_code` program instead")`.
  - Nested sub-dispatches (carrying a `parent` token) are permitted to execute any visible tool.
- **Python Status**: In `dsh/core/tools.py`, `schemas()` and `get_schemas()` always expose all tools. No collapse logic exists, and no `parent` token check exists.

#### [D11] Missing `tools/ptc-dispatch-log` Waterfall Hook
- **TS Reference**: `reference/packages/core/tools/src/index.ts:176-189, 1287-1305`
- **TS Details**:
  - Provides Cordis waterfall event `tools/ptc-dispatch-log` allowing policies (e.g. spill policy) to reshape durable log content for subtool results before appending `tool/code-dispatch`.
- **Python Status**: Not implemented in `dsh`.

#### [D12] Missing Image Context Deferral & Turn Conclusion in PTC Bridge
- **TS Reference**: `reference/packages/core/tools/src/ptc.ts:565-579`
- **TS Details**:
  - When a sub-call result contains an image block (`block.type === 'image'`), `exec.deferContext(createUserMessage({ content: result.content, source: { kind: 'plugin', plugin: 'tools-code-mode' } }))` attaches it to the turn so the model sees it on the next step.
  - When a sub-call outcome has `result.concludesTurn`, calls `exec.concludeTurn()` to conclude the outer agent turn.
- **Python Status**: Not implemented in `dsh`.

---

### Category 4: PTC Codegen & SDK Generation (`src/ts-types.ts`, `src/py-types.ts`)

#### [D13] Missing Python SDK Codegen for PTC Mode (`py-types.ts`)
- **TS Reference**: `reference/packages/core/tools/src/py-types.ts:1-819`
- **TS Details**:
  - Pure projection from registered tool schemas to Python SDK text (`renderToolsSdkPy`):
    - Generates typed `TypedDict` classes for each tool's argument and output schemas.
    - Generates `class Tools(Protocol):` with `async def <name>(self, args: <Args>) -> <Output>:` methods.
    - Adds JSDoc/docstrings, handles CPython identifier rules (`isBareIdentifier`, NFKC normalization, Unicode `XID_Start`/`XID_Continue`).
    - Quoted comments `# tools["<name>"](...)` for reserved words (`class`, `def`, `from`), non-identifiers, and underscore-leading names.
    - Escapes controls (`UNPRINTABLE`), lone surrogates (`LONE_SURROGATE`), doubles backslashes.
    - Enforces CPython bracket nesting cap (`MAX_LIST_NESTING = 180`).
    - Maps types (`jsonSchemaToPy`): `str`, `float`, `int`, `bool`, `None`, `Literal[...]`, `list[...]`, `dict[str, Any]`, `X | Y`.
- **Python Status**: Completely missing! `dsh` contains zero Python SDK generation code for PTC.

#### [D14] Missing TypeScript SDK Codegen for PTC Mode (`ts-types.ts`)
- **TS Reference**: `reference/packages/core/tools/src/ts-types.ts:1-318`
- **TS Details**:
  - `renderToolsSdk(schemas)` generates TypeScript declarations:
    - `interface ToolArgsMap { ... }`
    - `interface ToolOutputMap { ... }`
    - `type ToolName = keyof ToolOutputMap`
    - `declare class ToolCallError extends Error`
    - `declare const tools: { [K in ToolName]: (args: ToolArgsMap[K]) => Promise<ToolOutputMap[K]>; }`
    - Injects `bash` example when `bash` schema satisfies arguments.
  - `jsonSchemaToTs(schema)` renders stack-safe TypeScript types with JSDoc comments.
- **Python Status**: Completely missing in `dsh`.

#### [D15] Missing Dynamic Language-Aware `run_code` Flavor Resolution
- **TS Reference**: `reference/packages/core/tools/src/ptc.ts:34-133, 668-680`
- **TS Details**:
  - `RUN_CODE_FLAVORS` provides language-specific descriptions for `code` and `description` parameters.
  - `resolveFlavor(peekRuntime)` dynamically queries `CodeRuntime.language` ('typescript' vs 'python') at schema emission time, ensuring model prompt matches runtime language.
- **Python Status**: Completely missing in `dsh`.

---

### Category 5: Tool Runtime Service & Scoped Architecture (`src/index.ts`)

#### [D16] Missing Scoped Tool Layers & Shadowing
- **TS Reference**: `reference/packages/core/tools/src/index.ts:715-755, 812-815, 1151-1192`
- **TS Details**:
  - Employs `ScopedLayers` (`@deepseek-ai/dsh-scope`).
  - Scoped registrations (`agent.ctx.tools.register(...)`) shadow global tools. Disposing an agent scope cleanly unwinds its tools without residual leaks.
  - Scope chain traversal (`view(scope)`): applies restrictions to inherited layers, adds own layer registrations, appends presentation transport.
- **Python Status**: In `dsh/core/tools.py:211`, `ToolsService._tools` is a single flat `Dict[str, Tool]`. Scoped tool registrations and scoped shadowing do not exist.

#### [D17] Missing Tool Restrictions (`tools.restrict()`)
- **TS Reference**: `reference/packages/core/tools/src/index.ts:681-692, 1070-1096`
- **TS Details**:
  - `tools.restrict({ allow?: string[], deny?: string[] })`:
    - Filters global/ancestor tools for a specific agent scope.
    - Validates that restricted names belong to known global tools.
    - Forbids restricting reserved `run_code` transport.
    - Returns an exact effect disposer to lift the restriction.
- **Python Status**: `tools.restrict()` does not exist in `dsh/core/tools.py`.

#### [D18] Missing Monotonic Execution Guards (`tools.guard()`)
- **TS Reference**: `reference/packages/core/tools/src/index.ts:705-712, 1109-1127`
- **TS Details**:
  - `tools.guard(guard: ToolGuard)`:
    - Registers monotonic synchronous check `(exec: ToolExecution) => string | undefined`.
    - Evaluated after `tools/pre-execute` waterfall and before tool execution.
    - Cannot be overridden by allow decisions; fail-closed.
    - Supports global and agent-scoped guard registration.
- **Python Status**: `tools.guard()` does not exist in `dsh/core/tools.py`.

#### [D19] Missing Scoped Presentation Mode (`presentAs`) & System Prompt Sections
- **TS Reference**: `reference/packages/core/tools/src/index.ts:834-892, 946-974`
- **TS Details**:
  - `presentAs(mode)` requires a scoped context (`agent.ctx`).
  - Automatically mounts `tools:ptc-only` prompt section (order 30) and `tools:sdk` section (order 40).
  - Returns a disposer restoring default mode.
- **Python Status**: In `dsh/core/tools.py:308-322`, `present_as()` only sets a string attribute `_presentation_mode`. It does not register prompt sections and does not hook into `systemPrompt`.

#### [D20] Missing `tools/execute` Around-Dispatch Waterfall
- **TS Reference**: `reference/packages/core/tools/src/index.ts:153-163, 1531-1575`
- **TS Details**:
  - `tools/execute` is an around-dispatch waterfall event (`exec, next()`).
  - Allows middleware plugins (timeout policy, retries, metrics, sandboxing) to wrap the execution.
  - Fuses replacement signals with caller signal via `fuseToolSignals()`.
- **Python Status**: `dsh/core/tools.py` has `tools/pre-execute` and `tools/post-execute`, but completely lacks `tools/execute` around-dispatch waterfall! Timeout policies in `dsh/guard/timeout_policy.py` cannot wrap tool execution via standard Cordis waterfall.

#### [D21] Missing User Approval Seam (`PreToolDecision: ask`)
- **TS Reference**: `reference/packages/core/tools/src/index.ts:589-593, 1688-1728`
- **TS Details**:
  - `tools/pre-execute` supports decision `{ kind: 'ask', reason?: string }`.
  - Delegates to `ctx.get('approval')` (`ApprovalService.request(...)`).
  - Handles outcomes: `allowed-once`, `rejected`, `cancelled`, `unavailable`.
- **Python Status**: In `dsh/core/tools.py:361-379`, `tools/pre-execute` only recognizes custom dict keys (`skip`, `abort`, `allow`). No `ask` decision or `ApprovalService` integration exists.

#### [D22] Missing Final Content Hook (`finalizeContent`)
- **TS Reference**: `reference/packages/core/tools/src/index.ts:246-247, 1648-1653`
- **TS Details**:
  - `ToolDefinition.finalizeContent(exec, result): ContentBlock[] | undefined`.
  - Snapshotted at execution start; invoked for every normalized outcome (including failures) before materialization to allow last-mile tool-owned content formatting.
- **Python Status**: Not supported in `dsh/core/tools.py`.

#### [D23] Missing Cancellation Fusing & Distinction (`TOOL_ABORTED` vs `BEFORE_DISPATCH`)
- **TS Reference**: `reference/packages/core/tools/src/index.ts:469-474, 1508-1558, 1885-1943`
- **TS Details**:
  - Distinguishes cancellation BEFORE dispatch (`TOOL_ABORTED_BEFORE_DISPATCH`) from cancellation AFTER body invocation (`TOOL_ABORTED`).
  - `fuseToolSignals()` cleanly combines caller signal and around-wrapper signal without leaks.
  - Ensures tool body promise settles to quiescence before abort outcome is published.
- **Python Status**: `dsh/core/tools.py` only defines constants `TOOL_ABORTED_BEFORE_DISPATCH` and does not track whether tool body was invoked or fuse signals.

#### [D24] Missing Context Deferral & Turn Conclusion APIs
- **TS Reference**: `reference/packages/core/tools/src/index.ts:398-422, 1390-1395`
- **TS Details**:
  - `ToolRunContext` provides `deferContext(context: UserMessage)` to ferry messages/instructions to be emitted after `tool/result`.
  - Provides `concludeTurn()` to conclude the turn on successful terminal tool calls.
- **Python Status**: Missing from `ToolExecutionInput` and `Tool.execute()` in `dsh/core/tools.py`.

#### [D25] Missing `tools/result` and `tools/change` Event Dispatches
- **TS Reference**: `reference/packages/core/tools/src/index.ts:190-208, 1656-1675`
- **TS Details**:
  - Dispatches emit event `tools/result` with deep-frozen `(exec, result)`.
  - Dispatches emit event `tools/change` whenever a tool is registered, unregistered, or restricted.
- **Python Status**: `dsh/core/tools.py` does not emit `tools/result` or `tools/change`.

---

### Category 6: Package Invariants Companion (`src/invariant.ts`)

#### [D26] Missing Package Invariants Companion Plugin
- **TS Reference**: `reference/packages/core/tools/src/invariant.ts:1-129`
- **TS Details**:
  - Plugin `tools-invariant` (`@deepseek-ai/dsh-tools/invariant`).
  - Validates pipeline stage monotonicity: `pre` -> `execute` -> `post` -> `result`. Rejects repeated pre-execute or skips.
  - Validates frozen states on publication (`Object.isFrozen(exec)`, `Object.isFrozen(result)`).
  - Validates non-empty name and callId.
  - Validates `tool/code-dispatch-start` and `tool/code-dispatch` parent-root enclosure and open turn enclosure.
- **Python Status**: Completely missing in `dsh`.

---

### Category 7: Test Suite & Fixture Parity (`tests/*`)

#### [D27] Missing Test Fixture Helper `defineContentToolFixture`
- **TS Reference**: `reference/packages/core/tools/src/testing.ts:1-43`
- **TS Details**:
  - `defineContentToolFixture<S>(options)` provides canonical test fixture that maps content blocks directly to JSON array outputs.
- **Python Status**: Not implemented in `dsh`.

#### [D28] Test Suite Discrepancy Across All 12 Spec Files
The reference repository contains 12 dedicated Vitest test suites in `reference/packages/core/tools/tests/` totaling 8,261 lines of tests:

| Spec File | Lines | Test Scope | Python Test Equivalent in `dsh` | Status |
| :--- | :---: | :--- | :--- | :--- |
| `tests/execution-mode.spec.ts` | 142 | Fail-closed per-call classification, isolation from model schema | `tests/test_tools_execution_mode_classification_1to1.py` (118 lines) | **Partial** |
| `tests/execution-signal-types.spec.ts` | 105 | Static type tests for `AbortSignal` at all pipeline stages | None | **Missing** |
| `tests/gen-tool-catalog.spec.ts` | 152 | Tool schema catalog harvest & manifest completeness | None | **Missing** |
| `tests/invariant.spec.ts` | 240 | Pipeline monotonicity, frozen snapshots, PTC turn enclosure | None | **Missing** |
| `tests/json-schema.spec.ts` | 456 | JSON schema subset enforcement, prototype security, stack safety | None | **Missing** |
| `tests/properties.spec.ts` | 176 | Property-based tests (`fast-check`) for DSL compilation & validation | None | **Missing** |
| `tests/ptc.spec.ts` | 1,878 | `run_code` execution, fake runtime, SDK prompt, subcall scheduler, events | None | **Missing** |
| `tests/py-types.spec.ts` | 1,173 | Python SDK generation (`TypedDict`, `Protocol`, `isBareIdentifier`, docstrings) | None | **Missing** |
| `tests/schema.spec.ts` | 206 | Author schema DSL compilation, deep nesting, `__proto__` safety | None | **Missing** |
| `tests/scoped.spec.ts` | 720 | Scoped registration, shadowing, `restrict()`, `guard()`, disposal | None | **Missing** |
| `tests/tools.spec.ts` | 2,786 | Full pipeline: pre/execute/post, approval, output validation, cancellation | `tests/test_tools.py` (68 lines), `test_1to1_tools_parity.py` (51 lines) | **Severe Deficit** |
| `tests/ts-types.spec.ts` | 231 | TypeScript SDK generation, JSDoc escaping, stack safety | None | **Missing** |
