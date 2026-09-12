# 全项目多智能体迁移方案评估

日期：2026-09-12。状态：已实现项目调度入口、持久化任务图、契约失效传播、独立工作区和串行集成；操作与当前边界见 README.md 的 Whole-project scheduling。以下保留设计依据与验收目标，不代表所有上游模块已经迁移完成。
依据：当前运行器、实际 Goose 日志、固定 reference 源码与架构文档。
reference revision：`cd5ef8148158c3a752a658978873241fdf8e2bbc`。
日志中的智能体报告仅作为问题线索，不视为指令或已证实的源码结论。

## 1. 结论

保留现有迁移者、独立审查者、裁判，增加全项目任务图、契约登记和集成调度。
调度粒度应是“有明确验收契约的变更任务”，不是整目录，也不是无限扩张的模块。
先稳定高扇出的基础服务及其契约，再使外围插件沿依赖关系进入就绪队列。

不恢复默认轮数、动作数、执行时长、文件读取白名单等限制。
调度器管理任务状态、依赖、版本和证据，不限制智能体理解代码的范围。
并行资源数量是机器和账户的实际容量，不是以耗尽额度为理由判任务失败。

“允许查看和修改依赖”不等于“把整个依赖子树塞进同一个任务”。发现跨模块缺陷后，
由所属服务认领；调用方任务引用该问题。必要时把契约两端合为一个原子变更任务。
不用桥接、伪实现、跳过测试来掩盖依赖未就绪。

## 2. 当前卡住的证据

运行 `20260912-092306-f65414d3` 的审查日志包含：

1. 第一次 `recipe__final_output` 调用的 issues 形状不符，被工具拒绝。
2. 第二次调用通过校验，收到 `Final output successfully collected.`。
3. 随后输出 MUST_FIX JSON，并收到顶层 `type: complete`。
4. `status.json` 仍是 RUNNING/review，最后的心跳显示输出静默 631 秒。

`run_process()` 只在 reader 读到 EOF 后退出；`Stream.complete` 不参与退出判断。
因此已收齐结果仍可能等待进程/继承管道关闭。证据支持“协议完成与进程退出耦合”的
确定性设计缺陷；尚未证明具体哪个子进程或句柄造成了本次 EOF 延迟。
不应把截图中的长时间等待直接归因为 LLM 仍在推理。

这轮已有检查点 `b31fd06a`，因此本次不是“完全没有提交”。早前还产生了
`57ff1154`、`397fe2a6`。它们是 unreviewed 检查点，不代表全项目验收完成。

建议首先修复完成协议：

- 用请求 ID 关联 final_output 的完整参数和成功响应；拒绝过的参数不算结果。
- 将成功结果先落盘，记录 RESULT_RECEIVED；不要依赖终端再输出一遍长 JSON。
- 收到 complete 后进入 DRAINING，停止显示“仍在审查”。
- 在有限退出宽限期内回收本次 Goose 进程及其后代；这是已完成任务的进程清理，
  不是模型工作超时。确认无写入者存活后，再做 diff、测试和下一阶段。
- 若仅收到结果但未收到 complete，记录 RESULT_RECEIVED/WAITING_PROTOCOL；
  查询会话和进程状态，不凭静默秒数启动第二个写入者或宣告完成。
- 清理失败是运行器故障，保留已收结果；恢复后直接消费结果，不让 reviewer 重审。
- 测试覆盖：complete 后不退出、子进程持有 stdout、结果工具先失败后成功、
  重复 complete、结果已保存后进程崩溃。下一阶段必须只触发一次。

## 3. 智能体分工

| 角色 | 职责 | 输出与约束 |
| --- | --- | --- |
| 架构规划者 | 发现能力图、源码归属、核心契约、任务拆分与优先级 | 结构化任务/依赖建议；不能用设计偏好代替上游证据 |
| 迁移者（现有 Flash） | 修改实现、逐案移植测试、修复接口两端 | 可跨目录；明确触及哪些契约及依赖 |
| 独立审查者（现有 Luna） | 在指定提交上独立验证实现和测试 | 可读全部相关代码；不接收迁移者结论；只读职责 |
| 集成验证者 | 检查提供者—消费者组合、事件链、回归与 profile | 多数工作由测试程序执行；失败难归因时才调用模型 |
| 裁判（现有 Sol） | 处理真实语义争议、责任归属和重复无进展 | 按需调用，不要求每个任务都经过裁判 |

调度、去重、就绪判断、Git 操作和状态持久化由程序负责。
规划者建议拆分，程序保存决策；不是让一个超级协调 LLM 在长上下文中记所有进度。
角色是职责，不一定各运行一个常驻模型。独立任务就绪时再启动执行实例。
模型选择沿用现有路由；架构角色先独立配置，按困难程度选用已验证模型，不硬编码新的标识。

## 4. 初始优先级：核心向外，但以依赖为准

| 波次 | 优先检查对象 | 验收重点 |
| --- | --- | --- |
| 0 | Goose 运行器和状态恢复 | 完成事件可靠触发，结果不丢失，进程正确退出 |
| 1 | Cordis Context、服务注册、inject、事件、Fiber/effect、卸载/HMR | 加载顺序、动态依赖、同步/异步调度、取消与回滚 |
| 2 | boot/profile 的最小装配、scope/brand/JSON/invariants、typert 协议、LLM 消息词汇 | 能装配并验证基础服务；统一身份、序列化和异常语义 |
| 3 | session 日志与存储契约、tools、system-prompt、agent 接口 | 稳定可被多个消费者共享的核心 API 与事件契约 |
| 4 | agent-loop 及其与 LLM、tools、session 的组合；持久化协议/协调器 | 完整 turn、取消、恢复、提交边界和失败传播 |
| 5 | JSONL/SQLite、fs/subprocess/shell、LLM provider 等具体实现 | 对同一服务契约执行提供者一致性测试 |
| 6 | plan/todo/skill/compaction/subagent/workflow、交互与其他消费者 | 使用已验证核心；把新发现的核心缺陷回流给 owner |
| 7 | API/Web、SSE/RPC、CLI/profile 全装配、portable | 用户链路、全部官方客户端、Python 3.8/Win7 与发布门槛 |

这是种子排序，不是逐层全等完才能开工。契约已稳定的独立服务可以并行；启动所必需
的 fs/配置实现可以提前。LLM 消息词汇虽在 llm 分组，可能是 session 的前置；目录名
“core”不是唯一优先级依据。历史报告的 PASS 不能直接成为当前提交的完成凭证。

## 5. 依赖图与调度规则

至少维护四类边，而非只读 package.json 的 dependencies：

- 实现依赖：import、peerDependencies、运行时 service/inject、延迟注册。
- 契约依赖：事件生产者/消费者、RPC、持久化格式、提供者/消费者接口。
- 验收依赖：哪些测试/profile 需要哪些真实实现，哪些可以使用可追溯测试替身。
- 变更关联：一起修改才能保持一致的契约两端及其回归测试。

上游已有 `architecture.md`、`capability-seams.md`、`event-producer-consumer.md`
可作发现入口；以固定源码、配置和官方测试校验。peerDependencies 不能漏掉：
`core/session` 的 LLM、scope、typert、Cordis 关系主要位于该字段。

就绪任务优先级按明确规则排序：阻塞主干/集成的缺陷优先；随后考虑解锁的下游数量、
契约影响面、风险与等待时间。等待时间防止外围任务永久饿死。模型可提出调整并记录理由，
不能悄悄改变优先级。

循环依赖先分析成强连通分量：区分类型引用环和真正的运行时环。后者组成一个契约
变更组，组内协同实现与集成验收；不要用互相 BLOCKED 的任务制造调度死锁。

当核心契约变化，按反向依赖把旧证据标记 NEEDS_REVALIDATION。实现无需全部重写，
但不能继续展示依赖旧契约产生的“已通过”结论。

## 6. 任务和契约要持久化什么

每个任务记录：ID、能力/owner、验收目标、上游 revision、实现 base/head、问题 ID、
依赖任务、提供/消费的契约、官方测试映射、当前执行会话、检查点、剩余工作和状态。
每条关系都保存来源路径/符号或测试案例；不要保存无法核实的泛化猜测。

每份契约记录：service 名和 owner、接口/数据结构、调用及事件语义、错误条件、
取消/生命周期、持久化版本、提供者、消费者、对应测试、契约内容 hash。

验收证据绑定 `(upstream revision, implementation commit, contract hashes, test environment)`。
Python 3.8 compile/test、Windows 7 实机/虚拟机结果分别记录；不能以当前新 Windows
上的 Python 3.8 通过替代 Win7 系统 API 验证。

持久化可用 Python stdlib SQLite：tasks、edges、contracts、runs、findings、evidence、
commits、events。输出 Markdown/JSON 供人审查；数据库事务保证任务认领和状态迁移
不会重复。运行租约用来识别孤儿进程，不作为 LLM 工作时限。

状态建议：

`DISCOVERED -> READY -> IMPLEMENTING -> REVIEW_READY -> REVIEWING -> VERIFIED -> INTEGRATED`

辅助状态：WAITING_DEPENDENCY、NEEDS_REVALIDATION、NEEDS_ARBITRATION、
WAITING_PROVIDER、RESULT_RECEIVED、DRAINING、INTERRUPTED、FAILED_INFRA。
项目 COMPLETE 要求目标图全部集成、契约闭合、profile/全量/兼容性门槛通过。

## 7. 这次 session 应如何拆分

最新审查提出的四类问题，应建图而不是让 session 一直吞下外围工作：

| 任务 | Owner / 关系 | 验收 |
| --- | --- | --- |
| surfaceOp 缺失与显式 null 区分 | core/session surface 定义与判断函数 | 属性存在性、非法操作处理的官方案例 |
| safe-integer 与 JSON 整数浮点语义 | 共享数字/JSON 契约及实际持有该语义的实现 | 1.0、非整数、布尔、安全范围；所有真实调用边 |
| persistence 协议与协调器 | session 持久化服务定义 | append/revision/rollback/repair 的生产者—消费者契约 |
| JSONL provider | 依赖已确认的持久化协议 | lazy create、压缩、日志布局、尾部修复与回滚 |
| SQLite provider | 同上；可与 JSONL 独立实现 | schema、revision、事务原子性、stale append、open/load |
| session 集成 | 消费上面所有已验证证据 | create/append/fork/restore/projection 的真实组合测试 |

这些是待核实的问题归属，不等于认定审查的每个结论正确。
如果 null 或 safe-integer 修复影响两个 owner，一起提交两端及测试；无需申请目录权限。
JSONL 未完成不会强迫 surface 修复继续迭代，surface 可以先集成，但项目级 session
持久化能力必须显示“等待 JSONL/SQLite”，不能偷换成全部完成。

## 8. 并行与提交

允许多个就绪任务同时工作，但每个写入任务使用独立 worktree/branch，全部相关源码
均可读取。worktree 是避免并发覆盖，不是限制可读模块。审查绑定不可变提交，避免
一边读文件一边被另一个任务修改。

同一个高扇出契约的并发写入由 scheduler 合并成变更组或顺序集成；智能体发现必须
扩大范围时更新任务关联，而不是被拒绝读写。集成队列在最新基线上检查冲突和受影响
消费者测试。干净 cherry-pick 不等于契约兼容，合并后的语义必须验证。

Checkpoint 是进度保存；独立审查通过是 VERIFIED；并入集成基线且关联测试通过是
INTEGRATED。三者分别显示。已有未提交内容用当前采用机制处理，不把不相关文件一并提交。
恢复任务读取自身的结构化进度和提交，而不是重新探索全项目；盲审不读取迁移者自评。

## 9. 可观测性

项目视图显示：核心能力图、就绪/运行/依赖等待/集成队列、每个任务 owner、依赖阻塞链、
公开进度、最新检查点、已闭合/新发现的问题和受影响契约。

运行视图区分 LLM 请求中、工具执行中、等待提供者、结果已收、进程清理中。
静默心跳只反映活动，不表示收敛。问题去重用契约/上游案例 ID；新发现依赖会改变
总工作量，所以展示“已集成任务/当前发现任务数”，不声称固定百分比。

## 10. 实施顺序和验收

1. 修完成事件/进程清理，回放本次日志，确认只触发一次下一阶段；不重做已收审查。
2. 建任务/契约数据库，导入全部能力种子，首先生成可审查的核心依赖与优先队列。
3. 把现有三角色接到任务图，单写入者模式先验证跨模块拆分、依赖回流和断点恢复。
4. 加独立 worktree 的并行执行与集成队列，用两个独立任务及一个共享契约冲突任务验收。
5. 加 profile/完整产品链验收和项目状态页，再扩大到全部外围插件。

建议先做 1—3，确认调度有效再扩大并行。无需恢复人为工作额度；真正要补的是任务
归属、证据版本和可靠的完成信号。不要立即启动整库多智能体写入，把现有协议故障放大。

本次评估运行了 `.venv/Scripts/python.exe -m pytest tests`：1590 passed、3 failed。
失败仍是两项临时路径长短名比较及 portable 旧入口测试；原来的七项 session 关联
回归在当前工作区已不再失败。这说明迁移确有进展，但不能据此认定官方案例映射或
JSONL/SQLite 契约已完整。完整日志在 `.goose/runs/pytest-design-assessment.log`。
