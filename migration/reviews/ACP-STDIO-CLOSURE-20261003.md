# Canonical ACP stdio 有界闭包

固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；干净产品候选 `5edf7e22fbc4a0a9c4c74115688b266525614879`，Python 3.8.10、当前 Windows。完整门禁 passed / publishable=true；没有推送、公开发布或整体 accepted_upstream。

## 接受范围与源依据

`CON-ACP-STDIO@1` 接受原 SDK 1.4.0 的 NDJSON framing、split UTF-8、尾行、typed id、batch、错误、取消与 outgoing correlation，九个实际挂载方法的参数解释器，以及 canonical acp-app startup / readiness / 可撤销输入和 stdout。解释器数据绑定固定 SDK Zod/deserialize 源 SHA；运行时不依赖 Node。27 个选择驱动中的新增 SDK 驱动保留 906 项两侧原始观察，不归一化错误或字段；十类观察器破坏反例均拒绝。

真实 canonical Agent 进程验证两个 Session 并发、协议/Session 取消、活动 EOF、关闭排空与新进程恢复。关闭在既有五秒 ProcessShutdown 边界内先 serial app/stopping，撤销 ACP 请求与 Agent 并等待 projection-cache 待写任务，再执行 fiber teardown；这是显式 Python 调度适配，不是新原版 bug 例外。注册均可撤销，不关闭调用者句柄。

十五份当前候选证据只重新签发各自已有有界合同；不扩张 Cordis、Agent、Session projection、Spine 或 Portable 的历史认证范围。父任务 `MIG-ACP-TRANSPORT-002` 仍为 draft。

## 完整门禁与产物

完整 `.venv\Scripts\python.exe -m pytest tests`：**4971 passed、6 skipped、1 warning、0 failed**，1108.79 秒。十四条必需 browser/Portable/ACP 进程 lane 均通过且没有跳过。六组未改动原版源码断言 80 + 100 + 197 + 100 + 139 + 3 = **619**；**27** 个选定双侧驱动通过。八类既有精确原版 bug 谓词及 C58 边界未改变。

实际发行 ZIP 解压后 runtime 13 步、原版 browser 5 步、两个 ACP 子进程九步、119 frontend 输入校验通过。发行 ZIP SHA256：`1f14798af291318a3e4f139c15b46e51b15af34ff14dbf42f5fcc96b810b025e`。冻结输入 SHA256：`52e86d6d1d14121add6432b76e239c63e836084e303563d2b6fd594b6fc4d3ac`。证据包 `migration/evidence/artifacts/ACP-STDIO-20261003-5edf7e22.zip` SHA256：`48724d745fcdd8e41570bbca4af89f3bcf65061f5ee94adcb874efb4ccb6fff1`，含回执、JUnit、完整输入、源码观察、原始配对输出及先前失败。

首次全量的五个过时 registry 断言失败、早期 process/observer fixture 故障、dirty Portable 专项预览均保留，不能冒充本次通过证据。最初实际 EOF 的关闭后存储写入警告经提供端/消费者共同修复后才验收；不靠日志过滤或重试消除失败。

## 后续未闭环项

A4：真实 MCP stdio/HTTP/SSE 提供端、一次性权限、subagent 消费者和后代关闭。实际原 SDK 缺失 executable 失败，而当前 Python MCP stub 返回空 tools / 虚构调用成功，已保存否定证据。原版 ACP 对缺失/未知 permission outcome 判别字段却携带 allow-once 的响应错误授予权限；原始 source probe 已归档为未接受发现，不属于既有八类例外，也不构成原始匹配证据。

B/C/D：完整 domains/history/cache/FTS、Tools/Wire、profiles、OAuth/云、JS/SDK、扩展交付、职责覆盖、无缓存安装仍保留各自退出条件。本次没有 --prepare、远程 Actions、付费远程模型或暂缓的 Win7 真机认证；当前 Windows 通过不替代这些范围。
