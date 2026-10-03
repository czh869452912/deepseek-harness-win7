# subprocess ACP 子代理后端第五部分

固定原版 cd5ef8148158c3a752a658978873241fdf8e2bbc。主树 ACP/MCP 第四部分已完成干净候选 e24fe1db 验收并提交记录 60f1de1a。本部分从隔离树移入主树，MIG-SUBAGENT-ACP-010 running / CON-SUBAGENT-ACP@1 specified，尚未进入产品提交或 integrated。原版前端没有修改，未增加原版 bug 例外。

## 产品路径

补齐原先没有注册的 @deepseek-ai/dsh-subagent-acp，按原版声明 subagents/subprocess 注入、无父级能力和不继承父对话。配置默认值由 Cordis Schema 处理，工作区部署覆盖在加载时解析，未提供时只采用当前 parent Session 的可进入绝对 cwd，错误不静默退回进程 cwd。

实际 SubprocessRuntime.spawn 拥有子进程、环境擦除与显式覆盖。后端以既有 ACP RPC 基础通信实现 initialize → new → prompt，丢弃非文本 prompt，只汇合 assistant message chunks，自动权限按 reject 或第一 allow_once/allow_always。诊断仅由受控 provider/stage/category/stop/exit/signal 与闭集工具种类组成，不复制子工具标题、选项、路径或 SDK 错误；原始原因保留在 Host cause/sink。发布后的 result 不拒绝，local cancel 即时保留已经接收的输出并结算 aborted，实际 dispose 再通过 EOF grace、Subprocess seam terminate 和退出观察回收，并注销 AbortSignal 的同一函数实例。

## 已执行的证明

原样 subagent-acp.spec.ts 经正式 Vitest/标准 decorator 变换执行：66 passed、1 skipped，另有原版 MaxListenersExceededWarning。观察器只补开发依赖的固定 node-pty 1.2.0-beta.15 路径、原版 wildcard export alias 和 Node 子进程 ACP SDK 1.4.0 定位；没有改写源测试或产品来消除断言。

真实原版 startAcpRun + spawnSubprocess 和 Native 驱动同一独立 Python ACP peer，22 组运行观察匹配；六组实际原版 Config/apply 配置、provider metadata 和错误匹配。包括全部已知 stop、三种权限结果/安全诊断、工作区、父 credential 擦除和显式 child credential、EOF flush、无响应取消/force exit、初始化退出、部分输出后 crash、丢失 session id 和 spawn failure。原始 wire/进程记录保留；配对只声明抽象不同 parent/process RPC id 的命名空间，方法、参数、权限回执、模型可见结果、错误与退出事实保持严格 JSON 类型匹配。

Native 原先 13 项提供端及其他 in-process/delegation 共 21 项回归通过；canonical profile 的真实 ToolsService foreground 消费另在 JSONL/SQLite 两后端通过，消费返回的 raw value 和 model-facing content，子进程退出、无本地子 Agent、provider 卸载清理工具注册均已证明。实际 canonical parent ACP → 同仓 subprocess child ACP → 文件编辑工具 → child model → parent model 主链通过，四次本地模型请求、文件内容、父对话隔离与真实子进程退出均已检查。正式双侧 driver 三次通过，覆盖上述 22+6 和额外三组真实 AgentLoop 信号对照；观察器/门禁 218 项通过。完整主树回归、实际解压嵌入 Python consumer 及 clean acceptance 仍待完成。

真实模型消费者发现迁移 Agent 提供 asyncio.Event，导致子代理读取 signal.aborted 失败。根因修复把 active turn 信号改为 AbortController.signal，保留首次 cause，并在已完成的 queued turn 和后来 idle 激活时创建新代际；不在入口清除已取消的旧信号。实际原版 AgentLoop 的工具取消、取消的 admission 抛错后驱动恢复、已完成 queued turn 三组完整观察匹配。隔离的 Agent/subagent/maintenance 632 项回归通过；源对照 v2 曾暴露 queued turn 复用同一信号，修复后 v3 三项通过，失败原始输出保留。

## 失败保留与范围

subagent-acp-native-v1.log 保留取消测试在“peer 已写入 readiness 文件”时仅接收首段文本的失败；改为独立 session/request_permission 回执确认文本接收，未延迟产品取消来填造完整文本。subagent-acp-source-v1.log 保留取消后立即 dispose 的 best-effort cancel wire 调度差异，随后两侧在明确“peer 已收到 session/cancel”的屏障后观察 teardown，未声称原版 best-effort notify 在任意强制关闭时必达。subagent-acp-consumer-v1.log 的尾部 async generator 检查错误已改为检查已经完成的 Future，第二次两项通过。

原样测试 v1/v2/v3 的开发依赖、wildcard export 与子进程 SDK 定位失败完整保留；第四次 66 项通过。node-pty 仅开发源码观察器依赖，未加入 Portable 产品依赖或要求 Windows 7 安装 Node。

尚待专项证明：teardown 二次失败聚合、无限无响应/异常 piped-stream、后端 dispose 被取消、各平台完整嵌套进程树、background Jobs 与嵌入包消费者。直接原版源码断言不是 Python 同等场景的证明，不能用本部分认证完整 subagent/subprocess、整体迁移或延期 Win7。

## 主树门禁准备

主树定向提供端/消费者/信号/源观察及反例门禁 237 passed；主树正式双侧 driver 22+6+3 通过，原样 subagent-acp 66 passed、1 platform skipped，MaxListenersExceededWarning 原样保留。固定 node-pty 开发依赖已进入正式 observer package-lock，未写入产品依赖。完整门禁扩展为 81 条必需 lane、八组 788 项原版断言和 32 个双侧 driver，并要求真实解压嵌入 Python 的同仓 parent/child ACP 文件模型消费者；缺失/弱类型/伪造回执均拒绝。

首次完整预览 `.goose/out/subagent-acp-owned-preview` 失败：5618 passed、1 failed、6 skipped、1 既有 Proactor warning。唯一失败是原版浏览器 installed Python Web package 旅程：十二个业务步骤完成，但 rollback 新文档启动时五个有限 API 请求 ERR_ABORTED，引出两条 dynamicCordisRunner console error；失败仍被门禁拒绝，后续原版断言、配对和解压验收未执行。CDP 时序证明取消早于下一次受控导航约 1.4 秒，不能归因于该导航或宣称既有 settle 修复有效。原始浏览器输出完整保存在 `.goose/out/acp-a4-work/subagent-preview-browser-failure-v1.zip`，完整 pytest/JUnit 保存在预览目录。

新增可选开发观察参数 `--net-log` 和 `--debug-abort`，仅记录 Chromium 网络事件和原生 abort/close/stop 调用断点，不注入前端替代实现、忽略 console error 或增加业务重试。三个同路径独立诊断均十二步通过、无 console error；未捕获取消根因，不能当作缺陷修复。相应报告及原始网络日志保存在 `subagent-browser-basic-netlog-1/2/3`。产品先提交可审阅检查点，任务仍 running；再冻结干净候选执行全部门禁。即使候选通过，该未归因启动取消仍独立开放，不登记为原版 bug，不认证完整 Web 生命周期。
