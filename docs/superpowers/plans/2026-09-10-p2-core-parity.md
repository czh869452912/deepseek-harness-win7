# P2 实施计划：core 层 1:1 对照对齐 + P1 遗留收口

日期：2026-09-10
状态：待用户批准
总设计：`docs/superpowers/specs/2026-09-02-1to1-parity-migration-design.md`（P2 行）；方法沿用 P1 全流程（盲审对照 → 差异报告 → 实现对齐 → 1:1 测试移植 → 复审门 → 提交）
前置：P1-R 四轮修复审核闭环（NOT-READY 已解除，见 `p1-reverify/FIX-REVIEW-4.md`）

## 0. 目标与规模

- **主体**：`dsh/core/*`（16 文件 4,678 行）对照 `reference/packages/core/*` 8 包（src ≈12,778 行 TS / specs ≈24,892 行）。P1 是"漂移修正"，P2 主体是**缺失行为补齐**（Python 侧仅为 TS 规模的 37%）。
- **顺带收口**：P1 遗留积压——cordis 地基 ≈25 项 MUST-FIX、boot/profile ≈25 项、测试债 47 处、R-2 便携冒烟。
- **用户决策**（2026-09-10）：① 地基先清再进 core；② P4（Web GUI）按原计划，不提前。

## 1. 波次划分（顺序已确认）

### Wave P2-0：cordis 地基收尾（修复轮未触达的 ≈25 项 MUST-FIX）

| 组 | 条目 | 要点 |
|---|---|---|
| G2-plugin | D4 @inject 延迟执行、D6 Plugin.id 身份键、D7 runtime name/Config 回退、D10 internal/plugin emit 归属、D28 allow_replace/同值放行 | registry 契约；D28 为 TS 无条件抛 |
| G3-events | D4 next 覆写参数、D6 internal/dispatch 双约定、D7 internal/listener 收窄/payload | 与 D3 否决契约同族收尾 |
| G5-fiber | D8 apply 签名嗅探、D14 微任务失效检查点、D20 name 回退、D21 restart 自发明 | effect 引擎收尾 |
| G6-context | D1 is_ 鸭子兜底、D2 _effect_metas、D3 extend shadow、D5 isolate 收敛、D9 根 strict 旁路、D10 internal/get 双派发、D11 多级兜底栈、D12 store 裸名查找 | context 区唯一整体未修的组 |
| G1/G4 | G1 D5 parse_date 年份分支、G1 D14 is/Binary/defineProperty/mapValues、G4 D2 回调异常吞掉 | 小项随手清 |

流程：派 2-3 个对照智能体按 p1-reverify 报告清单逐项复核现行状态（防 P1 修复轮已顺手修掉）→ 实现 → 每项补钉测 → 全量 pytest + 探针回归 → 提交 `P2-0: cordis ground-layer leftovers`。

### Wave P2-1：boot/profile 收尾 + legacy 退役 + 测试债

- **G12**（≈10）：D1 双轨收敛（删 cordis/profile.py 平行实现，三预设走 boot 正典）、D4 patchReload 校验回落、D6 manifest 消费、D8 根 cordis.yml 重写、D9 heal 接线复核、D11 resolve_dsh_home strip、D13/D14/D15 错误文本、D18/D19 LAN/层序收尾
- **G13**（≈15）：D3 args 版本/文案、D5+D7 HostResolvedRootInclude 回退、D6 审计空值抛错收尾、D11 FIRST_PARTY_SECTION_ORDER、D12 sort_keys、D13 文案、**D15 harness 内联审计删除 + build_harness 收编 run_profile（legacy 双轨退役）**、D19 ready 可调用回退、D21–D23 ENOENT 语义、D27 快照合一、D29 warn 尾参、D30 patchReload 空值、D31 Command 语义补齐、D32 CancelledError dispose
- **G8**：D6 剩余参数 oFormatter 全覆盖、D8 splitlines→`/\r?\n/`
- **R-2**：build_portable 后 dist 内 profile-boot 端到端冒烟门（进 scripts 或 CI 步骤）
- **测试债**：T1 F1 waterfall None-续传钉测改标注（随 G3 D4 修复重写）、5 OVERCLAIM、6 WEAK；T2 29 弱化 + F3 时序 + F2 non-Error
- 流程：同 P2-0；legacy 退役单独提交（可回滚），退役后全量 pytest + `dsh.py --mode minimal` 真实启动冒烟 + `--dump-config` 三预设对照。

### Wave P2-2：test-support 移植（core 测试的地基）

移植 `packages/test-support/` 三件到 `tests/1to1/_support/`：
- `agent-loop-testkit`（agent-loop 全部 spec 的驱动器）
- `llm-mock-server`（LLM HTTP mock，spec 中 request-cache.e2e 等依赖）
- `session-snapshot`（fixtures/suite 快照机制）
1:1 移植 + 各自 spec 移植（testkit 自带 tests/agent-loop-testkit.spec.ts）。**先于一切 core 包**。

### Wave P2-3…P2-9：core 8 包（依赖序，每包一波）

| 波 | 包 | TS src/spec | Python 现状 | 备注 |
|---|---|---|---|---|
| P2-3 | session | 3028 / 4688 | session.py 976 + surface.py 360 | 其余子模块：chunk-rows/json/known-event-types/preparation/repair/request-header/seq-ranges/types；**persona.py 归属待审计定位** |
| P2-4 | system-prompt | 605 / 852 | system_prompt.py 398 | |
| P2-5 | tools | 5304 / 7578 | tools.py 467 | **缺口最大**（Python 9%） |
| P2-6 | scope | 507 / 557 | scope.py 181 | |
| P2-7 | agent | 1547 / 1369 | agent.py 487 + inbox.py 183 + consumed_work.py 63 + model_selection.py 82 | agent/src 子模块：dispatch/inbox/consumed-work/model-selection/runtime-types/types |
| P2-8 | agent-loop | 1575 / 9655 | agent_loop.py 929 + tool_calls.py 299 + runtime_context.py 68 | **spec 最大**；依赖 session/tools/scope/agent 全部就位 |
| P2-9 | agent-default-model + agent-tool-presentation | 119+93 / 86+107 | 74 + 41 | 小包合波收尾 |

每包固定流程：
1. **盲审对照**（1-2 个智能体）：逐文件 TS↔Python 映射，产出差异报告（缺失行为为主，格式同 p1-reverify：D/T 条目 + TS 引文）——报告落 `docs/superpowers/plans/p2-reports/<wave>-<pkg>.md`
2. **spec 1:1 移植先行（TDD）**：`tests/1to1/core/<pkg>/test_<spec名>.py` 与 TS spec 文件一一对应（describe/it → class/test_ 保名 snake_case）；Node/TS 特有用例头注记录跳过原因，不许静默省略
3. **实现对齐**：按差异报告补齐，红→绿
4. **复审门**：1 个独立审查智能体核对该包（引文抽查 + 探针）→ 修复 → 全量 pytest + compileall → 提交 `P2-<n>: <pkg> 1:1 alignment + tests`

## 2. 验证协议（全程）

- 每波次：全量 pytest 全绿、`compileall` exit 0、py3.9+ 语法扫描零违规
- 地基波（P2-0/1）加：p1-reverify 12 项探针回归全绿
- core 波（P2-8 后）：真实对话冒烟——`dsh.py --mode minimal` 一轮真实 LLM 对话（工具调用 + 流式），作为 agent-loop 波次验收
- 每波独立提交，复审门未过不合入下一波

## 3. 风险与对策

| 风险 | 对策 |
|---|---|
| specs 体量（25k 行）×2 波（P3 session-query 还要用） | 按包分波独立交付；test-support 先行复用；每包 spec 缺口在审计报告中量化后按 it 粒度移植，禁止整文件跳过 |
| core 行为依赖 cordis 语义，地基残留导致误判 | P2-0 强制先行；审计智能体输入含 p1-reverify 偏差清单（许可偏差不再重复报告） |
| legacy 退役（G13 D15）影响用户现有使用习惯 | 退役单独提交；`dsh.py` 入口行为保持（--mode X 等价映射到 parse_dsh_args 分发），AGENTS.md 更新使用说明 |
| tools 包缺口 9%，一次对齐量巨大 | P2-5 内部按 spec 文件再分批（每批红→绿→提交），波内多提交 |
| LLM mock/e2e 用例在 py3.8 的可行性 | P2-2 移植时逐个甄别，不可行用例头注记录（同 P1 口径） |

## 4. 交付物

- `docs/superpowers/plans/p2-reports/`：每包盲审差异报告 + 复审报告
- `tests/1to1/_support/` + `tests/1to1/core/<8 包>/`
- `dsh/core/*` 对齐后的实现
- AGENTS.md 增补：creative 分层说明（已完成）、legacy 退役说明（P2-1）
