# P2-4 盲审差异报告：system-prompt

**标的包**：`packages/core/system-prompt` (TS src: 2 文件 ~658 行 / tests: 4 文件 ~989 行)  
**对照实现**：`dsh/core/system_prompt.py` (Python 496 行)  
**日期**：2026-09-11  
**状态**：已审计，准备对齐

---

## 1. 模块映射与行数对比

| Upstream TS (`packages/core/system-prompt`) | 职责 | Python 现存 (`dsh/core/`) | 状态 |
|---|---|---|---|
| `src/index.ts` (597 lines) | `SystemPrompt` 服务、PromptLayer、assemble、renderPrompt、renderContextSnapshot、orderTools、interpolate | `system_prompt.py` (496 lines) | 基本具备但缺乏 ScopedCarrier 派发、变动回滚保护及作用域链层级处理 |
| `src/invariant.ts` (61 lines) | `system-prompt-invariant` 伴生插件，契约断言（非空名称、无重复、有效变量规则） | **缺失** | 需补齐 `dsh/core/system_prompt/invariant.py` |
| `tests/invariant.spec.ts` (49 lines) | invariant 伴生插件验证 | **缺失** | 需移植至 `tests/1to1/core/system_prompt/test_invariant.py` |
| `tests/scoped.spec.ts` (227 lines) | 作用域级 sections、contexts、tools、variables、suppression、assemble dispatch | 仅部分零散覆盖 | 需完整 1:1 移植至 `tests/1to1/core/system_prompt/test_scoped.py` |
| `tests/tool-order.spec.ts` (116 lines) | 工具排序、TOOL_ORDER_REST 插入、未注册报错、稳定排序 | 仅部分覆盖 | 需完整 1:1 移植至 `tests/1to1/core/system_prompt/test_tool_order.py` |
| `tests/system-prompt.spec.ts` (602 lines) | 内置项、排序、HMR 卸载、回滚机制、waterfall 链、快照隔离、变量插值 | 仅部分覆盖 | 需完整 1:1 移植至 `tests/1to1/core/system_prompt/test_system_prompt.py` |

---

## 2. 差异明细清单 (D-Item List)

### [D1] 缺失 `SystemPromptInvariantPlugin` 伴生插件与不变式检查
- **TS 依据**: `src/invariant.ts:1-61`。
- **现状**: Python 完全未实现 `SystemPromptInvariantPlugin`，当系统加载 `invariants` 服务时无法提供自动装配契约防御。
- **对齐目标**: 实现 `dsh/core/system_prompt/invariant.py`，注册 `system-prompt-invariant`，在 `system-prompt/assemble` 前置拦截器中校验 `sections`、`contexts`、`tools`、`variables` 的有效性、唯一性与类型契约。

### [D2] `assemble` 事件分发未携带 `ScopedCarrier`
- **TS 依据**: `src/index.ts:583-586`:
  ```ts
  const transformed = await this.ctx.waterfall(
    scopeTarget(this, scope), 'system-prompt/assemble', assembly, context,
    () => Promise.resolve(assembly),
  )
  ```
- **现状**: Python 直接调用 `self.ctx.waterfall("system-prompt/assemble", assembly, ctx_param)`，未传递 `scope_target(self, scope)` 作为 carrier，导致 scoped listener 无法按作用域精确过滤。
- **对齐目标**: 在 Python 中使用 `scope_target(self, scope)` 作为 carrier 派发 waterfall。

### [D3] 注册项变更广播失败时的回滚机制 (P1-1 回滚保护)
- **TS 依据**: `tests/system-prompt.spec.ts:193-264`:
  - `rolls back a section when a system-prompt/change listener throws (P1-1)`
  - `rolls back a tool provider when a system-prompt/change listener throws (P1-1)`
  - `rolls back a variable when a system-prompt/change listener throws (P1-1)`
- **现状**: Python 中先插入 registry 再 `ctx.emit("system-prompt/change")`，若 listener 抛错，已插入的项目留在内存中泄露。
- **对齐目标**: 在变更触发后若抛出异常，立即捕获并执行撤回，然后重新向外抛出该异常，确保状态零残留。

### [D4] Tool Provider 快照隔离
- **TS 依据**: `src/index.ts:538-541` 及 `tests/system-prompt.spec.ts:231-247`:
  `snapshots tool-provider membership before evaluating an assembly`
- **现状**: 在 assemble 执行期间若 tool provider 动态向当前 layer 添加新 tool provider，可能发生正在遍历时列表修改或直接参与本轮 assemble。
- **对齐目标**: assemble 时先对有效 tool providers 取快照副本 `list(...)`，再进行执行求值。

### [D5] Complete Section 互斥与恢复机制严格 1:1
- **TS 依据**: `src/index.ts:556-592`:
  - 若存在多个 `complete === true` 的 section，抛出 `multiple complete prompt sections are active: "a", "b"`
  - 若存在单一 `complete === true` 的 section，在 waterfall 结束后强制将 `assembly["sections"]` 恢复为单一的 `completeSection`，防止 listener 注入额外 prompt。
- **现状**: Python 逻辑基本具备，但需要与 TypeScript 的错误文本格式和单 section 恢复严格对齐。

### [D6] 变量插值中 `(none)` 与格式文本对齐
- **TS 依据**: `src/index.ts:336`:
  `unknown prompt variable "{{x}}" in section "s"; registered variables: (none)`
- **现状**: Python 中的未知变量与未赋值变量错误文本基本一致，需确保空集合显示为 `(none)`，已注册变量按排序拼接。

---

## 3. 架构落地设计

重构 `dsh/core/system_prompt` 为模块化目录结构：
```
dsh/core/system_prompt/
├── __init__.py          # 完整 barrel 导出
├── service.py           # SystemPrompt 服务核心
├── invariant.py         # SystemPromptInvariantPlugin 伴生插件
├── layer.py             # PromptLayer 与作用域分层
└── types.py             # 类型定义、常量与工具函数（FIRST_PARTY_SECTION_ORDER 等）
```
同时保留 `dsh/core/system_prompt.py` 作为平滑兼容重定向。
