# ACP 权限迁移进展

权限产品候选 `e887550a` 已在干净冻结门禁完成 `CON-ACP-PERMISSIONS@1` 有界验收：5020 通过、6 平台跳过、1 既有 warning、零失败，20 条必需 lane、28 个配对驱动、619 项未改动原版断言及实际解压 Portable 通过。源码和包内均执行六个真实权限子进程；没有付费模型或公开发布。

修复同时覆盖 ACP 提供端、ApprovalService 的 canonical Event 消费者及 Tools→下一模型请求，避免只测一个处理函数。两组原版畸形权限响应错误授权已独立审阅，保留原始差异并严格限定为 `UPSTREAM-ACP-PERMISSION-001`；不修改既有八类 bug 或 C58 判据。审阅与产物哈希见 `migration/reviews/ACP-PERMISSIONS-CLOSURE-20261004.md`。

主候选冻结期间，真实 MCP stdio 在隔离工作树继续实现；实际 SDK 的正常初始化、八个并发调用、错误和工具列表通知字段匹配，52 项 provider/supervisor/consumer 针对性测试通过。重连、通知串行同步、关闭 barrier、卸载等待、作用域服务名与真实 ToolsService 消费者已有原型，尚缺完整双侧失败观察、schema、完整 Python 回归和干净 Portable 认证，不设置 integrated。HTTP/SSE 和 ACP MCP/subagent 仍待实现。

既有 Proactor warning 与 HTTP 10054 诊断保留为未闭环测试债务，不加入原版 bug 例外。全量后 HTTP 10054 在旧门禁亦出现，具体请求归因仍待完成；本次修复的 IPv6 响应释放不宣称消除了所有关闭诊断。整体 accepted_upstream 仍未建立，B/C/D、Win7 和外部认证范围不变。
