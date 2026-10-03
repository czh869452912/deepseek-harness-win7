# MCP HTTP 与生命周期第三部分

目标固定 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，产品起点 `93e06d8a`。`MIG-MCP-HTTP-008` 保持 running，`CON-MCP-HTTP@1` 保持 specified；未签发 clean acceptance 或整体 accepted_upstream。

## 实现与来源

HTTP 提供端替换虚构空工具和成功输出，使用 Python 3.8 标准库 asyncio 网络流执行真实 MCP 初始化、JSON/批 JSON 响应、POST SSE、GET 通知、协议/session/header 字段、错误、超时和取消。stdio 与 HTTP 共享抽取的 RPC 请求、schema、错误及取消所有权，stdio 保留独立子进程读写和关闭。图片与工具桥保持第二部分的真实消费者证明。

固定原版 transport factory 加真实 SDK 1.29.0，向相同受控 HTTP peer 执行十六组旅程；原始输出及请求字段与有界 literal specification 和 Native 精确匹配。观察器明确先等 optional GET admission 再 list，并在 cancel/timeout 等 cancellation admission 后 shutdown；不将无约束并发请求的偶然到达次序称为协议要求。整个原始字段保留，未通过删字段或重试掩盖差异。

九组未改动原版 supervisor 的 readiness、日志、fetch/register/unregister/close 顺序对照暴露并修正：成功 outcome 应为空对象、错误诊断需要原版名称前缀、注册冲突需要记录且回滚，以及数值计数的 JavaScript 文本表示。另用真实 SDK 而非 MockClient 验证非法 URL 工厂失败：五秒 close barrier 后停止，不创建虚假重试 generation。工厂失败期间的并发 dispose 仍待对照。

HTTP cancel 不能等待通知 POST 的服务端回执才结束请求；通知作为本客户端拥有的异步任务发出，close 回收。close 本身按原版行为不发送 DELETE；显式 terminate_session 才发送，并接受 405。网络 writer 关闭超过一秒会 abort，不让 TLS writer close 无限占有作用域；该关闭适配不等于 TLS parity。

SDK schema 对照另补三组 Unicode 数字样式对象键，修正 Python isdigit 对非 ASCII 数字的额外识别；当前共 962 组解析与错误观察，旧第二部分的 959 组证明仍按旧输入保留。

## 验证与失败

隔离工作树 228 项针对性回归通过；最终提供端/观察器的 163 项通过。十六组原始 HTTP、九组 supervisor 及一次真实 SDK factory barrier 对照通过；正式 HTTP driver 和含实际 ToolsService 消费者的 Native runtime report 均通过。108 个观察器用例拒绝缺失、重复、损坏、布尔/数值假退出、假工具结果和错误模块来源。

早期失败全部留在 `.goose/out/acp-a4-work/mcp-http-*.log`：observer 读取正在覆写的 JSON 改为 admission marker 与退出后读取；受控 TCP server 的 Windows Proactor accept/stop 竞态导致源码旅程 stderr，TCP-only fixture 改用 Selector policy，产品未换策略；DELETE 缺失默认 Accept、取消通知发送/回执归属、GET/list 并发顺序、UTF-8 BOM 分别经原始源码观察修正或明确输入屏障。它们不进入原版 bug 例外索引，没有忽略错误或添加重试。

主树 444 项针对性回归和正式 HTTP 双侧 driver 通过；必需 lane 扩至 51，新增 HTTP 双侧 driver 和真实解压 embedded Python HTTP 消费者。

完整冻结开发门禁 `.goose/out/mcp-http-owned-preview` 未通过：**5407 passed、1 failed、6 skipped、1 warning**，失败为 `test_original_browser_built_creative_source_restart_upgrade_rollback[host]`。在第三次打开新 host 后、文档 load 附近，settings/describe、inspect manifest、credentials、inventory、modelCatalog 与 HMR SSE 同批 ERR_ABORTED；下一次受控导航在约 1.4 秒以后，不能归因于下一次导航。此前启动取消诊断仍未解决，不忽略 consoleErrors、不增加重试，也不登记为原版 bug。失败日志和输入 manifest 保留；该 run 为 failed / publishable=false，未运行的后续原版/配对门禁不冒充通过。

同一冻结输入生成的真实 ZIP 另独立解压验证通过，结果 `.goose/out/mcp-http-owned-preview/portable-diagnostic.json`：embedded Python 3.8.10 的十六组 HTTP 原始观察和真实 ToolsService 消费者通过；注册、实际输出、撤销、关闭、peer 退出均为真，writer/task/pending 均为零。二十组 stdio、既有 runtime/ACP/权限与五步原版浏览器旅程也通过。ZIP SHA256 `f695168e311967f827c6ab911e21c0f961a4902f03be6a75a282280854c56b4b`。独立 Portable 成功不能覆盖完整门禁的浏览器失败。

隔离工作树新增浏览器 net-log 诊断，前两次十七步旅程通过，尚未捕获失败网络日志；这两次不构成失败修复证明。按用户授权提交第三部分实现与失败记录后，继续干净候选完整验收及浏览器根因调查，任务保持 running。

## 后续未完成

HTTP TLS、redirect、compression/URL 细节、resumable SSE/replay 与重试耗尽还未完整认证；当前可执行路径不代表完整 SDK。ACP mcpServers validate/mount-before-publication、subprocess subagent-acp、B/C/D、fresh uncached bootstrap、Win7 和外部服务验收继续保留独立退出条件。先前浏览器启动取消、Proactor warning 和 HTTP 10054 诊断保持未归因；本轮通过不等于这些问题修复。
