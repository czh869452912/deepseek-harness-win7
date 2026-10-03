# ACP stdio 与 canonical 启动推进

固定目标 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；A1/A2 有界接受候选仍为 `97f7b287`。本部分 `MIG-ACP-STDIO-005` / `CON-ACP-STDIO@1` 尚为 running/specified，没有整包或完整 ACP 验收。

## 产品与必要消费者

`AcpRpc` 使用 Python 3.8 标准库实现 SDK 1.4.0 NDJSON、split UTF-8、精确 ECMAScript 空白、未终止尾行、batch、typed id、当前取消注册、协议错误、串行 stdout 和 outgoing correlation。参数解释器只涵盖已挂载的九个方法；生成数据绑定实际固定 SDK 的 Zod/deserialize SHA，开发时重新导出并逐字段比对，运行时不依赖 Node/Zod。

canonical acp-app 接受参数后才提供 readiness 和 detachable stdin，help/错误不占 transport；ACP 撤销自己的事件、请求和 stdout，不关闭调用者的进程句柄。`session/update` 来自已提交事件并在 prompt result 前排空，仍不把未提交 provider delta 当作 committed output。

真实 EOF probe 发现 `session_projcache` 在 Agent 取消后继续写入已关闭存储的警告。修复在 canonical shutdown 的既有五秒边界内先 serial `app/stopping`，ACP 关闭请求与 Agent，再等待 projection-cache 待写任务，随后全树 fiber teardown。注册可撤销，无错误过滤/重试/新 skip；这是一项显式 Python 调度适配，未登记为原版 bug。

## 已执行与保留失败

- 最初产品旧 ACP/app 专项：152 passed；随后新 stdio/app/process 专项 18 passed。
- 独立原样 SDK 与实际生产实现：906 原始观察匹配，包括 10 framing、9 outgoing、9 byte vectors、78 参数向量和固定种子的 800 变异输入。报告/两侧输出/输入/hash 为 `.goose/out/acp-stdio-work/combined-matched.*`；没有对错误、数字或输出字段归一化。
- 新 observer 的十类破坏反例拒绝缺失、重复、顺序丢失、空 batch、typed cancel 丢失、尾行丢失及 outgoing/schema 状态缺失。
- 原样 `acp-app` 两文件 3 assertions passed，开发观察器补固定 `commander@15.0.0`，没有改 reference。
- 最新 process/wire/startup/observer/release 专项：72 passed（`targeted-final.log/xml`）。实际子进程启动原入口、受控 localhost HTTP，覆盖两个 Session 并发、session/protocol cancel、活动 EOF、新进程恢复、拒绝非法参数及 committed updates 顺序；不继承真实凭据。
- 首次完整 Python 3.8.10 回归：4966 passed、5 failed、6 skipped、1 warning（1157.49 秒），保留 `full-regression.log/xml`。五处失败全部是 installation registry 仍断言 acp-app 缺失；提供端落地后收缩 frozen shipped gap 为零，并以独立未实现安装 fixture 保留 fail-loud 反例，不改上游。最终 registry/gate/SDK observer 组合 105 passed（`consumer-final.log/xml`）；仍须冻结候选重跑全量，不能把组合回归记录改成全量成功。
- 独立实际解压 Portable 预览通过：13 runtime steps、两个 ACP 子进程九步 journey、119 frontend 输入校验；ZIP SHA `7134d6333a221ab58c999a6d6f04370e1fbebb5f8007deead9d8c3bbd8504315`，provenance dirty=true，browser 未在这份专项预览运行，不能发行或接受。`portable-preview-receipt.json` 及 stdio/runtime 原始日志保留。用开发 venv 的 `-I` 运行同一 probe 因开发路径隔离找不到 apps 而失败，未冒充产品故障；实际包 `_pth` 隔离运行已通过。
- 早期 `journeys.log/xml`、`journeys-owned.log/xml`、`targeted.log/xml` 保留。首次 fixture 误读最后一条 system reminder；后续 fixture 错把未提交 delta 当作 ACP update，因此超时。改为等真实 HTTP admission，再观察取消结果。EOF 缓存关闭故障单独修复，不用 fixture 修正掩盖产品警告。
- 合并 observer 的 built-in `bytes` 名称遮蔽、batch anchor 少计一个 invalid response、报告孤立 surrogate UTF-8 写入失败均已修复；原始 `combined*` 失败仍保留。最终报告用 JSON escaped Unicode 无损记录孤立 surrogate。

## 验收仍待执行

统一 gate 现要求 27 paired drivers、六组原样源测试（前五组 616 + app 3），十四条不可缺失/跳过的 browser/Portable/ACP 进程 lane；解压 Portable 增加两个真实 stdio 进程、九步初始化/参数拒绝/new/close/list/EOF/resume 验证。没有重新发行或声称当前旧 ZIP 含这些未提交变更。

已执行完整 `.venv\Scripts\python.exe -m pytest tests` 并修复五处受影响消费者断言；提交的是待验收产品候选。冻结干净候选跑完整 gate，必须全量零失败和所有 required lane/SDK/source/实际解压通过，再绑定 ZIP/receipt 签发限定验收。A4 MCP/一次性权限/subagent、B/C/D、无缓存安装、真实远程服务和暂缓的 Win7 真机不随 A3 自动闭合。原有八类精确原版 bug 谓词和 C58 边界未扩大。

A4 首个实际否定探针：原样 MCP SDK 在不存在 executable 上 connect 和后续 tools 调用均失败；当前 Python MCP transport 返回 proc=None、空 tools 和虚构调用成功文本。原始观察保留 `.goose/out/acp-a4-work/mcp-provider-{source,python}.json`，这是未完成提供端的失败证据；不得只接 ACP 参数 mapping 或 advertise http=true 就宣称 MCP 完成。
