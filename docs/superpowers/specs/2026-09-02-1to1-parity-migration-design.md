# 1:1 对照移植总体设计（deepseek-harness → deepseek-harness-win7）

日期：2026-09-02
状态：已获用户批准的方向性设计

## 1. 目标与约束

- 目标：以 `reference/`（dsh-v0.1.2-alpha.1 快照）为唯一设计基准，对移植版 `dsh/` 做 1:1 对照对齐：设计逻辑、代码组织、代码实现、测试全部对齐；真实使用（尤其官方 Web GUI 的设置与按钮）行为与原版一致。
- 约束（仅允许在这两点上偏离原版，其余必须 1:1）：
  1. Python 3.8.10 语法/标准库限制：禁用 3.9+ 语法（`list[str]`、`str.removeprefix`、`match/case` 等）；`typing.List/Dict`；asyncio 用 3.8 兼容写法。
  2. Windows 7 SP1 运行环境：`powershell.exe` 优先回退 `cmd.exe`；bash 系列原版包不移植（平台不可行）；路径/编码（utf-8 显式）按 AGENTS.md 规则。
- 平台不可行、明确不移植：`e2b/*`（云沙箱）、`shell/bash-*`+`tool-bash`+`terminal-bash`（bash 依赖）、`experimental/webworker-*`（浏览器端）、`experimental/inspector`（CDP）、`sandbox/sandbox-local` 的 bwrap/seatbelt 部分（保留 windows-acl 思路）、`sdk/client`（TS SDK；Python 侧 SDK 不在本仓库范围）。
- 其余原版包**全部移植**，包括此前遗漏：feedback、hooks（hook-protocol 可移植，claude-code/codex 桥按协议移植）、win32-process、schedule、user-questions、command-goal、command-compact、goal-round-driver、fs-observation-policy、fs-sandbox(windows 适配)、skill-badge、session-telemetry、session-projection-cache、web-search-exa/perplexity、subagent 各后端（acp/claude-code/codex/dsh-sdk/fork/spawn → 按进程内等价实现）、tool-subagent-report、terminal（PTY 用 py3.8 可行方式）、lsp（stdio JSON-RPC）、workflow-worker-thread（线程等价）、deepseek-llm-api-extensions、context/session-reference、tmux-context（win 下按原版禁用语义）。

## 2. 现状结论（探索已完成）

- 映射清单：`dsh/<module>` ↔ `reference/packages/<group>/<pkg>` 已建立（35 模块，266 py 文件）；根 `packages/` 是 reference/packages 的干净拷贝（12238 文件，0 内容差异，仅少 node_modules/tsbuildinfo）。
- Web GUI 痛点根因：`apps/web/dist` 与 `reference/apps/web/dist` 逐字节一致（官方 React 构建版），客户端插件来自原版 `packages/client/`；但后端 `dsh/host/apiproxy` 移植的是**已废弃的旧 host/apiproxy 设计**。现行原版为 `api/gateway` + `api/remotes` + `session/settings/workspace-controller` + `client/connection` 传输层。wire 契约漂移导致官方前端行为异常。
- 原版测试面：`packages/*/*/tests/**/*.spec.ts` = 970 文件 / 约 29 万行（100% 覆盖率门禁）；vendor 各包自带 `test/`。移植版现有 154 个自创 pytest 文件（728 用例全绿，作为回归安全网保留，1:1 测试另建）。
- 死代码：dsh/mcp、dsh/acp、dsh/attachment、dsh/schedule、dsh/identity、session/{checkpoint_policy,coordinator,stats}、compaction/command_compact、context/tmux_context、spill/spill_policy、interaction/user_questions（有消费者无挂载者）——本工程中按原版语义接活或对齐。

## 3. 阶段计划（顺序已确认）

每阶段流程固定：**逐文件对照分析（智能体并行）→ 差异报告 → 实现对齐 → 1:1 移植测试 → 全量 pytest → git 提交**。

| 阶段 | 范围 | 对照基准 | 原版测试量级 |
|---|---|---|---|
| P1 | `dsh/cordis/*` 全部 + harness 装配 | `vendor/{cordis,cosmokit,schemastery,hmr,include,loader,group,timer,logger-console}` + `boot/app-boot` + `boot/cmdline` | vendor test/ + app-boot specs |
| P2 | `dsh/core/*`（session, system_prompt, tools, agent, agent_loop, scope, surface, persona, inbox, tool_calls...） | `packages/core/*` | ~2.6 万行 specs |
| P3 | `dsh/session/*` | `packages/session/*` + `packages/session-query/*` | ~2.2 万行 specs |
| P4 | `dsh/host/*`（apiproxy 按现行 gateway 语义重写、webserver、client_modules、frontend_static、directory_picker、plugin_inventory） | `packages/api/*` + `packages/host/*` + `packages/client/connection` + `client/modules` 推导 wire 契约 | api/gateway+controllers+connection specs |
| P5 | 能力插件逐组：fs, shell, todo, skill, web, interaction, context, compaction, plan, goal, guard, jobs, spill, workflow, team, subagent, mcp, acp, attachment, credentials, settings, storage, workspace, identity, diagnostics, llm, extensions | 对应 `packages/<group>/*` | 各组 specs 全量 |
| P6 | 补缺包（第 1 节列出的从未移植集合） | 对应原版包 | 对应 specs |

P4 完成后必须做一次真实 GUI 冒烟：`dsh.py --web` 启动，人工验证设置、模型选择、会话列表、审批、提问等按钮行为。

## 4. 工作方法

### 4.1 智能体分工
- 每个插件（或插件组）派 1 个对照分析智能体（explore/general）：逐文件读原版 `src/*.ts` 与移植版 `*.py`，产出差异报告：缺失行为 / 语义漂移 / 事件与 effect 顺序差异 / 配置项差异 / 错误处理差异；标注允许的 py3.8/win7 偏离点。
- 实现与测试移植由主会话统一执行（保证跨插件一致性），大块独立修复可派 general 智能体并行。

### 4.2 测试移植规则
- 目录：`tests/1to1/<group>/<pkg>/test_<spec名>.py`，与原版 spec 文件一一对应；describe/it → class/test_ 函数，保持原名（snake_case）。
- 断言 1:1 语义对齐（含错误类型、事件序列、日志文本等价物）；原版 test-support（llm-mock-server、agent-loop-testkit、session-snapshot 等）先移植为 `tests/1to1/_support/`。
- Node/TS 特有且无 Python 对应的用例（如 ESM 加载、tsconfig paths），在文件头注释记录跳过原因；其余不允许静默省略。
- Win7 不可行的用例（bash 等）按原版 windowsUnsupported 名单同样排除。

### 4.3 验证协议
- 每阶段结束：`.venv\Scripts\python.exe -m pytest tests` 全绿（旧 728 + 新 1:1）。
- 语法基线：所有改动文件通过 `py -3.8`（或 venv python 3.8）`compileall` 校验。
- P4 后加 GUI 冒烟清单（设置/模型/会话/审批/提问/目录选择/插件清单）。

## 5. 提交策略

每阶段完成且全量测试通过后创建一个 commit（消息格式 `P<n>: <阶段名> 1:1 alignment + tests`）。设计文档与阶段报告随所属阶段提交。

## 6. 风险与对策

- 规模风险（29 万行测试）：按阶段推进、每阶段独立可交付；测试移植与实现对齐同阶段闭环，避免实现漂移积累。
- wire 契约推导风险（P4）：以 `packages/client/connection` + `client/modules` 的前端源码为契约权威，后端实现以能通过原版 api/gateway 的 spec 为准。
- Python 语义差异（JS Event/Proxy/finalizationRegistry 等）：cordis 事件/生命周期用显式 API 等价实现，偏离点逐条记录在阶段报告。
