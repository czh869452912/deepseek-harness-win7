# P2-3 差异报告：@deepseek-ai/dsh-session 对照审计

日期：2026-09-11
对照源：`reference/packages/core/session/` (src: 11 文件, tests: 14 文件)
实施目标：`dsh/core/session.py`, `dsh/core/surface.py`, `dsh/session/repair.py` 1:1 对齐与缺失子模块补齐

---

## 0. 模块与架构映射

| Upstream TS 模块 | Python 现状 | 差异定级 | 解决途径 |
|---|---|---|---|
| `json.ts` (191 行) | `dsh/core/session.py` (内联简陋 `snapshot_json_value`) | **MUST-FIX** | 独立 `dsh/core/session/json.py`，实现迭代无递归遍历、`-0.0` 拒收、`is_json_value`、`snapshot_json_value` |
| `types.ts` (418 行) | `dsh/core/session.py` (散落类型与常量) | **MUST-FIX** | 规范 SessionId, SESSION_FORMAT_VERSION, SessionHeader, SessionEventMap, TurnEndReason 等 |
| `repair.ts` (134 行) | `dsh/session/repair.py` (283 行，多余字段与旧迁移混杂) | **MUST-FIX** | 1:1 规范 `interrupted_turn_closers`、`TOOL_NOT_STARTED`、`TOOL_OUTCOME_UNKNOWN`，纠正 event envelope 结构 |
| `request-header.ts` (72 行) | `dsh/core/session.py` (内联简陋实现) | **MUST-FIX** | 规范 `canonical_header`、`header_equals`、`fold_request_header`，适配 `adapterDefaults` 与 `call_config_equals` |
| `preparation.ts` (50 行) | `dsh/core/session.py` (SessionPreparation 类) | **MUST-FIX** | 补齐 context manager (`__enter__`, `__exit__`) 与单次幂等 release 语义 |
| `surface.ts` (461 行) | `dsh/core/surface.py` (438 行) | **SHOULD-FIX** | 对齐 `derive_event_message`、`fold_surface`、`SurfaceManager` 与 TS 细微行为 |
| `invariant.ts` (250 行) | 缺失 | **MUST-FIX** | 实现 `SessionInvariant` 伴随插件，注册至 `invariants` 服务 |
| `seq-ranges.ts` (83 行) | `tests/1to1/_support/session_snapshot/seq_ranges.py` 已有 | **PORT** | 纳入 `dsh/core/session/` 统一导出 |
| `chunk-rows.ts` (112 行) | `tests/1to1/_support/session_snapshot/chunk_rows.py` 已有 | **PORT** | 纳入 `dsh/core/session/` 统一导出 |
| `known-event-types.ts` (71 行) | `dsh/core/session.py` 已有列表 | **ALIGN** | 确保与 TS 40 个已知事件类型完全一致 |
| `index.ts` (1157 行) | `dsh/core/session.py` (Session & SessionStore) | **MUST-FIX** | 对齐 `Session`、`SessionStore` 的 Scope carrier、fork、恢复验证、事件通知隔离与 rollback |

---

## 1. 差异清单

### D1 [MUST-FIX] `snapshot_json_value` 缺陷：递归上限溢出、未拒绝 `-0.0`、缺少 `is_json_value`
- **位置**: `dsh/core/session.py:104-126` vs `packages/core/session/src/json.ts:1-191`
- **原版行为**:
  - `walkJsonValue` 采用迭代任务栈（而非递归），支持 5,000+ 深度嵌套。
  - 严格拒绝 `-0`：`Number.isFinite(current) && !Object.is(current, -0)`。
  - 严格拒绝 `NaN`, `Infinity`, `-Infinity`。
  - 严格拒绝异构对象（Map, Set, 自定义类、原型篡改对象、稀疏数组、带额外属性的数组、Symbol 键等）。
  - 对每个属性仅读取一次，防止 getter 状态突变。
  - 导出 `is_json_value(value)` 与 `snapshot_json_value(value)`。
- **移植版现状**:
  - 依赖 `json.dumps()` / `json.loads()`，深层结构直接触发 Python `RecursionError`。
  - 允许 `-0.0` 通过。
  - 失败时返回 `None`，与合法 JSON 值 `null` (`None`) 产生二义性。
  - 缺失 `is_json_value`。
- **修复方案**:
  - 移植 `json.py`，实现显式栈遍历，精确区分 `UNDEFINED` 哨兵，拒绝 `-0.0`（通过 `math.copysign(1.0, v) < 0` 判断），深度限制只受可用内存约束。

### D2 [MUST-FIX] `repair.ts` 契约偏差：合成了非标准的 `tool_call_id` 根字段
- **位置**: `dsh/session/repair.py:101` vs `packages/core/session/src/repair.ts:109-124`
- **原版行为**:
  ```ts
  closers.push({
    type: 'tool/result',
    seq: seq++,
    time,
    data: {
      turn: openTurn,
      step,
      message,
      error: started
        ? { name: 'ToolOutcomeUnknownError', code: TOOL_OUTCOME_UNKNOWN }
        : { name: 'ToolNotStartedError', code: TOOL_NOT_STARTED },
    },
    surfaceOp: 'append',
    ...started ? { sourceEventSeqs: [callSeq] } : {},
  })
  ```
  `data` 仅含 `turn`, `step`, `message`, `error`（及可选 `meta`）。
- **移植版现状**:
  - `dsh/session/repair.py` 在 `data` 中额外添加了 `"tool_call_id": call_id`，破坏了与 `SessionEventMap['tool/result']` 的 1:1 结构一致性。
- **修复方案**:
  - 移除多余字段，统一导出 `interrupted_turn_closers`、`TOOL_NOT_STARTED`、`TOOL_OUTCOME_UNKNOWN`。

### D3 [MUST-FIX] `SessionStore` 缺少 Scope carrier 派发支持
- **位置**: `dsh/core/session.py:883-1120` vs `packages/core/session/src/index.ts:37-87, 400-410, 912-925`
- **原版行为**:
  - `enter(session)` 中获取 `carrier = scopeTarget(session, scopeOf(this.ctx))`。
  - 发布 `session/created`, `session/event`, `session/disposed`, `session/flush` 时透传 `carrier`，使 scoped 监听器只接收其作用域内的 session 事件。
- **移植版现状**:
  - 未使用 `scope_target`，所有事件全局裸发，导致 scoped spec 无法正常过滤。
- **修复方案**:
  - 在 `SessionStore` 维护 `SessionEntry`，捕获 `carrier` 并按 scope 派发。

### D4 [MUST-FIX] `Session.create` 与 `SessionStore.create` 的生命周期与回滚机制
- **位置**: `dsh/core/session.py:984-1008` vs `packages/core/session/src/index.ts:828-838`
- **原版行为**:
  - `SessionStore.create()` 将 `enter` 返回的 detach disposer 注册到 `ctx.effect` 中，随后调用 `announce()`。
  - 若 `session/created` 监听器同步抛错，effect 机制自动触发已注册的 detach，将 session 从 store 中移除并派发 `session/disposed`，实现原子回滚。
- **移植版现状**:
  - 使用简单的 try-except，缺少与 Cordis fiber effect 生命周期的协同。
- **修复方案**:
  - 规范 `SessionStore.create` 与 `prepare`/`enter`/`announce` 流程。

### D5 [MUST-FIX] `SessionStore.fork` 边界检查与错误代码规范
- **位置**: `dsh/core/session.py:1010-1090` vs `packages/core/session/src/index.ts:1079-1152`
- **原版行为**:
  - 错误代码为枚举 `SessionForkErrorCode`: `SESSION_NOT_FOUND`, `SESSION_NOT_LIVE`, `SESSION_ALREADY_EXISTS`, `INVALID_BOUNDARY`, `OPEN_TURN`。
  - 若 boundary 省略，默认截取到 `lastEvent.seq`；若空 session 则返回空 seed。
  - 截取切片最后一个 turn 边界如果是 `turn/start`，无条件抛 `OPEN_TURN`。
- **移植版现状**:
  - 错误信息和异常类型基本具备，但需确保错误代码与 TS 完全一致（`SessionForkError.code`）。

### D6 [MUST-FIX] `Session.append` 异常隔离与观察者保护
- **位置**: `dsh/core/session.py:575-633` vs `packages/core/session/src/index.ts:379-397, 602-653`
- **原版行为**:
  - 观察者（`session/event` 监听器）执行时被单个隔离容器包裹（`invokeContainedSessionObservers`）。
  - 若某个观察者抛错，仅通过 `ctx.logger.warn` 记录日志，**不影响已提交的 append 成功返回**，也不阻止后续观察者接收事件。
- **移植版现状**:
  - 直接调用 `self.ctx.emit(...)`，一旦监听器抛错，导致 `append` 抛出异常中断调用方流程。
- **修复方案**:
  - 对齐 `invoke_contained_session_observers` 机制，保障 append 事务提交后的观察者失败隔离。

### D7 [MUST-FIX] `Session.fromRestore` 语义与入参对齐
- **位置**: `dsh/core/session.py:561-574` vs `packages/core/session/src/index.ts:493-546`
- **原版行为**:
  - `Session.fromRestore(id, seed, header)` 仅负责校验并所有权转移已恢复的持久化数据（不自动调用 `interruptedTurnClosers`；尾部修复属于持久化恢复层职责）。
  - 严格校验 `validateRestoredSessionHeader` 与 `freezeRestoredObject`。
- **移植版现状**:
  - 在 `from_restore` 内部调用了 `interrupted_turn_closers` 和 `migrate_legacy_event`。
- **修复方案**:
  - 纯化 `Session.from_restore`，保持与 TS 1:1 职责边界。

### D8 [MUST-FIX] 缺少 `session-invariant` 伴随插件
- **位置**: 缺失 vs `packages/core/session/src/invariant.ts:1-250`
- **原版行为**:
  - 提供 `session-invariant` 插件，注入 `invariants` 服务，在 `internal/dispatch` 预校验并暂存 transition，在 `session/event` 确认提交。
  - 严格检查 turn/step 嵌套、seq 单调递增、工具调用成对性（未启动合成工具除外）。
- **移植版现状**:
  - 缺失该插件实现。
- **修复方案**:
  - 移植 `invariant.py`，实现与 `dsh.diagnostics.invariants` 的对接。

---

## 2. 规范化文件布局

为了既保持 `from dsh.core.session import Session, SessionStore...` 百分之百向后兼容，又实现 1:1 模块化：
- `dsh/core/session/` 包目录：
  - `__init__.py`: 导出全部公共 API（Session, SessionStore, SessionHeader, SessionPreparation, SessionForkError, json 函数, repair 函数, request_header 函数等）
  - `types.py`: 类型常量与定义
  - `json.py`: 无损 JSON snapshot 与校验
  - `repair.py`: 崩溃恢复合成器
  - `request_header.py`: 请求头规范化与折叠
  - `preparation.py`: 未发布会话包装器
  - `seq_ranges.py`: 序列范围编码
  - `chunk_rows.py`: chunk 流编码
  - `known_event_types.py`: 已知事件类型集合
  - `invariant.py`: 伴随不变式插件
- `dsh/core/surface.py`: 保持并对齐
- `dsh/core/session.py`: 兼容桥接文件（直接 `from dsh.core.session import *`）

---

## 3. 验收测试计划 (TDD)

移植 `packages/core/session/tests/*.spec.ts` 至 `tests/1to1/core/session/`：
1. `test_json.py` (对照 `json.spec.ts`, 250 行)
2. `test_seq_ranges.py` (对照 `seq-ranges.spec.ts`, 143 行)
3. `test_chunk_rows.py` (对照 `chunk-rows.spec.ts`, 152 行)
4. `test_repair.py` (对照 `repair.spec.ts`, 187 行)
5. `test_request_header.py` (对照 `request-header.spec.ts`, 112 行)
6. `test_surface.py` (对照 `surface.spec.ts`, 451 行)
7. `test_fork.py` (对照 `fork.spec.ts`, 260 行)
8. `test_derived_cache.py` (对照 `derived-cache.spec.ts`, 215 行)
9. `test_session.py` (对照 `session.spec.ts`, 1658 行)
10. `test_scoped.py` (对照 `scoped.spec.ts`, 338 行)
11. `test_properties.py` (对照 `properties.spec.ts`, 210 行)
12. `test_invariant.py` (对照 `invariant.spec.ts`, 248 行)
