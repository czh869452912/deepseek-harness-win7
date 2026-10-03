# ACP 一次性权限通道推进

A3 已在干净候选 5edf7e22 完成限定验收，验收提交 693d86a0。下一有界单元 `MIG-ACP-PERMISSIONS-006` / `CON-ACP-PERMISSIONS@1` 当前 running/specified；MCP 与 subagent 完整提供端仍未完成。

生产 ACP handler 只接受 exact owned Agent/Session + callId，先 drain committed tool update，再经实际 AcpRpc 发出 session/request_permission 和两个一次性选项。回答经过 ApprovalService 审计；断连、远程失败、非法响应不授权，foreign Agent/无 callId 委托下游。原 AgentLoop 的 asyncio.Event 与原 ApprovalService 的 AbortSignal 接口不一致，真实工具首次请求直接失败；新增调用方 Event 的自有 watcher 适配，pre-abort/等待中取消/回答后取消均保留单条决定与释放 watcher，不取消借用的迟到回答。

固定原源码 + SDK 和实际 Python wire 观察十二种模式：十项原始匹配，未知/缺失 outcome 判别字段且携带 allow-once 的两项原版错误授权单列 reviewed-original-defect。专用 predicate 对完整固定身份/选项/update/顺序/响应/审计逐字段检查；20 项 observer 反例拒绝空输出、缺失、重复、乱序和无关差异。审阅见 migration/reviews/ACP-MALFORMED-PERMISSION-20261003.md。统一发现索引新增 UPSTREAM-ACP-PERMISSION-001；原有八类及 C58 未改变，不能把新增原始差异算成 matched。

六个真实 canonical CLI 子进程模式覆盖 allow/reject/malformed/cancel-late/close-late/EOF。实际安装可撤销本地 Python 工具 fixture，受控 localhost DeepSeek wire 发出工具请求；检查 permission 前工具未执行，allow 仅执行一次，拒绝/非法响应返回 tool-result 给下一模型请求，取消/关闭/EOF 不执行且无下一请求。JSONL 关闭后审计恰为 asked/decided 同一 id；迟到 allow 不产生第二决定。此处使用自有最小测试 profile，不能冒充 standard/creative 全链认证，或真实付费模型。

首次开发 -I 进程因开发 venv 路径隔离没有 apps 失败；仅实际 Portable 使用 -I/_pth。最小 profile 缺失 adapter、fixture effect 立即撤销工具、取消 fixture 错等 notification 的回复等初期失败均保存于 .goose/out/acp-a4-work，不改名成功。修正后六个进程通过；原生 Event/权限/observer 组合 59 passed，旧 approval 双侧九项与38个未改动源 assertions 重新通过。

统一发行 gate 增加第28个 permission 双侧驱动、六条必需权限 process lane（总20）；实际解压 ZIP 用自身 Python 执行同六模式并绑定 raw permission/audit/frames。完整 Python 3.8.10 为 5020 passed、6 skipped、1 既存 Proactor warning、0 failed（1111.52 秒）。实际解压专项预览通过 runtime 13、ACP 9 步/两个进程、permission 六进程/六种单条持久审计与119 frontend 输入；ZIP SHA256 747ebb5d044ac81eaf3dbf4e80ad4632b5b2251624f96ef7017163054ffff2ab，dirty=true、browser 未运行，不能发行或接受。

完整回归结束后的 IPv6 HTTP WinError10053 诊断在先前 A3 原始完整及 clean gate 日志中同样存在。归属测试支持的 mock LLM IPv6 listener 用例：仅读取 status，没有读取/关闭 response，之后 fixture 强制关闭 keep-alive socket。修正该观察器消费者，使其在 context manager 中验证并读完 DONE，再释放 response；不捕获/过滤服务器异常，不改产品或 reference。ACP/stdio/approval 关闭组合另行检查无 stderr。仍须冻结干净产品候选跑完整 gate，所有必需 lane/源码/双侧/真实解压包齐全才签发有界 integrated；公开发布、无缓存安装、Win7 实机及整体 accepted_upstream 保持原边界。
