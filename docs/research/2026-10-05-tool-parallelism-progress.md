# 工具并发上限与可逆 settings 迁移进展

目标固定为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，原版前端、源码和既有 bug 判据不修改。此增量 `MIG-TOOL-PARALLELISM-033` 只覆盖并发上限、settings 归属和实际模型消费者；完整 Tools/Wire、全部 profile/UI 和整体迁移仍开放。

## 根因与修复

原版默认 `maxParallelToolCalls=10`，Native 调度器原先固定默认8，模型消费链没有读取部署配置，也未注册原版可编辑的 `agent-loop` settings。新的共享提供端校验有限正整数数值，允许原版 Number 语义的整值浮点，拒绝布尔、字符串、非整数、非有限及非正数；声明式 Config 保持原版 agents 字段。

Loop 组合拥有基础配置，规范可选 SettingsProvider 仅覆盖 `maxParallelToolCalls`，不开放 agents 编辑。非法更新保持旧值；提供端卸载回到组合值，重新挂载读取新存储值，Loop 卸载可逆释放 namespace。模型步骤传递实时配置读取器，调度器在每个组起点读取一次，不改变已经运行的组。

## 实际 Source 对照

27 项原样 `tool-calls.spec.ts` / `settings.spec.ts` 断言通过，日志 `tool-scheduler-original-27-v1.log`。实际原版 Context、Loop、Tools、Settings、MockAdapter 与 Native Python3.8.10 二十项观察匹配，没有以测试名、清单或静态 fixture 代替双侧执行。

十二工具模型消费者分别证明上限1、2、10，保留十二个结果的模型顺序并进行第二次模型请求。七工具受控模型消费者从上限2启动：保留工具1等待，只释放工具0并在其内部把 settings 改为1；工具2仍须开始，证明当前组快照仍为2。随后排空第一组，执行独占工具3，工具4–6逐个释放，后组峰值为1。两侧初始 `[0,1]`、继续 `[0,1,2]`、峰值 `[2,1]`、完整结果 ID 和第二次请求一致，未添加时序睡眠或放宽超时预算。

当前定向33项通过，先前54项实际消费者通过；磁盘清理后595项回执/便携启动/factory/原版模型消费者回归通过，日志 `tool-scheduler-gate-v3.log`。回执验证要求完整有序观察、正确选定根和 Python3.8.10、实际导入的全部候选 Python 模块字节；缺失/更改模块、外来根/运行时、删行/重排行或改值拒绝。实际解压运行使用包内 `python.exe -I` 再观测，对照新鲜 Source 摘要与当前宿主模块闭包，宿主回执同时重新核验当前磁盘模块字节；完整干净门禁成功前不签收。

## 拒绝样本与后续

候选 `18d605664588d984a2a008dcbd0ced49c5c9fd7d` 完整 pytest 为6889 passed、2 failed、6既有 skipped、1既有 Proactor warning，1724.43秒。新增完整 Config 在发布前以原版 `ValidationError` 拒绝空 sessionId 和布尔 maxTokens；两条旧用例却期待手工 `ValueError`，因此完整门禁拒绝。补上这两条实际原版/原生异常类型、对应消息语义及零 agent 发布观察后，配对扩大为二十二项且匹配；测试现在分别严格指定 `ValidationError` 和 `ValueError`，不是接受任意异常。49项定向回归通过。此次原版浏览器和普通文件替换均通过，但不归因历史启动取消/1175。后续独立 Source/配对/解压阶段未执行。

确切拒绝ZIP SHA256 `25979b01ee5e63d0fdedf5a3a103799ebf8f7e3c011dd4d40a077e498d17cd73`，输入SHA256 `f1b30ce43810b35b672120a1af46583b58b357d27a27cdbd4c7f6a1a37c2434b`，位于 `.goose/out/session-storage-clean-18d60566/`；XML、原始日志和浏览器观测独立保留。修改后的新候选须重新完整冻结验收，旧候选不重跑、不签收。

初始回执套件544项通过、41项因 `No space left on device` 失败，原始 `tool-scheduler-gate-v2.log` 保留。用户授权后，按 `unit-receipt-cleanup-687.json` 清单核验路径、字节数、非 reparse 和明确合成标记，清理1081个可重建 receipt/extracted JSON，释放11191684654字节；真实失败 ZIP、输入、XML、Source/浏览器观测不删除。新回执验证仍须通过，磁盘失败不计为绿色验收。

下一干净冻结门禁要求全量 pytest、443必需 lane、十八组1237原样断言、54配对驱动及实际解压/原版浏览器。031/032/只读差分/033在该新候选通过后才转入有界集成。保留 `5f2a76db` WinError1175、旧启动请求取消、未测量 partial-wire、Source 固定等待和 Proactor warning，受控 sharing code32不归因1175。同步 dispatch 前缀、完整取消/批准/followup/maintenance/compaction/disposal 组合、Session 任意 ABI、C/D 和延期 Win7继续具名开放，`accepted_upstream`为空。
