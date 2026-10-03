# ACP 一次性权限有界闭包

固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；干净产品候选 `e887550aa510e74bf3529a8a114ea39ef3402a13`，Python 3.8.10、当前 Windows。完整冻结门禁 passed / publishable=true，未推送或发布，整体 `accepted_upstream` 仍为空。

## 接受范围

`CON-ACP-PERMISSIONS@1` 接受真实 `session/request_permission` 的一次性允许/拒绝、精确 Session/Agent/callId 归属、已提交工具通知的先行排空、未知选项与畸形 outcome 拒绝、断连包含和取消后迟到授权失效。必要消费者同时修复：ApprovalService 能观察 canonical Agent 的 `asyncio.Event`，释放自有 watcher，并保持借用回答与既有 AbortSignal 的所有权；没有这个消费者，真实工具会在请求权限之前失败。

12 组固定输入保留两侧原始请求、更新、响应、决策、顺序和审计关联。10 组完全匹配；两组是原版错误接受缺失/未知 outcome 判别字段中的 allow-once，Python 返回 unavailable。两组只能通过独立审阅的完整字段精确谓词，不能标为 matched，不能放宽其他异常。见 `ACP-MALFORMED-PERMISSION-20261003.md` 和 `UPSTREAM-ACP-PERMISSION-001`；此前八类原版 bug 与 C58 判据均未改变。

实际 canonical CLI 子进程连接本地可控模型和可撤销工具，覆盖 allow、reject、malformed、cancel-late、close-late、EOF 六条旅程，验证执行次数、下一次模型请求、JSONL asked/decided 关联与关闭排空。使用受控 minimal 测试 profile；这不认证完整 standard/creative/Web 主链。

## 冻结门禁与产物

完整 `pytest tests`：**5020 passed、6 skipped、1 warning、0 failed**，1123.26 秒。**20** 条必需 browser/Portable/ACP/permission 进程 lane 全部通过；**28** 个选择配对驱动、六组 **619** 项原样源码断言通过。实际 ZIP 解压后 runtime 13 步、原版 browser 5 步、ACP 两进程九步、权限六进程及 119 项 frontend 输入验证通过。

发行 ZIP SHA256：`30d4bc310f79db2fa4a5d3f15bbb1c19df5062e39bae3bc7fab7c9b0ff2bd3e9`。冻结输入 SHA256：`e1f42792c0bdf23b861bb7bd5453f83dd6a1d0fc0e50c530a7670c46e3d7d17c`。证据包 `migration/evidence/artifacts/ACP-PERMISSIONS-20261004-e887550a.zip` SHA256：`214f99be4b32a1d978db0fff9fbe4a86aac4aebadbff56846444ab6a2fc1c775`，含完整门禁、原始 SDK/Python 输出、前期失败和未验收 MCP 原型探针。16 份证据只重签各自原有有界合同，不扩展历史任务的认证范围。

日志仍保留一个既有 Proactor `Event loop is closed` warning，以及全量后 HTTP/1.1 读取下一请求时的 WinError 10054。后者同样见于此前 controls/config/current-review 门禁；尚未归因到具体请求，不作为新的原版 bug 或通过谓词。旧 IPv6 测试未释放响应的 10053 已修正，45 项支持测试通过且本次未出现该诊断。所有日志未过滤；上述遗留诊断仍需独立清理，不能据本次结果宣称零告警或全部关闭路径已认证。

## 未闭环项

完整 ACP 父任务仍为 draft：真实 MCP stdio/HTTP/SSE、supervisor、mount-before-publish 和 subagent/后代关闭尚未验收。隔离 MCP 原型的正常 SDK 字段匹配与针对性测试不是 MCP acceptance。B/C/D 的 domains/history/cache/FTS、Tools/Wire、完整 profiles、OAuth/云、JS/SDK、扩展交付、全职责覆盖和无缓存安装继续保留。远程 Actions、付费模型与暂缓的 Win7 真机/目标浏览器没有本次证据。
