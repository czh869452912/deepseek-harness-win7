# Cordis 核心迁移：运行取证与角色工作流调整建议

日期：2026-09-19。性质：评估与提案；未修改角色、运行配置、控制器、候选代码或任务状态。

## 1. 判断与前提

保留 `vendor/cordis` 的阻断地位。核心契约错误时放行下游，会让消费者围绕错误语义实现，制造后续返工。必要消费者适配属于同一个核心契约变更的验收闭包；不得因为改动跨目录或涉及大量测试而拆到被核心阻塞的后续任务。

本轮发生在此前编排修复落地之后。实际运行已经使用重验、增量评审、问题账本和仲裁，不能再把“尚未实现这些机制”作为当前主因。应调整的是：语义修复单位、角色交付物、失败分流、证据复用方式和高风险阶段配置。

核心问题：当前角色能严谨验证一个局部现象，却没有强制先建立完整的运行时行为模型。局部修复与局部回归一起通过后，下一角色才发现同一契约的另一个维度。协议错误、环境失败和清理问题又被卷入同一个昂贵修复循环。

## 2. 本次直接核对的原始证据

以下路径相对仓库根目录：

- A：`.goose/runs/project/candidates/ddde47ac-1789733001207066400/.goose/runs/20260918-200327-827f19b8/`
- B：`.goose/runs/project/candidates/ddde47ac-1789782769511967800/.goose/runs/20260919-095255-77288343/`
- A 的 01-review、02～06-integrate、02～06-integration_review、05-judge 结构化结果。
- B 的 01～03-integrate、01～03-integration_review、03-judge 结果，以及 04-integrate 的未完成工具轨迹。
- B 的 progress.jsonl：核对阶段开始、实际工具命令、工具输出、验证拒绝、结果和同一 HEAD。
- B 的各阶段 context.json：核对实际注入指令、full_review_required、历史反馈大小及验证错误内容。
- 当前 `.agents/agents/parity-*.md`、`.goose/agent-config.json`、parity_runner.py、project_runner.py、review_evidence.py、cordis-lifecycle-contract.md。
- state.sqlite3 使用 SQLite mode=ro 读取；没有恢复调度器或写数据库。

暂停快照仍为 READY 237、NEEDS_REVALIDATION 47、INTEGRATED 5；Cordis 为 READY round 4。记录含 revalidation_review、15 条 issue_ledger 和一次 decisions 记录。任务图存在 249 个直接依赖 Cordis 的任务；该阻断是预期的核心优先策略。

## 3. 真实反复点

### 3.1 EventBus：把“协程必须执行”误当成完整契约

A/01-review 找到无事件循环时 Timer 丢弃返回的 coroutine。A/02-integrate 用私有循环执行并补四种 Timer API 回归，随后评审通过。

A/03-integrate 把同类修复扩展到 EventBus.emit，采用 asyncio.run 等待异步监听器完成；03-integration_review 以可运行探针指出 emit 被约 80ms 的监听器阻塞，新测试也编码了这个错误顺序。

A/04-integrate 改为后台循环，等待单个监听器进入后返回；04-integration_review 又发现前一个监听器的 await 后续可以抢在第二个监听器调用之前执行，探针 20/20 复现。单监听器测试覆盖不了整个 dispatch 的顺序。

A/05-judge 对照 JS 和 Python 探针，明确要求 dispatch-wide barrier；随后实现和评审收敛。

归因：JS async 调用的同步前缀、Promise 延续、整次同步分发、非阻塞返回、后台任务归属是五个同时成立的约束。当前实现角色逐轮满足其中一个；测试随补丁设计，未先从上游导出完整事件偏序。不能简单把 `asyncio.run` 或后台线程认作统一的“合法 Python 适配”。

### 3.2 HMR：识别到注册身份，却只修共享状态的一张表

B/03-integrate 已明确复现原始失败：80 次负载尝试的第 44 次命中 `_refreshes` 残留，并明确判断为产品缺陷。报告引用上游按注册对象管理状态，却选择只拆 `_mtimes` / `_module_mtimes`，明确保留共享 `_refreshes`。

B/03-integration_review 与 03-judge 用确定性探针发现：module dispose 删除同路径活 config 的刷新状态；旧回调仍被阻塞时发生真实变更，会创建第二份状态、启动第二个回调，`calls_before_release=2, peak=2`。

新增测试先释放旧回调，再等待轮询，只覆盖“无真实变更时不应重新触发”，未覆盖“真实变更发生在 pending 期间必须串行”。B/04-integrate 已转向注册身份键控，但该阶段中断，尚无完成评审，不能宣称修复已验收。

归因：实现角色把“最小改动”理解成最少行数和保留现有机制；真正需要最小化的是无关语义变更。恢复一个完整不变式可能必须同时调整多张状态表和所有权关系。

### 3.3 同一 HEAD 被重跑：这一轮是结果协议错误

B/progress.jsonl 第 503 行：`Rejected test path tests: not an existing tests/ pytest path`。

B/01-integrate.result.json 的 test_paths 同时包含 `tests` 和若干合法子路径。控制器要求 `name.startswith('tests/')`，遇到 `tests` 立即返回 False；随后 01-integration_review 已经 PASS，仍因 verification=False 进入下一轮。

B/02-integrate 和 02-integration_review 都仍在 HEAD `9c249d36`；迁移者报告无代码改动，再做完整的证据核对。第二轮实际上下文中的错误仅为 `No valid targeted test selection`，没有携带被拒路径和具体原因，还保留旧的 IPv6 full_suite_failure。

归因：格式纠正被分流成产品修复；模糊的新错误与详细的旧错误并存，诱导重复诊断旧问题。对应代码：parity_runner.py 的 verify_chunk，以及 project_runner.py 的 execute_integration。

### 3.4 正确语义仍因临时文件进入一整轮修复

A/05-integration_review 已认可 EventBus 语义，但 checkpoint 包含四个临时探针/重建文件以及 EOF 空白问题。A/06-integrate 删除探针和修正空白后重新评审通过。

这应属于确定性的工作区清理与验收证据复核，不应再次承担语义迁移成本。探针本身有价值，执行位置和归档规则需要规范。

### 3.5 增量机制存在，但历史证据包过大且缺少“本轮唯一工作指令”

B 的集成评审上下文 01/02/03 均为 full_review_required=false，确认不是逐轮强制全量盲审。

但集成者 context.json 分别约 155/165/181/174KB，03-judge 约 336KB（文件字节数，不是 token 数）。其中完整 contracts 映射约 32.5K 字符、旧 migration 约 20K 字符、旧失败日志约 24～27K 字符，并存在多份历史 review/repair。B 第 596 行的可见进度说明需要先结构化解析大上下文。

这能证明输入臃肿和重复读取，不能仅凭大小证明模型性能下降；应测量解析/重读耗时。但 B/02 的协议错误被旧代理失败信息包围，是具体可修的任务定位问题。

## 4. 对原评估报告需修正的内容

1. B 阶段 start 实录中的 integration_review 是 `custom_openai_sol / gpt-5.6-sol`；当前配置为 medium。不能继续把今日评审归因于 Luna。
2. “今日第一轮到第二轮”有明确的 test_paths 协议拒绝证据，不应归为又一轮 flaky 门禁失败。
3. B 的 09:54:49/50 工具调用是在分段读取 context.json；输出包含历史测试结果。10:04:17 是读取既有 full_rs.log。它们不能计作新启动的全量 pytest。
4. 可直接确认 round 1 在 09:57:02、10:00:55 发起了两次完整 pytest。原报告“连续五次全量通过”的计数不能直接用于概率或效率推断；其他命令应按执行 ID、cwd、HEAD、退出码去重后统计。
5. HMR 第 3 轮明确确认产品竞态。不得将其归类为可通过三取二放行的纯测试 flake。原样复跑只用于诊断，不抵消既有失败证据。
6. 旧审计中的 round=0 数量不能证明修复后的任务仍从 migrate 开始；本轮 revalidation_review 已实际运行并查出真实 Timer 缺陷。

## 5. 建议的标准工作流：核心与必要消费者共同验收

### 阶段一：建立或更新契约包，再开始高风险实现

仅在新增运行时适配、共享状态所有权、调度/取消语义或核心接口变化时触发，不给每个普通补丁增加架构轮。

契约包必须包含：

- pinned source SHA、上游函数/测试证据、稳定 invariant_id。
- 对象身份、状态存储键、创建者、执行者、清理者、等待者。
- 状态转换、事件偏序、错误传播、取消与重复调用规则。
- JS→Python 的差异及采用该适配的边界；不得从已有 Python 写法反推合法性。
- 接口/行为变化→消费者接入点→必要改动→回归测试的影响表。
- 未决语义和反例；对疑难适配用 JS/Python 最小对照探针确定预期。

核心及必要消费者适配由一个候选统一承担并通过门禁；独立功能完整性缺口仍保留原 owner。区别依据是“不修改是否会违反本次核心契约”，而不是目录范围或改动文件数量。

### 阶段二：按不变式完整实现

迁移者先提交可检查的简短设计：失败现象→被破坏的不变式→共同根因→所有受影响状态/消费者→验证矩阵，再动代码。

补丁不得仅声明“保留其他状态不动”：必须说明为什么保留后仍满足全部关联不变式。不能因核心变更要求大量消费者适配而自行缩小验收。

每个真实修复至少有一个旧实现失败、新实现通过的确定性用例。采用事件/屏障控制交错，超时用于防挂起，不用短 sleep 作为正确性证明。对于不能在旧实现原样运行的新内部 API 测试，提供外部行为探针；变异测试是补充，不能冒充原始 pre-fix 复现。

### 阶段三：评审同时验证实现和测试的区分能力

独立核对上游不变式与消费者闭包；为新增时序/所有权机制设计反例，而非只重跑实现者测试。

最低检查项：单实例/多实例；同路径不同身份；单监听器/多监听器；首次触发/pending 中再次触发；正常/抛错/取消；局部 dispose/根 teardown；有/无 ambient loop（仅对契约支持场景）。每项填写覆盖用例或不适用的源码理由。

首审建立完整证据，修复审复用未受影响条款；不得每轮重建所有已确认事实，也不得因为旧 PASS 就跳过新增机制的反例。

### 阶段四：控制器按失败类型分流

| 类型 | 下一步 | 保留什么 |
|---|---|---|
| RESULT_PROTOCOL：路径/字段格式 | 纠正结果字段并验证；不改代码、不重跑语义评审 | 同 HEAD 的实现和评审证据 |
| HYGIENE：临时文件/空白 | 定向清理，再检查 diff 和适用证据 | 已确认语义结论 |
| ENVIRONMENT：代理/端口/工具错误 | 同候选诊断执行环境，控制器验证纠正后的条件 | 失败命令、环境差异、原始输出 |
| PRODUCT_SEMANTICS：真实断言/探针失败 | 按不变式修复完整因果范围 | 已完成的无关条款 |
| CONTRACT_AMBIGUITY：适配/顺序/所有权不清 | 实现前裁决契约或修改方案 | 双方证据与反例 |

产品竞态必须修复。不得仅凭某次复跑通过变成 PASS。最终仍对统一候选运行完整门禁。

路径验证应返回准确的 invalid_path/reason/accepted_examples；schema 与验证器须一致。是否允许根目录 tests 是策略问题，关键是禁止将合法性纠正升级为产品修复循环。字段纠正后仍需执行正确选择的测试。

### 阶段五：让证据可复用且可定位

每轮输入开头固定提供：本轮模式、触发原因、当前唯一阻塞项、候选/基线 SHA、已完成条款、需重验条款、明确禁止重新设计的已关闭范围。

当前失败与历史失败分开标注。默认携带精简条款及证据路径，完整原始报告按需读取；只传相关契约的版本，不把所有任务契约与多层旧反馈反复内嵌。

测试记录绑定 command/cwd/interpreter/head/environment fingerprint/exit/log/attempt。读取旧日志不算新运行。同一 HEAD 的协议纠正不得使完整语义评审失效；影响代码或契约的变化则必须重新判断证据适用性。

## 6. 各角色的具体要求与配置建议

以下是待验证提案，不是本次已应用的配置，也不是模型优劣实验结论。

| 角色/阶段 | 建议要求 | 配置建议 |
|---|---|---|
| architect / 契约设计 | 除任务图外输出上述契约包、消费者影响表；保留核心原子验收 | 使用现有 Sol；高风险设计可显式 high，避免依赖未声明的默认 effort |
| migrator / 普通实现 | 按已经明确的契约和覆盖矩阵实现，禁止用本地测试证明自己定义的语义 | 普通任务保留 Flash，作为流程试点基线 |
| integrator / 核心语义修复 | “失败日志是入口，完整不变式及消费者是修复范围”；输出根因与关联状态清单 | 对 Cordis 的运行时/所有权修复试点 Sol high，或先由 Sol high 审查契约方案再交 Flash 实现；一次只比较一种策略 |
| reviewer / integration_review | 必须提供测试区分能力和交错反例证据；列出复用/新增覆盖 | 当前已是 Sol medium；先规范产出，必要时对高风险阶段试点 high，不承诺升 effort 必然减少轮数 |
| judge | 增加实现前的疑难契约/修复方案裁决；输出行为规则、反例与回归义务 | 保持现有 Sol high；无需对每个普通修复都调用 |
| controller | 失败类型分流、精确反馈、精简证据包、测试结果去重、同 HEAD 复用 | 用确定性逻辑实现，不能只追加提示词 |

当前控制器将 integrate 映射到 migrator、integration_review 映射到 reviewer；配置只有四个 role。要单独配置核心 integrator，需新增有边界的 task/phase 覆盖能力，不能假装现有 JSON 已支持，也不建议为此全局切换所有普通任务模型。

提示词应保留一份有效要求：移除被控制器覆盖的旧 COMPLETE 状态、旧文本结果块和角色侧全量步骤；统一由控制器跑最终全量门禁。judge 的“只在事后分歧时调用”需与实际轮数升级及拟新增前置裁决一致。迁移者的“不能隔离就升级”需澄清：已授权核心契约所必需的跨模块适配可直接完成，真正未决的语义才需裁决。

推荐直接加入 integrator 的规范文本：

> Treat the failure signature as an entry point, not the complete repair scope. Before editing, identify the source-backed invariant, state identities and owners, all related state stores, and required consumer adaptations. Repair the smallest complete semantic cause. Preserve unrelated verified behavior, but do not preserve a mechanism that violates the same invariant merely to minimize changed lines. Distinguish protocol, environment, hygiene, and product failures before choosing implementation work.

推荐加入 reviewer 的规范文本：

> For each new concurrency or ownership mechanism, verify a counterexample independently of the implementer's regression. Report the source-defined ordering and ownership rules, covered interleavings, and why the tests distinguish the incorrect implementation. Reuse unaffected evidence; do not accept passing counts as proof of complete affected-contract coverage.

## 7. 落地顺序和验证标准

1. 先补纯协议纠正路径与精确错误反馈：用本次 test_paths=tests、同 HEAD、已有 PASS 的真实样本重放；预期不再启动新一轮产品实现。
2. 用已有 EventBus 与 HMR 失败前候选离线检验新契约包和评审清单。已知案例只能证明流程能覆盖已知遗漏，不能当作独立模型能力评测。
3. 恢复当前 Cordis 候选前先核对 round 4 中断时的修改、探针还原状态及现有裁决；不能因本评估忽略已有工作重新实现。完成注册身份/串行刷新契约后统一验收必要消费者。
4. 流程验证与模型替换分别做，避免同时改提示词、模型和门禁后无法归因。新任务记录新缺陷/复发/协议纠正/环境处理/语义修复各自耗时、同 HEAD 重复评审数、旧实现失败证明覆盖率、消费者覆盖率。
5. 保持核心阻断和最终全量零未解释失败。成功标准是完整契约一次覆盖更多维度、无意义修复轮下降，而非降低门禁或保证固定两轮完成。

验证边界：本会话前一轮已经按 AGENTS.md 在主工作区执行完整 pytest：1844 passed、1 failed、1 warning，失败为 tests/test_portable_smoke.py::test_smoke_dist_portable_directory。本次仅新增评估文档，未发生需重复该检查的代码变化。这个结果不是候选的 2008 项套件结果，更不是 round 4 的验收。


## 8. 用户认可后的落实与验证

本节更新于同日后续实施；前文“未修改”的说明描述评估时点。

已落实：六个角色工作流；核心 contract_checks 结构化交付与验证；核心集成
ESCALATE 前置裁决；精确任务/阶段模型配置及缓存身份检查；测试根路径规范化和
无工具的结果字段纠正；当前工作指令与历史证据归档；测试命令/cwd/head/解释器
记录；看板覆盖配置显示与操作文档。当前只有 vendor/cordis 的 integrate 试点
Sol high，普通迁移和评审配置保持原值。核心阻断、必要消费者适配及最终门禁保留。

离线重放真实 B/01-integrate 结果：test_paths 中的 tests 被规范化为 tests/，
去重后仅产生一次完整覆盖的控制器检查，不再因字段格式进入代码修复。此处测试
执行器由记录命令的夹具替代，只验证分流；不代表候选产品测试通过。
B/02 的实际反馈可识别为 RESULT_PROTOCOL，当前工作排在第一项；交接 JSON 从
146257 字符减少到 67787 字符，省略内容保留在可按需读取的原始证据中。

按要求执行 `.venv\Scripts\python.exe -m pytest tests`：1853 passed、1 failed、
1 warning，耗时 133.51 秒。唯一失败仍为既有的 portable 目录 smoke test，
调整前亦失败；未删除、跳过或放宽该测试。日志：.goose/workflow-adjustment-tests.log。
最后的原子任务组分号解析修正另做两项专项验证，2 passed。Python 3.8 编译检查和
差异空白检查通过。未执行真实模型恢复试跑，未宣称模型效率收益已获验证。

调度器保持暂停，候选代码与任务库未修改。恢复将使用新的核心阶段配置和指令，
重新核对并保留已有未完成工作；不自动重置迁移成果。本轮没有重建旧 portable 包。
