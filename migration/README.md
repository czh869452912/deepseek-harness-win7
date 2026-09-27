# 持续对齐记录

本目录是新迁移流程的持久记录入口，设计依据为[持续对齐工作流评估](../docs/research/2026-09-27-continuous-parity-workflow.md)。当前为第一阶段：清单发现、任务记录和只读门禁已落地，尚未启用自动领取、状态推进、多 worker 调度、上游定时观察或完整差分 runner。

## 使用

在仓库根目录执行，使用 Python 3.8 标准库，不增加产品依赖：

```powershell
.venv\Scripts\python.exe scripts/migration.py check
.venv\Scripts\python.exe scripts/migration.py ready
.venv\Scripts\python.exe scripts/migration.py status --write
.venv\Scripts\python.exe scripts/migration.py inventory
```

- `check` 校验 JSON、ID/引用、依赖环、revision、来源路径、证据摘要、上游 checkout 及 manifest 漂移。通过只代表记录一致，不表示迁移完成。
- `ready` 列出 ready 且无显式阻塞、依赖或活跃冲突的任务。它不认领任务、不提供租约，也不能在多个进程中充当调度器。
- `status` 输出看板；加 `--write` 只写固定的 `migration/status.md`。不要手工维护看板。
- `inventory` 输出当前 reference 所有 Git 已跟踪 package manifest 的发现结果，不改 target 或覆盖已人工分类的清单。新输出需先分析和合并，不能用它直接覆盖既有信息。hash 为 UTF-8 文本、换行统一为 LF。

当前发现 272 个 manifest，包括 7 个 fixture；其余 265 项仍待分类，不能把它解释为 265 个待迁移产品模块。清单同时登记 scripts/snapshots/native/python 等非 package 表面；官方测试总数、完整动态契约图仍待盘点。

## 单一状态权威

`tasks/*.json` 是持久任务状态，单一协调者编辑。worker 可以提出结果和记录修改，但不能各自依据旧工作树快照决定已领取或已集成。当前人工协调，逐个选择任务；需要并发时先实现事务租约与 checkpoint 恢复，再扩大执行槽位。

任务遵循 `draft → ready → running → review → verified → queued → integrated`。本工具仅检查当前快照，不校验历史状态转换或自动推进状态。未实施的转移校验不能靠 JSON 编辑冒充调度器行为。ready 不要求 owner；进入 running 后必须明确 owner。

`expected_paths` 是预计影响范围，**不是写权限白名单**。必要提供端、消费端和测试可以一起调整。跨模块变更先记录不变式、必要消费者、冲突 owner 和验证闭包；有活跃 writer 时由协调者确定共同交付者，禁止直接编辑对方工作树。

`requires` 绑定任务、契约、revision。消费者可放行须同时满足：提供任务 integrated、契约 specified、有效 passing acceptance 证据与集成提交及 revision 匹配。`conflicts_with` 任一方登记即可阻止与活跃任务同时执行。共同变更先收缩为同一任务，不用互相依赖制造环。

首批四个可选任务为 inventory、Cordis 验证、跨盘搜索分析、portable 输入分析；建议先执行 Cordis 证据复核。`MIG-SPINE-001` 仍为 draft：它的 Boot/Session 依赖尚未完整定义，不能看到 Cordis 完成就直接领取。

## 契约与证据

`contracts` 中 draft 表示还没有完备语义规格；specified 必须补齐身份、所有权、偏序、错误、取消及适配字段。所有语义修订必须增加 revision，同时更新受影响任务引用并安排重验。初始 C1–C21 是本地源码推导场景，不是官方用例 ID，也不是已确认的双侧 oracle 通过。

`mappings` 当前只支持 `indexed-unverified`，用于发现与保存测试入口；验收状态由证据而非映射标签承担。Cordis 官方直接消费者清单已建立于 cordis-inventory.json；仍不生成全项目完成率。

acceptance 证据必须包含：

- `task_id`、任务验收摘要 `acceptance_digest`、目标上游 SHA、产品提交、契约 revisions。
- `commands`、`exit_code`、Python/OS/cwd 环境、result 和 validity。
- `inputs`：产品代码、必要消费者、测试、fixture、runner 等实际输入的仓库相对路径及 SHA-256。
- `artifacts`：已保存日志/报告的仓库相对路径及 SHA-256。

摘要由 `scripts/migration.py` 的 `acceptance_digest(task)` 生成。任务目标、依赖、验收要求变化后旧摘要不再满足门禁。输入文件变化或消失会使证据在本次计算中失效；不会自动改写历史记录。artifact 内容不一致属于证据损坏，不能误报产品失败。

verified/queued 需要当前候选的有效证据；integrated 必须记录实际集成提交并具有该提交的通过证据，checkout 检查其为当前 HEAD 的祖先。已集成历史可以保留旧 target/revision 或 stale 证据，但不能再解锁消费者。语义规格变化应建立新 revision/重验任务，旧任务保持原始绑定，不重写为新 revision。

当前校验器只验证已声明输入，**不会自动推导所有消费者或检测未登记环境变化**；输入完整性、独立评审和真实执行仍由协调者负责。无关或伪造的 passing 文本不能成为合格证据。每次接受结果需核对命令输出、候选内容、测试区分能力和输入闭包。此阶段不能无人值守自动合并。

历史 baseline 失败摘要已入库；原始完整日志仍在本机 `.goose/research-workflow-20260927-tests.log`，不将历史摘要作为当前 acceptance。后续长期证据需保存可恢复日志或稳定 artifact，不能只留会过期的 CI 链接。

## 上游与平台边界

`baseline.json` 将 product、target、accepted 和 observed 分开。accepted 为空表示未建立全范围验收版本；observed 为空表示没有登记远端观察，不表示没有新版本。不要因 `reference` 固定了某个 SHA 就填充 accepted。

当前检测要求 reference HEAD 等于 target 且无已跟踪修改。新上游批次应先比较代码、manifest、锁文件、官方用例、快照及生成目录，完成影响分析后再一起更新目标及记录。未记录的新增/删除 manifest 或 hash 变化会让 check 失败。

旧 dist 与跨盘搜索的三个基线失败已通过实际修复和重建消除；MIG-PORTABLE-001、MIG-SEARCH-001 已有固定产品提交的通过证据。新 portable 包含自己的 Python 3.8 与固定 ripgrep，当前 Windows 隔离启动已验证。Win7/Win7 浏览器按用户指令暂缓；真实 provider 不由 mock 测试认证。

## 后续建设顺序

1. 复核 Cordis C1–C21 的原 oracle 证据或重建同场景双侧探针，补完整行为模型及必要消费者。
2. 核对上游官方案例清单，扩大 inventory；修复确认的基线缺口。
3. 加入带状态前置条件的记录更新、提交绑定及原子领取/租约恢复；补 PR 验证门禁。
4. 跑通真实纵向流程和一个上游更新批次后，再开放第二个实现 worker。

## 历史阶段验证记录（不代表当前失败）

工具门禁回归最终为 **27 passed**。全量回归为 **2924 passed、3 failed、2 skipped、2 warnings**；其后补充了两项历史集成保留测试并重新通过全部 27 项专项测试。三个全量失败与之前记录一致，没有隐藏或跳过。完整结果见 `evidence/RUN-WORKFLOW-20260927.json`。

`MIG-WORKFLOW-001` 的工具与初始记录已提交于 `a3c4462c`；任务仍停在 review，
其回归记录不是完整通过的固定候选 acceptance，提交不等于契约门禁集成。

Cordis 已建立直接运行固定上游源码的双侧 runner（见 `scripts/oracles/README.md`），
覆盖 C1–C45 本地场景，当前契约 revision 6 仍为 draft。其中 C42/C45 为未解决
差异，默认双侧 runner 返回 1；专项 pytest 通过不能抵消这两个差异。
前两轮观察与修复分别见 `reviews/CORDIS-C1-C21-20260927.md` 和
`reviews/CORDIS-WAVE2-20260927.md`。Loader/HMR 消费者观察见
`reviews/CORDIS-CONSUMERS-20260927.md`。模块热替换/回滚、官方用例清单和
固定候选验收尚未完成，不能据此解除 `MIG-SPINE-001` 的依赖。

前三轮 Cordis 修复、探针与证据已提交于 `24691c8d`。其后的 Include 初次加载
并发刷新修复见 `reviews/CORDIS-INCLUDE-20260927.md`；交付提交不等于完整
契约已集成，也不改变已有失败证据的历史性质。

最新生命周期验证见 `reviews/CORDIS-LIFECYCLE-20260927.md`。已修复公共重复
dispose 与结构所有者等待混用的问题；新发现的 registry 返回包装对象/原始 fiber
身份差异须优先处理，Loader/Include 与对应消费者应纳入同一修复闭包。


## 2026-09-27 最新收尾

产品提交 a7e65ba9：全量 **2989 passed、2 skipped、2 warnings，0 failed**。
旧的失败日志作为历史证据保留，不删除或改写；它们不表示当前回归仍失败。

- C1–C62 双侧源码探针：61 matched，C58 为已完成 Future / resolved Promise 的原生语言调度差异。C59 显式 checkpoint 适配匹配；默认 runner 仍返回 1，不隐藏差异。
- handle/raw restart、依赖恢复、真实模块 HMR、循环相对导入和同批失败回滚已完成。契约 revision 8 记录新的行为边界。
- 官方生命周期 11 + Boot HMR 6 项原测试通过；直接消费者 inventory 已入库，标题匹配不是语义验收。
- Preset invariant companion 与真实 profile → 工具 → JSONL → 全树重启恢复已实现。后者专项通过，但整体 SPINE 门禁仍等待 Boot/Session 完整契约与 Cordis 提供端验收。
- 跨盘搜索和新 portable 的有限范围验收已集成。发行物约 45 MiB，构建输入、ZIP 摘要和隔离 boot 证据已保存。Win7 暂缓不阻塞本批次，也不等于已认证。

完整 Cordis 验收尚有两个明确工作项：逐项审核官方必要消费者（包括动态参数展开），检查迁移回调对已完成 await 的可观察让出点。更广泛的模块分类、调度器原子领取/租约和上游更新演练也没有被本次测试计数替代。看板由任务记录生成，禁止把交付提交自动等同于全项目 parity。
