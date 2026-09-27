# 持续对齐记录

本目录以 `tasks/*.json` 为状态权威，`status.md` 由工具生成。当前交付是单一协调者、契约依赖和只读门禁；分布式调度器、原子租约、自动上游巡检不属于本批次实现。

## 操作

```powershell
.venv\Scripts\python.exe scripts/migration.py check
.venv\Scripts\python.exe scripts/migration.py ready
.venv\Scripts\python.exe scripts/migration.py status --write
.venv\Scripts\python.exe scripts/migration_inventory.py
```

`check` 校验记录、依赖环、契约 revision、证据哈希、固定上游 checkout 和 manifest 漂移；它不是 parity 测试。`ready` 只列出无阻塞任务，不领取任务、不提供租约。完整 inventory 重建要求固定上游 SHA 与 manifest 集合/内容未漂移。

## Current shared live-write closure

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
