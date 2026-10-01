# Session preset / Client / Python Remote 联合交付

日期：2026-10-01。起点提交 `fe398207`，固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。运行环境为原生 Python 3.8.10、
当前 Windows 和开发机 Chromium。本记录补齐源码联合包的 Session placement，
不认证整个插件交付阶段、动态运行时治理、全项目迁移或 Win7。

## 所有权与调用

`cordis_export(... placement=session)` 产生的项目现在走同一原生
`dsh plugin --profile web build / pack / add` 流程。生成的 Host row 仅注册
包所需的 Client 发现和 Remote 路由；`python_session_source` 不在该 row 中评估
用户 Host 源码。作者把 `preset.fragment.yml` 添加到用户 preset 后，源码才在该
preset 的 standing mount 中执行。安装不改内置 preset，不自动挑选用户会话。

Host bridge 通过既有严格 Typert `agent` lookup 接收 `agentId`，调用注入的
`agentPresets.serviceFor` 获取目标 preset 的 handler。没有从全局服务取同名
handler 的 fallback。没有 Agent 身份的调用拒绝；未装配该插件的普通会话拒绝。
Bridge 卸载会撤销严格 descriptor，旧 Client 调用不能退回 SRC。

不同 preset 的实例独立，同一个 preset 的会话共享 standing 实例，遵循原版
所有权。卸载一个 preset fiber 同时影响它的共享成员，不影响另一个 preset。
已进入调用的 handler 捕获实例与激活代次，沿用上一批次的失效检查。

构建检查生成的 Session row 保留 handler 服务的 isolate 声明，拒绝将 bridge
配置放入该 row。Host patch、preset fragment、Python entry、Remote 和 Client
产物均纳入同一源码与 SHA-256 receipt；验证失败不改已有构建。可编辑的用户
preset 仍受正常 preset 装配与泄漏检查约束，receipt 不能替代运行时所有权。

## 原版 Client 的选择生命周期

SDK 使用原版 `sessions.list` 和 `sessions.scope`，在选中会话的真实 Agent Context
中挂载 guarded Client，并捕获该 Agent identity 供 `host.call` 使用。无选中会话、
addressed subagent 或 Host 回答 unavailable 时不挂载。每次离开选择释放旧 fiber
和 styles，新选择重新评估其 Client 源码；Host standing 实例保留。

可用性查询可以并发。旧请求迟到不会阻塞新会话加载，也不能挂回旧会话。退出
选择即令旧 activation 失效，旧 closure 的未来调用或迟到结果不能返回成功。
已在运行的可信 Python/JS 代码不由此成为可抢占的安全沙箱。

Client 与 Host 仍使用共享 Remote artifact、原版 Connection/Typert、原版
evaluator、Context facade、React/slots 和 HMR。未修改原版浏览器输入、引入
另一条业务 HTTP 桥、Node Host、QuickJS 或新生产依赖。

## 已观察旅程

私有 `DSH_HOME` 下经真实创造模式 Tools 导出、原生 CLI 构建/ZIP 安装，配置两个
用户 preset 和四个 Session。测试准备合法的零 step transcript，通过正式 Session
列表与标题投影进入原版侧栏；这不是 AgentLoop/真实模型验收。原版有意保留空白
Session 的过滤规则，测试通过真实鼠标展开 Ungrouped 与切换侧栏，不改变该规则。

真实原版浏览器 23 步通过，记录 15 个实际 `call` request/response：13 个成功、
1 个 preset 卸载后拒绝、1 个 bridge 卸载后拒绝。调用 payload 明确包含捕获的
`agentId`，两个 preset 计数独立，同 preset 的 shared Session 计数连续，普通
Session 无 Client/style。故意挂起 a 的真实 availability RPC 后，b 可以先加载；
放行 a 不使旧 Client 复活，也不改变 a 的 Host 计数。

还验证源码重建/还原的真正 HMR、Host 计数与页面 timeOrigin 保留、styles/fiber
释放、页面 reload 恢复选择、profile 重启、2.0.0 升级、1.0.0 回退和移除。随机
端口重启产生新浏览器 origin，因此通过侧栏重新选择，不将跨 origin localStorage
视为已恢复。包移除后用户 preset 文件保留；仍引用已移除包的 row 需要作者编辑，
此次未实现用户 preset 引用的事务性清理。

## 回归观察的计时修正

全套回归曾得到 `1 failed, 4630 passed, 2 skipped, 1 warning`（662.28 秒）：
唯一失败为既有 Cordis C42。适配器固定等待 50 毫秒后就释放 gated refresh，
当 disposal 尚未结算时会改变 `pending` 和最终 trace 的顺序。通过仅延迟测试中
的清理结算 80 毫秒，可稳定复现相同失败；不是本次 Session Remote 的失败。

两侧观察适配器现在等待 C42 的实际 disposal 完成，设置 5 秒超时，再采样与
释放 refresh。C41 仍保留初始 apply 必须 pending 的观察窗口。没有修改 Cordis
产品运行时、固定原版源码或冻结 expected。生命周期 13 项通过；重新运行原版
与 Python C40–C51，12 个观察全部匹配原先冻结结果，输入哈希无漂移。
这是测试观察器修正，不登记为原版运行时 bug。

原始失败日志、XML 和当时输入保存在 `.goose/out/python-session-client-reviewed-failed.*`
及 `python-session-client-reviewed-failed-inputs.json`；双侧结果在
`.goose/out/python-session-client-lifecycle.json`。这些本机辅助文件不构成迁移
registry acceptance，也不能替代发行环境的独立验收。

## 最终验证

原生 `.venv\Scripts\python.exe -m pytest tests`，启用 `DSH_TEST_CHROMIUM`：
**4632 passed、2 skipped、1 warning，645.39 秒，退出码 0**。JUnit 共 4634 项，
failure/error 均为 0；五个真实浏览器用例均执行通过，包含既有 lifecycle、Inspect、
预构建包、Host 源码联合包和本次 Session 源码联合包。

最终日志、JUnit 与 12 个变更输入快照分别为
`.goose/out/python-session-client-final.log`、`python-session-client-final.xml` 和
`python-session-client-final-inputs.json`，结束后核对 0 漂移。全套产生的 Session
与 Host 浏览器报告复制为 `python-session-browser-final.json` 和
`python-session-host-regression-final.json`；各自核验 119 个固定前端输入，21 个
实现/示例输入哈希均无漂移。两个报告的 Runtime/console/network 错误记录为空，
Host stderr 为空，退出码 0。

两项 skip 为 Windows 不适用的 POSIX 路径/权限检查；保留 Windows Proactor
transport 析构 warning、pytest-asyncio fixture loop scope 提示和测试 HTTP 连接
中止诊断，不宣称零警告。Python 3.8 compileall、Node syntax、diff whitespace、
migration check/ready 均通过；固定 reference 的 tracked 文件没有修改。

## 剩余迁移与发行

安装后的 SDK 不加入原始动态 runner 的 AgentRun/card、跨插件 priority 和组件
归属治理；这些限制不能由 Session placement 的成功代替。复杂 Remote 类型、
Python 依赖闭包/冲突诊断、用户 preset 引用清理、多来源获取和最新 Portable
解压验证继续实施。通用 JS Workflow、JS Host、Inspector/CDP 等原版表面仍未
由本次完成；Win7 真机与目标浏览器认证保留用户暂缓决定。

发行方向仍是固定 Python 3.8.10 Portable、本地目录/ZIP、可选预构建 Client，
所有来源归一到 profile/Loader。没有发布、推送或重建 Portable。本次修复测试
fixture 与迁移版 SDK，不将原版空白过滤、分组折叠或 origin 存储规则登记为 bug。
