# 跨语言迁移的智能体组织方案评估

日期：2026-09-26。范围：公开一手案例研究、Git 状态盘点、下一代迁移方案设计。本文记录调研阶段，随后的分支收尾见 [基线整合记录](2026-09-27-consolidated-baseline.md)。尚未安装新编排系统或恢复旧任务。方案效果尚未通过本项目对照实验验证。

新基线建立后的操作协议与持续上游跟踪方案见 [持续对齐工作流评估](2026-09-27-continuous-parity-workflow.md)。该文补充契约依赖、跨模块变更闭包、任务状态及证据失效规则，并建议先用单执行者跑通记录和验收，再开放多智能体并行；本文的执行器组合保留为候选，不作为先决条件。

## 建议

放弃以 Goose 多阶段角色链为中心的迁移组织方式。采用「上游可执行基准 + 单一架构决策所有者 + 按契约分区的并行实现 + 独立验证 + Git 合并队列」。代理运行器可替换，迁移事实保存在仓库和测试产物中。

首选落地组合：Codex SDK 驱动独立工作线程，Git worktree 隔离，仓库内契约与测试映射，GitHub PR/CI 承担集成。先跑 2 个实现 worker，按实测增加到 3–4 个；数字是试点建议，不是行业最佳值。需要不同模型交叉评审时接入 Claude Agent SDK；在确认需要无人值守的依赖领取后再接 Beads，避免第一天同时引入多个控制系统。

工程运行环境与产品运行环境分离：编排和上游 Node 基准可在现代开发机/CI 运行，交付物继续严格满足 Python 3.8.10、Windows 7、Cordis 插件语义和既定 GUI 兼容目标。现代系统上的测试通过不等于 Win7 验证。

## 一手案例与证据边界

### Codex CLI：TypeScript → Rust

官方迁移公告选择新旧实现并存：TS 继续修 bug，Rust 以 native 预览逐步达到功能与体验一致，并设计跨语言协议。可借鉴的是渐进替换和协议边界；公告没有披露完整迁移代理编队或对照数据，不能据此认定某种 swarm 导致了成功。

来源：[官方迁移公告](https://github.com/openai/codex/discussions/1174)。

### Pi Agent Rust：TypeScript → Rust

公开的历史迁移材料分开记录源结构、目标设计、功能计划和兼容测试。兼容测试包括执行 TS 后捕获输入输出 fixture，再在 Rust 侧重放。其协作生态以 Beads 管任务和依赖、Agent Mail 管通信和文件预约。

但当前 README 明确不再追求原版 Pi 的严格 drop-in 替换；历史计划还主动排除了 Web UI 等范围。历史 CONFORMANCE 文档也不能当作全部测试已经落地的证明。借鉴其机制，不接受其范围缩减作为本项目的验收标准。

来源：[原始迁移计划](https://github.com/Dicklesworthstone/pi_agent_rust/blob/main/docs/planning/PLAN_TO_PORT_PI_TO_RUST.md)、[源结构说明](https://github.com/Dicklesworthstone/pi_agent_rust/blob/main/docs/planning/EXISTING_PI_STRUCTURE.md)、[兼容测试设计](https://github.com/Dicklesworthstone/pi_agent_rust/blob/main/docs/planning/CONFORMANCE.md)、[当前目标声明](https://github.com/Dicklesworthstone/pi_agent_rust)、[协作约定](https://github.com/Dicklesworthstone/mcp_agent_mail/blob/main/AGENTS.md)。

不照搬「读完规格就不再看上游」的做法：规格用于索引和压缩，上游固定提交及其可运行行为仍是兼容性权威。文档缺漏不能成为合法偏差。

### TypeScript 编译器：TypeScript → Go

这是大型跨语言迁移案例，不是已证明的多智能体迁移案例。贡献指南明确使用固定提交的 TypeScript 子模块作为测试和代码生成来源；迁移仓库按能力列出状态，并将有意差异单独记录。

本项目可以直接借鉴：固定上游 SHA、沿用官方测试语料、按原始测试案例核算覆盖，不用新增 Python 测试总数替代迁移完整率。

来源：[迁移公告](https://devblogs.microsoft.com/typescript/typescript-native-port/)、[贡献指南](https://github.com/microsoft/typescript-go/blob/main/CONTRIBUTING.md)、[迁移仓库](https://github.com/microsoft/typescript-go)。

### Anthropic：并行代理编写 Rust C 编译器

这是从零实现实验，不是 TS 迁移。代理在编译 Linux 时撞上同一阻塞，16 个代理也不能有效并行。作者加入 GCC 作为已知正确的对照编译器，让不同文件由不同编译器处理以定位缺陷，再以差分缩减寻找组合失败。

启发：外部正确性基准和失败分解能力决定有效并行度。文章也明确产物不是完整的生产编译器替代品。

来源：[工程报告](https://www.anthropic.com/engineering/building-c-compiler)。

### Cursor：长期代理工程与 Rust SQLite 实验

2026-02 报告的组织演进：共享文件自协调失败；固定 planner/executor/judge 流水线僵硬；包揽所有职责的持续 executor 又过载；随后采用分层规划者、独立工作副本和异步交接。其研究分支容忍暂时错误，这不等于可以降低本项目发布门禁。

2026-07 后续实验进一步让设计决策有明确所有者，并通过共享设计文档解决分歧、专门处理合并冲突、拆解热点大文件、采用不同评审视角。SQLite 测试集通过率是受限实验指标，不等于 SQLite 完整兼容认证。

来源：[组织演进](https://cursor.com/blog/self-driving-codebases)、[后续实验](https://cursor.com/blog/agent-swarm-model-economics)。

两个时间点的方案不同，不能将“去掉 integrator”或“增加 reviewer”当作普适规则。

## 目标组织与职责

1. **架构/契约所有者**：固定范围、确定公共接口及运行时语义、分配任务、处理跨分区设计分歧。不替所有 worker 写代码，也不承担进程管理。
2. **实现 worker**：每个工作树负责一个完整的行为单元及必要消费者。允许读取全仓库；重叠写入通过任务分配控制，不能因为目录限制而截断必要修复。
3. **验证 worker**：依据上游、官方测试和反例检查候选。复用有效证据，检查新增风险；不把完整历史聊天灌入每次评审。
4. **确定性运行服务**：启动/取消/恢复会话、任务认领、记录进程和费用、运行测试、保留产物。处理字段错误和基础设施失败，不让模型重新诊断已知的格式问题。
5. **合并队列**：在最新集成基线上验证候选。无冲突则机械合并，有语义冲突才交给实现 owner 或临时冲突处理代理。

核心设计决策只能有一个 owner；实现和反例探索可以并行。不得让两个代理各自发明 EventBus 调度模型，再指望 Git 解决概念冲突。

## 按可验证行为拆分

旧包列表仍可做覆盖目录，但不直接等同于执行任务图。建议分两层：完整目标清单用于防漏，滚动任务队列只展开当前可验收的一小批工作。

初始分区：

- 运行时基础：Context、inject、effect、事件分发、Fiber、Timer、Loader/HMR 的关联契约；强耦合变更由同一 owner 统一设计。
- 会话与协议：事件记录、projection、persistence、repair、RPC envelope。
- 工具与 provider：在已确定的接口下拆成互不重叠的小批任务。
- Web：保留 React/TS 前端；围绕 HTTP/RPC/SSE 边界验证 Python 后端和浏览器完整流程。

按纵向切片交付，例如「启动最小 profile → 发起一轮 → mock LLM → 工具执行 → 会话落盘 → 重启恢复」。这是阶段验收顺序，不是取消其他 profile 和功能。

核心尚未完整通过时，下游可以做源码分析、测试提取和基于稳定接口的实现；不得把替身或局部模拟的通过标为真实集成完成。

## 可执行兼容性基准

迁移资产优先级：可运行上游 → 官方测试映射 → 共用场景与差分 runner → 文档索引 → 模型报告。

每个契约至少记录：稳定 ID、上游 SHA/源位置/官方测试、对象身份与所有者、状态变化和事件偏序、Python 适配规则、消费者、验证命令、明确剩余缺口。

两侧运行同一场景，比较返回值、错误、消息格式、事件顺序与资源生命周期。仅规范化确定无语义的字段，如临时根路径和生成 ID。不得通过对事件排序、丢弃异常等方式抹掉真实差异。

LLM 和网络可通过录制的协议输入固定；流式分片、失败、取消仍需覆盖。涉及生产 provider 的验证另列，不用现场随机模型回复作为严格差分依据。

JS/Python 异步差异必须有独立的测试场景：多监听器、有/无 ambient loop、pending 时再触发、重复取消、局部 dispose、根 teardown。使用事件屏障构造交错，时间限制用于发现挂起。

每个修复保留旧实现失败、新实现通过的证据。通过计数不能代替官方用例对应关系；未迁移、需凭证、平台限制必须分开登记。

## 技术栈选择

| 层 | 首选 | 理由与边界 |
|---|---|---|
| 编码执行器 | Codex SDK，必要时 exec 子进程 | 复用会话、工具、上下文和恢复能力；运行器版本固定 |
| 异构验证 | Claude Agent SDK，按需接入 | 独立工具链和模型视角；本项目尚无比较胜率 |
| 持久事实 | Git 中的契约、任务定义、测试映射；PR/CI 状态 | 更换执行器不丢迁移资产 |
| 无人值守任务依赖 | 必要时 Beads，单一任务状态权威 | 不同时让 Beads、PR 标签和自建数据库各决定任务是否完成 |
| 通信 | 短结构化交接，原始轨迹存档按需读取 | 小规模无需先部署全套 Agent Mail/tmux 网络 |
| 并行隔离 | 每个实现任务独立 worktree | 验证器绑定提交或工作树内容指纹 |
| 集成 | GitHub PR/CI；以真实合并候选为门禁对象 | 同时检查 product、Python 3.8、Windows 和 portable |

Codex 官方把 SDK 定位于任务自动化和 CI；完整 app-server 更适合自建交互式客户端。本项目起步无需先重建控制台。[Codex SDK](https://developers.openai.com/codex/sdk/)

Claude Agent SDK 暴露 Claude Code 的工具、会话、hooks 和子代理能力，可作为可替换执行适配器。[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview)

Gas Town 是现成的较重候选，具备工作区和多角色管理，但完整流程涉及 tmux、Beads/Dolt 等，原生 Windows 与完整 Linux 流程有差异。就当前少数模块和并行槽位而言，不优先引入整个控制平台。[Gas Town](https://github.com/gastownhall/gastown)

上述是适配本项目的工程判断，不是声称某 SDK 在所有模型、预算和仓库上最快。先建立统一任务基准，再比较执行器；核心指标是每单位时间/费用新增通过的契约，而非提交数、token 数或角色数。

## 旧成果收尾与切换

以下为 2026-09-26 调研时的历史盘点；后续整合、快照去重与最终验证见 [单一迁移基线整合记录](2026-09-27-consolidated-baseline.md)：

- GitHub open PR 列表为空。
- 远端默认分支为 master。远端 main=ebc2cd45，远端 master=59f52c7f；本地主工作区 master=dd3bc48b。
- 本地 main/master 分叉，独有提交计数为 31/138，不能以重命名或覆盖操作代替合并审计；计数也不等于独立产品改动量。
- 多个 candidate 分支指向相同集成提交，不能当作各自独立的成果依次合并。
- 旧 Cordis 工作树 `.goose/runs/project/worktrees/ddde47acaddc` 有 49 个已跟踪文件的未提交改动。本次没有完整盘点其未跟踪/忽略文件，也没有判断这些改动是否已被后续候选覆盖。
- 旧任务库的 INTEGRATED 指内部集成状态，不等于已发布到远端 main。

建议切换顺序：

1. 保存所有待收尾工作树的可恢复快照，纳入必要的未跟踪文件；核对忽略文件中是否有唯一证据。保留原提交和上游基线。
2. 按 patch 和行为去重，选择最新有效的 Cordis、Timer、Schemastery、Settings、Web 等成果；不能仅按分支时间或任务库 PASS 选取。
3. 创建统一收尾候选，以实际远端默认分支 master 为目标；保留旧 main 独有的产品变更，整合 master 中需要的修复，单独处理未推送差异。
4. 对缺口做有限收尾，修复现有 portable 基线失败；通过专项、全量和打包检查后集成到 master。目标系统验证单独登记；未完成模块以代码/测试和精确缺口保存，不虚报 1:1 完成。
5. 旧 .goose 运行库归档为证据；新流程只导入已验证契约、未决缺陷和代码来源，不搬运轮数、候选状态机和完整历史上下文。
6. 在新流程跑一个运行时单元、一个独立插件、一个端到端切片，完成真正的 PR 合并闭环，再扩大并行。

切换成功标准：会话中断可恢复且不重复实施、格式问题不触发语义返工、契约变动仅使受影响证据失效、合并结果可追溯、真实行为覆盖增加、Win7/portable 无回退。

## 验证说明

调研阶段仅新增本文件，未修改产品或运行器。当时主工作区的历史检查结果为：1853 passed、1 failed、1 warning，157.58 秒。失败为 `tests/test_portable_smoke.py::test_smoke_dist_portable_directory`，旧 dist 启动器不识别 `--profile minimal`；日志 `.goose/assessment-20260926-tests.log`。这不是整合后基线的验收结果。整合阶段的完整回归与未验证边界单独记录在 [单一迁移基线整合记录](2026-09-27-consolidated-baseline.md)。
