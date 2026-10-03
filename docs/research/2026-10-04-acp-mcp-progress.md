# ACP 会话 MCP 挂载第四部分

固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；HTTP 有界验收已提交 `52b14fba`，本部分从隔离工作树移入主树，`MIG-ACP-MCP-009` 保持 running。完整开发预览已通过，产品提交后的干净候选验收尚待执行，没有提前认证完整 ACP 或整体迁移。

## 产品变化

原先 new/resume 的工作区检查直接拒绝非空 mcpServers，现改为真实 factory setup 中先安装模型控制、验证全部声明，再依次等待 MCP provider 激活，完成后才发布 Agent/Session。通过安装所有的插件注册表解析 MCP provider，没有新增跨插件的硬编码类导入。子插件与工具属于尚未发布的 Agent scope，后续配置错误、启动错误、请求取消及 bridge 关闭由 factory 作用域回收。

声明映射保留原版 stdio/HTTP 字段、默认值与 failOnStartupError=true；NFKD/原始名称 SHA256 命名、UTF-16 孤立代理替换、环境与大小写不敏感 header 去重、非法名称/路径/header/URL/transport、完整列表预验证及 __proto__ 数据保留经真实未改动源码观察。初始化按原版补充 mcpCapabilities.http=true，并更新实际 stdio 进程旧断言。

## 当前证明

58 组原版声明配置/错误原始字段与 Native 完全匹配。真实原版 ACP handler、SDK/MCP 子进程和 ToolsService 的双会话消费、关闭后同 session 重挂载、空声明 resume、全局工具不可见以及最终无 Agent 的完整输出匹配。Native canonical profile 同时验证 JSONL/SQLite、真实 HTTP header/执行、第二个声明失败回滚第一个子进程、完整声明非法时一个子进程也不启动，以及阻塞握手在取消后迟到完成也不能发布。

相关 93 项及后来 305 项 ACP/factory 回归通过；正式双侧 driver、59 项提供端/观察器和 175 项门禁/观察器回归通过。移入主树后 ACP/factory/发布门禁共 432 项通过，最终严格类型观察器 49 项及变更后的 abort/source/发布门禁 127 项通过。真实 canonical ACP stdio 进程旅程实际本地模型完成八次请求，消费三个 stdio 子进程的三个工具调用和一个 HTTP 调用。三个 stdio 进程独立、完成关闭，并以 Windows 7 可用 process synchronization handle 实测退出，HTTP peer 和 ACP EOF 正常关闭，没有外部 API。实际解压 Portable 消费者和新 driver 已接入门禁，必需 lane 共 62、选择配对共 31；主树完整门禁及实际解压运行结果待验证，不能仅靠 closed 文件标记认证退出。

## 保留的失败与边界

`.goose/out/acp-a4-work/acp-mcp-source-v1.log` 记录首轮 schema 错误 JSON 属性顺序不符；配置构造顺序修正后 58 组匹配。`acp-mcp-runtime-source-v1.log` 记录 source observer 用新的同值 ScopeKey 导致看不到作用域工具，改用真实 Agent 的 scopeOf 后匹配；没有删掉工具可见性字段。

`acp-mcp-runtime-v1.log` 记录无响应初始化 peer 的取消测试在十秒后 shutdown 超时。这不是已证明的立即关闭契约：原版 Cordis 在插件 apply 惯性完成后才运行 effect disposer。随后真实原版 AcpSession.create 与 Native factory 各驱动实际受控初始化子进程，显式取消后、握手释放前 pending 尚未完成且 Agent 未发布，释放后均拒绝并回收子进程；完整字段匹配，独立进程退出证明通过。该证据采用声明的握手释放屏障，没有证明无限无响应 peer 十秒以内结束，不能把修改测试叫作产品修复。SDK 默认初始化超时的无限无响应边缘仍未实测，不扩展原版 bug 例外索引。

主树冻结开发门禁 `.goose/out/acp-mcp-owned-preview` 已通过：5508 passed、6 skipped、1 warning、0 failed，耗时 1179.80 秒；62 必需 lane、七组 722 项原版断言、31 双侧 driver 和真实解压 Portable 全部通过。实际解压包 ACP/MCP 旅程完成三个 stdio 子进程、三个 stdio 调用、一个 HTTP 调用、八个本地模型请求及真实进程退出。ZIP SHA256 为 `3aa924c146510b733dd2eb40974d8bc5c4eb3a13d3cf85742126a1a076667b35`；冻结输入 SHA256 为 `34cd509262fbe3687e4ede864878c7367f50504fd362b2e414883e9ac8ebb6cf`。这是未提交开发预览，publishable=false；随后提交本部分，再运行干净候选门禁。

尚无 clean acceptance 或 integrated 记录。WHATWG URL/Unicode 版本等未覆盖边缘、subprocess subagent-acp、其他 HTTP SDK 范围和 B/C/D 仍继续推进。浏览器启动取消、既存 Proactor warning/HTTP 10054 和延期的 Win7 认证保持开放。隔离树已开始真实 subprocess ACP 后端，并发现实际模型消费者收到 Event 而非 AbortSignal 的迁移缺陷；该修复属于后续部分，不混入本次冻结验收。
