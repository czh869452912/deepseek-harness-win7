# 全部迁移遗留项的闭环计划

目标继续固定为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，起点产品为 `5a3347d1ee98e828de0bbcce90c7b63880fe7532`。用户要求持续推进、每完成一部分提交；这不授权推送、发布、付费模型调用、擅自更新原版或恢复此前暂缓的 Win7 实机验证。

## 完成判据

“全部闭环”不能由 pytest 数、manifest 数、任务 integrated 数或一个发行 ZIP 推定。必须同时满足：

1. 每个产品运行时职责都有源合同、提供端和必要消费者映射；未知、占位、兼容适配和明确差异逐项记录。没有证据的部分仍未完成，非 MVP 不等于可删除范围。
2. 身份、所有权、顺序、错误、取消、持久恢复及卸载具有同场景双侧观察或可追溯原版断言；参数化用例不能只数文件名。
3. 真实 canonical profile / 实际工具 / 原版 UI / 新进程恢复 / 解压 Portable 组合旅程通过；原版前端不改 API 适配，退休 harness/ApiProxy 不回归。
4. 每个实现部分先跑针对性反例，再跑 Python 3.8.10 全量，提交后冻结干净候选验收；证据绑定实际 commit、输入、原版和产物哈希。
5. 原版此前八类 bug 和 C58 判据保持不变；新增 ACP 畸形 outcome 授权缺陷经独立审阅只允许两组精确签名。新失败先调查，不加入宽泛忽略、重试或跳过。
6. 整体源对齐与平台/外部服务认证分开。Win7/目标浏览器、真实凭据/模型和公开发布没有实际证据就保持未验收，不以用户暂缓为已完成。

`migration/tasks/*.json` 仍为任务状态权威；本计划是拆分和退出条件，不签发验收，也不自动设置 accepted_upstream。

## 依赖顺序与每次提交边界

| 阶段 | 提交单元 | 前置与退出条件 |
| --- | --- | --- |
| A1 | ACP 持久 Session 管理 | 已验收 Prompt ownership / Agent factory / Session cold + storage；实现 new 激活事务、list keyset、resume 精确归属/工作区、close 取消/排空/flush/dispose；不能 Agent=None 假成功 |
| A2 | ACP 配置与语义输出 | 对照 model-control/updates，模型目录/选择/turn pin、ordered committed updates、输出失败与恢复不重播；提供端和 Agent request 消费者一起验证 |
| A3 | ACP stdio 与启动 | canonical acp-app startup、整数版本/真实能力、标准 NDJSON JSON-RPC、请求 signal、EOF/卸载、stdout 专属协议；help/错误不占 transport，真实父子进程验证 |
| A4 | ACP MCP / 权限 / subagent | mount-before-publish、stdio/HTTP/SSE、工具 schema/结果、一次性权限、session/Agent 归属、断开/后代 drain；ACP 与 subagent-acp 消费端共同闭包 |
| B1 | Session 业务状态与长期历史 | registry 范围不冒充 domain；instructions、projection/cache、FTS、增量索引、损坏尾部、取消重放、跨进程恢复与规模测试分别认证 |
| B2 | Tools / Wire 正式合同回填 | 对照当前 24 paired drivers 和官方声明；并行工具、approval、用户补充、中断、maintenance/compaction 与关闭的组合顺序；DeepSeek/Pi 局部 wire 不认证 OAuth/云协议 |
| B3 | 完整 profile 用户主链 | standard/creative/minimal/headless/Web 与 PTC 的模型→工具→下一请求、question/approval UI、取消、关闭、新进程恢复；源码和解压包执行同旅程 |
| C1 | Provider / OAuth / 云协议 | 对原版服务能力逐个定义 route/auth/refresh/cancel 合同；先可控本地协议服务，再独立授权的真实 smoke；不继承宿主密钥 |
| C2 | JS / SDK / 插件交付 | 通用 JS 非小型表达式模拟；明确可随 Portable 交付且支持 Win7/Py3.8 的运行时方案；SDK AgentRun/card、Remote、升级卸载、preset 引用、priority/组件归属和来源信任 |
| C3 | 扩展打包与失败回退 | wheel/native ABI/版本范围、namespace/公共获取、授权清单、升级资产保留/数据回退，失败注入和离线启动；公开发布需单独授权 |
| D1 | 全职责覆盖收尾 | 逐行审 runtime/exports/动态提供端→消费者及上游参数实例；为剩余外围/experimental 功能补合同与反例；未认证职责不能据分类标完成 |
| D2 | 干净安装与最终发行验证 | --prepare 的无缓存开发依赖复现、完整统一 gate、精确 ZIP/receipt 上传消费；远程 Actions 执行与本地静态验证分列 |
| D3 | 目标平台与外部验收 | Win7 SP1/目标浏览器、PowerShell fallback、DLL/TLS/ACL/WinPTY；用户恢复验证并提供目标环境后实测，不能在当前 Windows 上签发 |

阶段 A 的共享提供端优先稳定，再推进 B 的主链组合。C/D 未获外部环境或授权时仍记录为未验收，继续推进其他可执行工作，不将局部阻塞伪装为全项目完工。

## 当前执行项

`6b82aebb` 的54双侧预检通过，但完整冻结候选被6890通过/1失败拒绝：原版安装包旅程十二步/六RPC通过，外部 Zotero 扩展脚本错误违反零错误要求，后续阶段未执行。确切 ZIP/输入/XML/浏览器资料保留。实际 Edge 受控扩展/页面异常实验证明进程级扩展隔离保持应用错误可见；统一测试浏览器启动并新增真实 lane，下一门禁为444必需 lane、十八组1237原样断言、54配对。旧取消/1175仍未归因，完整B/C/D继续开放；详见 `2026-10-05-browser-extension-isolation-progress.md`。

2026-10-05：最新完整有界签收产品为 `0edcc616`，6718 passed、6 既有平台 skips、1 既有 warning、0 failed；337 必需 lane、十五组 1124 原版断言、51 双侧驱动及实际解压/原版浏览器通过，见 `migration/reviews/SQLITE-FORMAT-CLOSURE-20261005.md`。可选五个 Session 工具、完整 FTS/schema-8/Unicode/text、schema-19 物理 codec 已有界签收；完整 B1/B2/B3、C/D 和全项目 accepted_upstream 仍未完成。

此后规范 SQLite 提供端 031 和默认压缩 JSONL 提供端 032 已实现。d5cc、865fea84、a6cf 的确切失败 ZIP、输入、XML、日志与浏览器诊断均保留：部分字节流超时的受控根修复、八项启动隔离/审计观察器错误已分别修复；a6cf 的 6808 passed / 1 failed 仍由原版浏览器升级启动请求取消拒绝，根因继续开放，不重跑未改候选。工具调度三处失败边界已提交 `03652743`；存储 null presence、路径/typed error/cold validation 与 public loadStored 已提交 `566eb5d0`，实际 JSONL 驱动扩大到 1030 项并匹配，570 项门禁单元验证通过。

只读上游差分 observer 已完成二十项含实际 pinned Source 的回归，任务 `MIG-UPSTREAM-DELTA-002` 按明确有界合同 running，不改变 pin 或自动推进任务。当前工具并发/settings 增量把下一完整门禁提升至 443 必需 lane、十八组 1237 原样断言、54 双侧驱动以及实际解压/原版浏览器。候选通过才签收 031/032/只读差分/033 的有界证据；浏览器未归因 finding、Session 任意 ABI/事件/竞争/长历史、Tools/Wire/全部 profile/UI 和 C/D 继续按退出条件实施，Win7 与真实认证仍按既有约束另列。

新干净候选 `5f2a76db` 的完整 pytest 为 6858 passed / 1 failed / 6 既有 skips / 1 既有 warning：普通文件原子替换返回 WinError 1175，原版双浏览器升级/回滚均通过，但后续 Source/配对/解压未执行。确切产物和输入已保留；受控 delete-sharing 双侧只复现 code32，不归因旧 1175。下一实施为原版默认10/可配置并发上限、组间动态 settings 与调度顺序合同，见独立文件发布记录；031/032/只读差分仍未签收。

工具并发增量已修复 Native 默认8与配置未传递的问题。实际 Source/native 二十项观察包含默认10、合法/拒绝数值、settings 挂卸、十二工具模型池，以及七工具跨独占屏障的动态组快照；33 项当前定向回归通过，27 项原样 Source 断言通过。完整 Tools/Wire 的同步 dispatch 前缀和组合仍开放。回执单测遇到磁盘写满，日志保留；用户授权只清理已标识的合成 JSON，真实失败产物不删除。新干净冻结验收待执行，见 `2026-10-05-tool-parallelism-progress.md`。

`18d60566` 完整门禁记录6889通过、2旧配置错误断言失败、6既有跳过和1既有warning；新 Config 的原版 ValidationError 与旧 ValueError 断言冲突。实际 Source/native 两条拒绝观察证明类型/消息及零 agent 发布一致，配对现为22项，严格修正断言后49定向通过。确切ZIP/输入/XML/浏览器均已保留，独立 Source/配对/解压仍待新候选完整验证；无原版判据放宽或未改候选重跑。

`2f3b8aa7` 全量6891通过、6既有跳过/1warning、十八组1237原版断言通过；第二配对因旧 Native configured-agent observer 只捕获ValueError而逃出ValidationError被拒绝，剩余配对/解压未执行。严格修正各案例异常与消息后七项Source/native匹配，全部配对预检与新候选验收继续，拒绝ZIP/输入/HTTP10054日志保持独立。

严格 observer 修正后全部54个实际双侧驱动顺序预检通过，包括规范SQLite323/JSONL1030与并发22观察；预检明确非发布，用户授权清理两次运行的460个合成回执后空间恢复。提交该 observer 修正后，冻结新的干净完整候选做全部解压/浏览器验收；031/032/差分/033仍须完整成功才签收。

## 历史执行项（2026-10-04）

2026-10-04：最近完整有界验收已推进到 `1d9940aa`，6134 passed、6 skipped、1 warning、0 failed；119 必需 lane、十一组 910 原版断言、43 双侧驱动与真实解压 Python 3.8.10/原版浏览器通过。三十一个有界子任务按精确产品、输入和产物重签；见 `migration/reviews/SESSION-FILTERS-CLOSURE-20261004.md`。这不是完整 ACP、Session 或全项目验收。

此后已逐项提交 subprocess ACP、teardown、MCP disposal、进程所有权/实际树、缓存与 point/corpus 读取、ZIP 暂存和标题批量。未签收的共同候选经历真实浏览器取消、ACP 中文 wire 观察编码、wrapped ZIP 暂存失败，以及用户中断；原始证据均保留。`d81dee16` 本次全量 5970 passed、6 skipped、1 warning，但随后原版 storage/cache 的固定 40ms 创建行检查失败（45 passed、1 failed），门禁拒绝且没有重签。受控 100ms fsync 延迟可复现相同断言，实际失败的具体延迟仍未测得；这不是新增 bug 绕过或已修复根因。

B1 的业务过滤与完整 surface 文档已连同此前 tracing 在上述候选有界签收。下一提交为搜索请求归属、错误优先级、参数化 SQL 预算与 Unicode 截断：50 原始观察匹配，隔离 534 扩展回归、最终 38 项和推广后主树 655 项通过；仍需新的干净全量/125 必需 lane/十二组 920 原版断言/44 配对/解压验收。这不是完整 FTS；后续还须补来源限定的持久化 revision、完整排名/游标/稳定重观察/增量索引代际，再 Tools/Wire、Web/profile 和 C/D。原版阶段停止并行开发 I/O，保留全部断言和失败退出码。旧 Proactor/HTTP 10054、浏览器启动取消、源测试时序和完整 SDK/树边缘仍具名开放；accepted_upstream 不自动完成。

A1 的 `MIG-ACP-SESSION-CONTROLS-003` / `CON-ACP-SESSION-CONTROLS@1` 已有界验收。父范围 `MIG-ACP-TRANSPORT-002` 仍是完整 ACP 的未完成任务，不因子合同集成而自动完成。

针对 A1 必须覆盖：空 Session materialization、关闭后 list/resume、稳定 newest-first + UTF-8 id 排序与严格 cursor、活动/正在激活/子 Session 排除、工作区物理/词法身份、未知/重复 resume、pre-abort、迟到激活、flush/dispose 失败、并发 close 共享、close 期间拒绝新 prompt、多个 Session 全部取消后汇总清理错误、真实 JSONL/SQLite 和新 Context 恢复。

后续每单元更新实际证据和下一项，不用“计划已写”冒充“实现已完成”。无法认证的范围保留具名 finding 与所需环境/决策，最终整体 accepted_upstream 仅在全范围证据齐全时考虑设置。
