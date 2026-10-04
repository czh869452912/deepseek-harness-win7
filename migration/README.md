# 持续对齐记录

本目录以 `tasks/*.json` 为状态权威，`status.md` 由工具生成。当前交付是单一协调者、契约依赖和只读门禁；分布式调度器、原子租约、自动上游巡检不属于本批次实现。

## 当前补齐：2026-10-02

2026-10-04 Session filters：干净候选 `1d9940aa` 完整冻结门禁 **6134 passed、6 skipped、1 warning、0 failed**，119 必需 lane、十一组 910 原版断言、43 双侧驱动及真实解压观察通过。`CON-SESSION-FILTERS@1` 有界 integrated，三十一份任务证据归档 `evidence/artifacts/SESSION-FILTERS-20261004-1d9940aa.zip`，包括实际候选 Portable ZIP；见 `reviews/SESSION-FILTERS-CLOSURE-20261004.md`。搜索请求正在单独推进；完整 Unicode/FTS/代际、B/C/D、历史诊断与延期 Win7 仍未完成。

2026-10-04 Session tracing：干净候选 `5c0b3c5e` 完整冻结门禁 **6082 passed、6 skipped、1 warning、0 failed**，114 必需 lane、十一组 910 原版断言、42 双侧驱动及真实解压 Python 3.8.10/原版浏览器通过。三十个有界任务重签，包含此前未签收的 ACP subprocess/teardown、MCP disposal、进程树、cache/point/corpus/title、ZIP 暂存和谱系/事件窗口；证据见 `reviews/SESSION-TRACING-CLOSURE-20261004.md`。此前失败和源缓存 40ms 时序诊断均保留，没有新绕过或重试；过滤/完整 FTS、B/C/D、整体 accepted_upstream 与延期 Win7 仍开放。

2026-10-04 ACP/MCP：干净候选 `e24fe1db` 完整冻结门禁 **5508 passed、6 skipped、1 warning、0 failed**，62 必需 lane、七组 722 项原版断言、31 双侧驱动及真实解压会话 MCP 消费者通过。`CON-ACP-MCP@1` 有界 integrated，十九份证据归档 `evidence/artifacts/ACP-MCP-20261004-e24fe1db.zip`，见 `reviews/ACP-MCP-CLOSURE-20261004.md`。无限阻塞初始化、完整 URL/SDK、subprocess subagent、B/C/D、整体 accepted_upstream 与延期 Win7 仍开放；第五部分继续单独实施和验收。

2026-10-04 MCP：干净产品候选 `8a17485d` 完整冻结门禁 **5408 passed、6 skipped、1 warning、0 failed**，51 必需 lane、七组 722 项原版断言、30 双侧驱动及真实解压 stdio/HTTP 工具消费者通过。`CON-MCP-STDIO@1` 和 `CON-MCP-HTTP@1` 只按有界提供端范围 integrated，18 份合同证据归档 `evidence/artifacts/MCP-20261004-8a17485d.zip`；见 `reviews/MCP-CLOSURE-20261004.md`。此前 browser startup 取消及既有 Proactor/HTTP 10054 保留未归因，完整 SDK/ACP mounting/subagent/B/C/D、整体 accepted_upstream 与延期 Win7 未闭环。

2026-10-04 A4 权限：干净产品候选 `e887550a` 完整冻结门禁通过，**5020 passed、6 skipped、1 warning、0 failed**；20 条必需 lane、619 项原版断言、28 个双侧驱动及实际解压六条权限进程旅程通过。`CON-ACP-PERMISSIONS@1` 有界 integrated，10 组原始匹配及两组单独审阅的原版畸形 outcome 授权缺陷，证据包 `evidence/artifacts/ACP-PERMISSIONS-20261004-e887550a.zip`。见 `reviews/ACP-PERMISSIONS-CLOSURE-20261004.md`；既有 Proactor/HTTP 10054 诊断仍保留。MCP/subagent、B/C/D 和整体 accepted_upstream 未完成。

2026-10-03 A3：干净产品候选 `5edf7e22` 完整门禁通过：**4971 passed、6 skipped、1 warning、0 failed**；十四条必需 lane、六组 619 项未改动原版断言、27 个双侧驱动及实际解压 Portable 通过。`CON-ACP-STDIO@1` 已有界 integrated，涵盖 canonical acp-app、SDK wire/参数、真实进程 EOF 与关闭所有权；906 项 SDK/生产原始观察匹配。十五份证据及历史失败归档于 `evidence/artifacts/ACP-STDIO-20261003-5edf7e22.zip`，见 `reviews/ACP-STDIO-CLOSURE-20261003.md`。完整 ACP 的 MCP/权限/subagent 和 B/C/D 仍未完成；全项目 `accepted_upstream` 仍为空。

2026-10-03 后续：干净产品候选 `97f7b287` 已通过完整门禁，**4933 passed、6 skipped、1 warning、0 failed**，十条必需 browser/Portable lane、五组 616 项原样源码断言、26 个双侧驱动及实际解压 Portable 均通过。`CON-ACP-SESSION-CONTROLS@1` 和 `CON-ACP-CONFIG-OUTPUT@1` 的有界任务已 integrated；14 份当前证据及所有先前失败归档于 `evidence/artifacts/ACP-CONFIG-20261003-97f7b287.zip`。完整 ACP 仍待 canonical stdio 与 MCP/权限/subagent；没有认证全项目、fresh uncached bootstrap 或 Win7。详见 `reviews/ACP-CONTROLS-CONFIG-CLOSURE-20261003.md`。

本轮 `MIG-CURRENT-RELEASE-GATE-003` / `CON-CURRENT-RELEASE-GATE@1` 补齐当前原版浏览器、最新已选双侧契约及实际解压 Portable 统一验收；不是重签历史 `MIG-REPRO-GATE-002`，也不代表整个迁移完成。用户授权提交后，产品候选 `623a615a` 已通过干净门禁；当前门禁和 ACP prompt 归属两个有界任务已 integrated，历史十个 Core/Agent/Session/Spine/Portable 范围重签本候选证据。未提交预览仍不得进入 verified/integrated。

正式门禁必须提供 Chromium：`scripts/verify_release.py --browser <absolute-path>`；缺少浏览器、必需测试跳过、回执或候选不一致均拒绝发行。`--allow-dirty` 仅用于本地开发预览，其 summary 始终 `publishable=false`。原版浏览器只用真实可见控件完成无凭据引导，不修改上游 TSX/CSS；后续导航先等待有限请求结束，再检查弹窗或交互状态。

范围、既存缺口和后续顺序见 `docs/research/2026-10-02-migration-status-audit.md`；本轮推进与验证见 `docs/research/2026-10-02-current-gate-progress.md`。Windows 7、JS/OAuth 和 ACP 等仍按独立契约推进，不能用当前 Windows 门禁代替。

2026-10-03：按用户授权提交 P0 初版后的首次 clean gate 失败已保留；新增文档代际等待和完整诊断，并用四个失败探针修复单请求 HTTP carrier 隐瞒 socket 关闭的问题。修复后的 preview 与干净产品候选均 **4800 passed、6 skipped、1 warning**，十条必需 lane、四组原样源码测试、24 个双侧驱动和实际解压 runtime/browser 通过；只有后者为 passed / publishable=true。ACP 精确 Session/Agent/message/turn 归属通过 `MIG-ACP-PROMPT-OWNERSHIP-001` / `CON-ACP-PROMPT-OWNERSHIP@1` 验收，不冒充完整 ACP 实现。收据、完整输入、原始观察及历史失败归档于 `evidence/artifacts/CURRENT-GATE-20261003-623a615a.zip`；范围与后续行动见 `docs/research/2026-10-03-current-candidate-closure.md`。

原版 bug 的统一发现索引为 `upstream-bug-exceptions.json`：此前八类判据不变，新增第九类 `UPSTREAM-ACP-PERMISSION-001` 仅接受原版对两组畸形 outcome 错误授予 allow-once 的精确签名。索引指向配对 predicate、场景和独立审阅，不是跳过列表。C58 独立归入语言适配，迁移产生的 ACP 归属错误和观察器缺陷不登记为原版 bug；各门禁仍是唯一允许差异的执行权威。

## 操作

```powershell
.venv\Scripts\python.exe scripts/migration.py check
.venv\Scripts\python.exe scripts/migration.py ready
.venv\Scripts\python.exe scripts/migration.py status --write
.venv\Scripts\python.exe scripts/migration_inventory.py
```

`check` 校验记录、依赖环、契约 revision、证据哈希、固定上游 checkout 和 manifest 漂移；它不是 parity 测试。`ready` 只列出无阻塞任务，不领取任务、不提供租约。完整 inventory 重建要求固定上游 SHA 与 manifest 集合/内容未漂移。

## Current Session projection registry closure

Candidate `7720cf03`: clean-checkout release gate passed; **3235 passed, 2 skipped, 2 warnings**. Nine real registry observations match; 100 unchanged upstream projection/core Session assertions establish the source baseline. `CON-SESSION-PROJECTION@1` covers exact weak Session cells, prefix catch-up and duplicate suppression, caller-owned shared registrations, host/selected/cached reads, detached checkpoints, anchored restore and hydrate.

See [registry closure](reviews/SESSION-PROJECTION-CLOSURE-20260928.md). Next: executable domain definitions, then storageDomain and durable projection-cache, then cold Web/listing carriers. Existing keyword domain registrations and Web bridge remain compatibility adapters, not certified domain parity. Win7 remains deferred. The rebuilt package is in the managed release-repro worktree.

## Previous configured Agent closure

Candidate `5131a712`: clean-checkout release gate passed; **3219 passed, 2 skipped, 2 warnings**. Seven real configured Agent observations match alongside all prior paired gates. `CON-AGENT-CONFIG@1` covers configured identity validation/overrides, delayed resume, exact history reload, draining replacement/cancellation and contained startup failures. The Cordis child-disposer ownership fix is included and revalidated.

See [configured Agent closure](reviews/AGENT-CONFIG-CLOSURE-20260927.md). Next: full Session projection and replay contracts before Web consumers, then complete profile journeys after Wire/Tools/Web contracts. Full AgentLoop settings/tool policy and launcher integration are not certified by this bounded closure. Win7 remains deferred. The latest package is in the managed release-repro worktree.

## Previous public storage closure

Candidate `8201d7dc`: clean-checkout release gate passed; **3200 passed, 2 skipped, 2 warnings**. Eight real uncompressed JSONL storage observations match alongside prior Agent/cold/live/preparation gates. `CON-SESSION-STORAGE@1` covers shared lazy creation, batch cursor/adoption, read validation, empty live materialization and tested first-write atomic publication/rollback in both local backends.

See [public storage closure](reviews/SESSION-STORAGE-CLOSURE-20260927.md). Next: configured Agent startup/reload, then full Session projection and Web consumers. Native upstream SQLite, compressed JSONL and arbitrary cross-process/power-loss behavior are not certified. Win7 remains deferred. The latest package is in the managed release-repro worktree.

## Previous shared preparation closure

Candidate `78f35dc2`: clean-checkout release gate passed; **3175 passed, 2 skipped, 2 warnings**. Five real JSONL preparation observations match, alongside the prior Agent/cold/live gates. 197 upstream Session assertions establish a source baseline. `CON-SESSION-PREPARATIONS@1` covers the shared pool, exact reservations, cancellation, revision refresh, public write guards and teardown integration in JSONL/SQLite.

See [preparation closure](reviews/SESSION-PREPARED-CLOSURE-20260927.md). Next: public storage lazy creation, full append/read schema and cursor/adoption rules, then configured Agent startup/reload and full projection. Win7 remains deferred. The latest package is in the managed release-repro worktree.

## Previous shared live-write closure

Candidate `3de19a21`: clean-checkout release gate passed; **3142 passed, 2 skipped, 2 warnings**. Four real JSONL live lifecycle observations and seven cold-recovery observations match. The 174 upstream Session assertions establish a source baseline, not 174 Python parity cases. `CON-SESSION-LIVE-WRITES@1` covers bounded writes, failure retention/rollback, drain and tested HMR/retirement ownership in JSONL/SQLite. Shared preparation/public persistence coordination and configured Agent startup/reload remain pending.

See [live-write closure](reviews/SESSION-LIVE-CLOSURE-20260927.md). Core, Agent, Spine, Portable and cold recovery are revalidated at this candidate. Win7 remains deferred. The package is in the managed release-repro worktree, not the main checkout dist.

## Previous Session cold-recovery closure

候选 `0ab68981` 在干净检出完成发行门禁：3111 passed、2 skipped、2 warnings；七组真实 JSONL 双侧观察全部匹配，Session 原样测试 164 项通过。已验收范围为 `CON-SESSION-COLD-RECOVERY@1`，不是整个 Session 或配置重载完成。Core/Agent/Spine/Portable 在此候选重新验收；其他任务如显示 historical integration，表示本次没有重新签发其专项证据，不代表删除历史成果。

待完成实测问题与后续顺序见 [本次审阅](reviews/SESSION-COLD-CLOSURE-20260927.md) 及 `MIG-SESSION-REPLAY-002`。共享 preparation、写队列、卸载/HMR adoption 先稳定，再迁移配置恢复和 Web replay 消费者。

## 历史 Cordis 基础闭包

- 272 个 manifest 已全部分类：201 runtime、48 frontend、9 tooling、7 fixture、6 platform、1 example。分类是职责，不是模块完成计数。
- `upstream-test-inventory.json` 登记 1,227 个官方测试源文件、14,659 个字面声明，并保留参数化工厂位置；不把字面声明当成实际执行数。
- `dynamic-contract-inventory.json` 记录 1,346 个源码位置和最近 package 归属。动态表达式明确保留为待运行时解析的发现数据，不伪造完整服务图。
- `cordis-consumer-audit.json` 的 69 个必要消费者实例已有断言映射；加上生命周期 11 项，原样执行五个官方测试文件为 80 项。此前缺失的 39 项及部分断言已经补齐。
- `CON-CORDIS-CORE@10` 覆盖枚举的基础层场景和关键消费者；`CON-BOOT-SESSION-SPINE@1` 定义真实 profile → 工具 → JSONL → 关闭 → 新 Context 恢复。后者依赖前者的有效验收。
- C1–C67 是源码推导的本地场景 ID。C58 保留 Python 已完成 Future 的原生调度差异；C59 和框架侧适配场景必须匹配。原始 runner 保留失败退出码，独立 `cordis_acceptance.py` 只允许已审核的精确 C58 签名。
- Win7 真机及其浏览器验证由用户暂缓。当前 Windows / Python 3.8 验证不能替代 Win7 认证；mock LLM 不能替代真实远程模型认证。

当时产品提交 `25f59152`：全量 **3064 passed、2 skipped、2 warnings，0 failed**；关键上游原样测试 **80 passed**；双侧观察 **66 matched + C58 原生语言差异**，精确适配门禁通过。六个活动任务均已 integrated，Win7 真机验证暂缓。

最终回归、便携包和精确候选验收见 `evidence/*FINISH*`；完整审阅说明见 [本批次闭包](reviews/CORDIS-FINAL-CLOSURE-20260927.md)。历史失败日志保留用于追溯，不代表当前仍失败。旧失效发行物和启动器已退役；新便携包使用自己的 Python 3.8 运行时。

## 任务和接口规则

任务使用 `draft → ready → running → review → verified → queued → integrated`。当前工具验证记录快照，不执行自动状态机。进入 running 后必须有 owner；协调者负责处理冲突和提交集成。

`expected_paths` 是预期影响范围，**不是文件写权限白名单**。接口变更应在一个契约事务中同时修复提供端和必要消费端，增加 revision、刷新依赖和验收证据。不要在未稳定的接口上先移植下游模块；不要用互相依赖制造任务环。

`requires` 绑定提供任务、契约和 revision；提供端 integrated、契约 specified、精确提交与 revision 的有效 passing acceptance 必须同时满足，消费者才可解除阻塞。`conflicts_with` 双向生效。其他活跃作者拥有的修改应先协调，共同交付闭包不等于随意覆盖他人代码。

`contracts` 必须写清身份、所有权、顺序、错误、取消和平台适配。`mappings` 只索引测试，永远不直接认证 parity。验收记录绑定任务 acceptance 摘要、候选 commit、输入与产物哈希；陈旧输入不会满足当前门禁。

## 后续上游版本

固定观察到的上游 SHA，计算 manifest、源码、测试及动态契约变化；先审基础契约，再按提供端 → 必要消费者 → 集成 spine 排依赖。将独立模块拆成任务，接口变更合并为共享闭包。每个候选运行双侧观察、官方源断言和 Python 回归，平台适配必须有具体复现与理由。

只有已验证的明确范围可以集成。全项目 `accepted_upstream` 仍为空；本批次 Cordis/Spine 完成不等于所有业务模块或未来上游版本自动对齐。更早的阶段记录、失败复现和设计讨论保存在 reviews/evidence 与 research 文档中。
