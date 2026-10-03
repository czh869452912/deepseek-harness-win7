# MCP 关闭中的 generation 与队列第七部分

固定原版 cd5ef8148158c3a752a658978873241fdf8e2bbc。本部分先在隔离树实施，现移入主树独立推进；第五与第六提供端仍等待共同验收，本部分 MIG-MCP-DISPOSAL-012 running，未 integrated。六组实际原版 startConnection/syncTools 通过已声明的 SDK Client、fetch deferred 屏障观察，另有一组不 mock SDK 的实际非法 URL 工厂关闭。没有修改原版前端或扩展九类原版 bug 例外。

## 实际差分

首轮六个 supervisor 场景中，connect-resolve、connect-reject、resync-reject 已匹配；initial-list、resync-list、queued-resync 的 Native 额外 after-fetch isCurrent 检查丢弃已经进入队列的 swap。原版要求先完成已接纳的 unregister/register，再由 awaited dispose 清理迟到结果；其 reconnect.spec.ts 原样用例也明确记录这一顺序。仅最终 registry 为空不足以证明所有权时序匹配。新的观察保留 create/connect/close/fetch/register/unregister 完整序列、before/after registry、ready error 和日志，不把三组中间差异正常化。

实际 SDK 工厂在非法 URL 抛错之前已分配 Client 和 close barrier。立即 dispose 应拥有该未关闭 generation，五秒后产生 shutdown-may-be-incomplete 诊断。Native 工厂抛错时没有保存该所有权，丢失关闭诊断。修复保留未连接 generation 的空关闭接口与真实未结算 barrier，由原有五秒 barrier 和 dispose 决定关闭结果，不伪造 close 回调、实际子进程或成功结果。

Native 队列入口继续拒绝已经失效的 generation；只撤销额外的 fetch 后检查，使已经接纳的 swap 在 awaited dispose 排空前完成。两条排队 notification 的第二个任务仍被入口拒绝，不新增 tools/list，最后 registry 为空。

## 当前证明与边界

修复后七组完整原始观察匹配；原始 v1 差分和 v2 修复观察保存在协调树 `.goose/out/acp-a4-work/mcp-disposal-*`。正式 `mcp_disposal_oracle.py` 使用字面 specification、独立新鲜原版/Native 进程及冻结输入，七项通过。配对、17 项反例和既有 supervisor 合计 53 passed；反例拒绝迟到交换丢失、未清理工具、额外 queued fetch/close、弱 generation 类型、迟到错误日志、工厂诊断丢失及外国模块/错误 Python 来源。

六个 SDK mock 场景证明 supervisor 在明确 async admission 屏障的 contract；它们不是实际 TCP/stdio 网络中断证据。第七项使用真实原版 SDK 和 Native HTTP URL 工厂，但没有成功连接外部端点。没有认证 SDK 全量 HTTP/TLS/重试/replay/URL、无限阻塞、异常关闭流、完整 subprocess tree 或用户延期 Win7。

完整隔离树 MCP 回归 516 passed、5172 deselected，102.84 秒；另有隔离树既存 pytest-asyncio 配置提示，原始日志保留。主树门禁接入 85 必需 lane、34 个 paired driver 和实际解压七场景服务消费者，来源与完整 transient swap/factory diagnostics 不可省略。未执行本部分实际解压、完整候选门禁或 clean acceptance；根据两次第五 browser 失败调整顺序，先分别提交已验证产品修复，再以共同干净候选签收各自有界合同。

主树新鲜 source/observer/supervisor/门禁 234 passed、23.05 秒，正式主树 driver 七项通过，migration check 与 diff check 通过。产品修复独立提交，任务仍 running；未宣称实际解压、完整共同门禁或 Web 启动根因已完成。
