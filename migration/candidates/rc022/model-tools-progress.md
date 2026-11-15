# C5 模型与工具执行进度

固定目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。2026-11-15 更新。
本页索引分批定向验证，不是整版、完整回归或发行验收。

当前已跑通选中的 PTC 执行器、实际受限 Python 进程、嵌套工具和 v4 Session 日志。Windows 本机实际验证工作区/只读/越界写入、内存和进程树回收；固定原版 Node 与 Python 的文件策略旅程也已配对。默认仍为每次调用创建独立进程，未实现或宣称可选的持久 Python 求值模式。

| 单元 | 已验证边界 | 检查记录 |
| --- | --- | --- |
| 前置模型 | 固定模型选择与调用准备 | [模型选择](model-selection-checks.json) |
| C5-A | 按步解析和执行准入 | [工具准入](tool-admission-checks.json) |
| C5-B | 显式执行器选择 | [执行器选择](executor-selection-checks.json) |
| C5-C | Native 批次与并行 | [Native 批次](native-batch-checks.json) |
| C5-D | 单步模型/工具准入 | [单步准入](step-admission-checks.json) |
| C5-E | 运行时上下文刷新 | [上下文刷新](context-refresh-checks.json) |
| C5-F | 未结束工具恢复 | [工具恢复](tool-recovery-checks.json) |
| C5-G | 内容投影、前后策略与取消 | [工具流水线](tool-pipeline-checks.json) |
| C5-H | 工具历史与模型更新 | [模型工具更新](tool-updates-checks.json) |
| C5-I | 执行器拥有策略流水线 | [独立流水线](pipeline-source-checks.json) |
| C5-J | 完整 PTC 调用和重置所有权 | [调用所有权](ptc-calls-checks.json) |
| C5-K | Python SDK 提示词 | [Python SDK](ptc-sdk-checks.json) |
| C5-L | Python 进程能力与期限 | [进程能力](ptc-runtime-checks.json) |
| C5-M | 嵌套调用有序调度与日志排空 | [嵌套调度](ptc-dispatches-checks.json) |
| C5-N | TypeScript SDK 提示词 | [TypeScript SDK](ptc-ts-sdk-checks.json) |
| C5-O | 选中的 PTC 执行器和私有工具入口 | [执行器接入](ptc-executor-checks.json) |
| C5-P | 策略变化后的进程回收 | [策略所有权](policy-processes-checks.json) |
| C5-Q | 消息、排队写入和绑定流量上限 | [有界通信](ptc-protocol-checks.json) |
| C5-R | 控制与输出分离、进程树收尾 | [独立通道](ptc-control-checks.json) |
| C5-S | 无嵌套 Job 的 Windows 资源适配 | [Windows 所有权](ptc-windows-checks.json) |
| C5-T | 真实策略隔离、提权和 Session 消费者 | [受限提供端](ptc-confinement-checks.json) |
| C5-U | 默认/可选执行器的真实 Loader 装配、旧配置退役 | [执行器装配](executor-composition-checks.json) |

后续继续闭合 C5 启动时模型恢复的消费者集成，再推进 C6–C9。生产 pin、原样前端和注册表仍在 C9 协调切换；`accepted_upstream` 不随上述定向结果变化。共享 Source/工具链保留到 C9；各运行的可重建工作区已按记录清理，真实观察、原始失败和检查回执保留。
