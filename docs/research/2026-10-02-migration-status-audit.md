# Python 3.8.10 迁移现状、差异例外与后续行动审查

日期：2026-10-02（Asia/Shanghai）。性质：实现审查与开发机复验；只新增报告，不修改生产代码、测试断言、迁移任务状态或上游源码。

## 1. 基线与总判断

- 产品 HEAD：`1d5d965de1c7e08c00cbd1fd5227d2503d28444f`；开始时 tracked 工作树干净。
- 固定原版：`cd5ef8148158c3a752a658978873241fdf8e2bbc`；本地 reference HEAD 一致，无 tracked 修改。
- 本机：原生 Python **3.8.10**、当前 Windows；开发 oracle Node **22.20.0**。浏览器复验使用现有 Edge Chromium，未安装软件或修改系统配置。
- 对照的是固定原版，非未经确认的 GitHub 最新 HEAD；`accepted_upstream`、`observed_upstream` 仍为 null。本轮不推进 target。

**项目已从“核心单元迁移、正式入口存在缺口”推进到“原生正式主链、canonical Web 和 Python 插件交付可运行的开发预览”。但不是全原版 1:1 完成，不是当前候选完整发行认证，更不是 Win7 SP1 真机认证。**

三类问题必须分开：①实现进度领先于正式台账；②仍有通用 JS、ACP、OAuth/云协议、业务语义和平台认证等实质缺口；③端到端与发行门禁尚未整体闭合。不能用一个未经映射的完成百分比代替这些判断。

审查入口为 migration README/status/baseline、固定 reference 源码，以及 9 月 28 日 MVP audit 之后的逐批研究记录。

## 2. 本次实际复验

### 全量 Python 回归

```powershell
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/migration-audit-20261002.xml
```

**4725 passed、16 skipped、1 warning，731.97 秒，退出码 0**。JUnit 4741 项，failure/error 均为 0。测试期间未修改生产或测试输入。

| skip 原因 | 项数 | 意义 |
| --- | ---: | --- |
| 未设置 DSH_TEST_CHROMIUM | 5 | 浏览器没有运行，不算浏览器通过。 |
| 当前 checkout 未构建 dist/dsh-win7-portable | 5 | 五个 profile 的 Portable smoke 未运行，不算发行通过。 |
| Windows 符号链接权限不可用 | 4 | 文件身份、lstat、别名写入、搜索链接行为需要补验。 |
| Windows 不适用的 POSIX 语义 | 2 | 平台不适用，不机械照搬 POSIX 断言。 |

保留既有 Proactor transport 析构 Event loop is closed warning、pytest-asyncio fixture scope 提示和测试 HTTP reset 诊断，不宣称零警告。

`migration.py check`、`ready` 均退出码 0；ready 无就绪任务。它们验证记录，不认证 parity。实际 Python 3.8.10 `compileall -q dsh apps/cli` 通过。

### 固定源码双侧 oracle

以下均为本次重新执行。观察单位不同且范围重叠，**不相加计算完成率**。

| 门禁 | 本次结果 |
| --- | --- |
| DeepSeek | 76 matched |
| pi-ai | 322 matched；当前三种实现协议 |
| storage/cache | 4 matched：routing、call-cut、threshold、non-json |
| 固定 Ralph 程序 | 18/18 matched；不是任意 JS Workflow |
| Repeat tool | 13 matched + 1 精确原版缺陷例外 |
| TokenMeter | 15 matched + 1 精确原版缺陷例外 |
| Compaction | 153 matched + 2 精确原版缺陷例外 |
| Inspect | 42 matched + 1 精确原版缺陷例外 |
| Guard | 117 matched + 2 精确原版缺陷例外 |
| Cordis runner | 13 matched + 1 缺陷/指导语适配 + 1 Python stack 适配；15 条旅程、149 个动作 |
| Cordis retirement | 2 matched + 6 精确原版缺陷例外 |
| Cordis tools | 92 matched |
| Approval | 9/9 matched；原样源断言另计 38 项 |
| Cordis core C1–C67 | raw：66 matched、C58 different；显式 acceptance passed |

报告前缀 `.goose/out/migration-audit-`，文件名对应各 `*_oracle.json`；核心收据为 `migration-audit-cordis-acceptance.json`。本次 Node 22.20.0 不同于旧 release gate 要求的 22.22.2：这些是当前开发机复验，不冒充锁定环境的完整 release gate。

DeepSeek/pi-ai 使用受控 HTTP，不是付费远程模型验收；部分 gate 明确不比较所有错误措辞、随机 ID 和精确时序。source assertion 数与 Python parity 场景数分开，不能直接互换。

### 显式浏览器 lane：当前失败

设置 DSH_TEST_CHROMIUM 为本机 Edge，执行 test_native_web_browser.py、test_python_web_plugin.py、test_python_client_build.py：**37 passed、5 failed，184.27 秒**。五个真实浏览器 lane 全部运行而非 skip。

- lifecycle/inspect 已启动原版页面、连接 /api/remote.mux、显示真实 pending 审批；Inspect 还完成目录查询与双页面结果竞争。
- 审批/插件控件存在，但被原版 **Add an API key to get started** provider onboarding 弹窗遮挡，点击驱动超时；Session 插件旅程同样受阻。
- 页面 Runtime/console/network 错误记录为空、Host stderr 为空、正常退出；不能把该超时直接说成 Gateway/插件崩溃。
- native_web_browser_oracle.mjs:291、python_web_plugin_browser_oracle.mjs:70 只关闭 Internal Testing Notice；没有像 portable_browser_oracle.mjs:138 一样点击真实 Configure later 并等待 provider onboarding 消失。
- 全量回归结束后 lifecycle 单独复跑仍为 **1 failed / 19.82 秒**，不是只在并发跑测试时失败。

因此当前无凭据环境的 browser gate 不能直接复现历史绿灯，首要修复对象是观察器/fixture 的首次使用流程。**尚未证明关闭 onboarding 后所有后续步骤都通过**；不登记为原版 bug，也不改断言隐藏失败。

日志/XML 为 `.goose/out/migration-audit-browser.*`、`migration-audit-browser-isolated.*`；详细失败现场保存在 `migration-audit-browser-failures/`。

## 3. 分领域进展

| 领域 | 当前判断 | 不能推定完成的部分 |
| --- | --- | --- |
| Cordis / Loader / lifecycle | 核心闭包已正式验收，本次指定双侧门禁重新通过 | 任意 JS Proxy/跨 realm、未解析动态消费者和完整原版表面。 |
| Canonical boot / CLI / presets | 正式 run_profile 接通，旧 launcher/harness 退役，不再是旧入口缺失状态 | 五个 profile 完整请求→工具→取消→关闭→新进程恢复，不只是 dump/启动。 |
| Agent / Session / storage / projection | 工厂、准备/live write/cold recovery/registry 已验收；domain/cache 后续有实现 | 所有业务 domain、压缩存储、任意跨进程/掉电、原版全部 SQLite 行为和回放消费者的完整等价证明。 |
| DeepSeek / pi-ai | Wire 与三种 pi-ai 协议有真实实现和配对证据 | OAuth/刷新、provider 专属认证、Bedrock/Vertex/Azure/Codex 等未实现协议和真实网络旅程。 |
| Tools / 长运行 / compaction | Repeat、meter、pruner、policy/transaction/command/invariant/error chain/maintenance、approval 持续补齐 | 全部工具策略组合、取消/热替换/关闭交错、长历史 UI/性能与真实网络响应中断。 |
| Canonical Web | 正式 Connection→Gateway→Remote/controllers/ClientModules 已实现，旧业务 carrier 已退役 | 当前 browser gate 缺口、question/approval widget、附件、steer、jobs、子代理、完整设置/重连旅程。 |
| 创造模式 / Inspect / Guard | Python Host runner、守卫、工具、Inspect 和有限浏览器联合能力落地 | 任意原版 JS Host、Node VM/builtin、跨 realm 和 experimental Inspector/CDP。 |
| Workflow / codeRuntime | 不再占位成功：固定 Ralph 真实调度；codeRuntime 明确报告 Python/process | 通用原版 JS Workflow；Node TS worker 的资源度量/执行语义不能自动替代。 |
| Python 插件交付 | 目录/ZIP、源码导出、升级回退、Host/Session Client、锁定纯 Python 依赖、指定哈希 HTTPS ZIP 已实现 | wheel/native、版本范围、namespace/复杂 Remote、preset 引用事务清理、公共目录/npm/PyPI。 |
| Portable / Win7 | 历史已有实际解压候选和隔离运行门禁，不再只有打包脚本 | 本 checkout 无产物/最新解压收据；当前 HEAD 发行重验、授权/资产保留/数据回退、公开发布、Win7 实机与浏览器。 |
| ACP / 外围 | ACP 有部分方法与历史单测，不是完全不存在 | stdio、list/resume/close/setConfigOption、MCP/权限、会话归属；Webhook 等外围须独立验收。 |

### 台账和覆盖指标

`migration/tasks` 实际 **21 项：15 integrated、6 draft**。不是 15/21 项目完成率：task 粒度不同，部分 integrated 只接受窄契约。

六个 draft 为 MIG-DEEPSEEK-WIRE-002、MIG-TOOLS-POLICY-002、MIG-SESSION-REPLAY-002、MIG-WEB-CONNECTION-002、MIG-PROFILE-JOURNEYS-002、MIG-UPSTREAM-DELTA-002。Wire/Web/replay 的部分实现已经推进，不能把 draft 翻译为完全未实现。

盘点含 **272 manifest**（201 runtime、48 frontend、6 platform、9 tooling、7 fixture、1 example），**1227 官方测试文件、14659 个字面声明、1346 动态契约位置**。这是发现量：声明未全部展开执行，动态位置多数是 source-discovery，尚无全范围源断言→本地测试→当前双侧证据的认证映射。

migration README 顶部仍强调 9 月 28 日 registry closure、3235 passed 和当时 domain/Web adapter 限制；不能代替 10 月 2 日完整状态。保留历史记录，同时补当前闭包索引/revision，不要重写历史，也不要重复累计已修复旧待办。

## 4. 先前问题、绕过与当前处置

### 已有后续修复，不应重复列为当前缺失

| 历史问题/替代路径 | 当前处置与边界 |
| --- | --- |
| 非 canonical 默认入口、legacy --mode/--web 分流 | 已退役，正式 profile 主链落地；不恢复旧入口绕过装配错误。 |
| ApiProxy /api/respond、双业务 SSE 替代原版协议 | 可挂载 provider 已删除；/plugins/events 是合法 HMR SSE。历史 domain helpers 仍供旧单测，不算 parity 证据。 |
| 问题/审批丢失 Agent carrier，Web 收不到请求 | 10 月 2 日修复，有正式 Gateway/实际工具链验证；最新 approval signal race、迟到结果及审计 companion 已补。实际 widget 仍待验。 |
| Workflow 占位成功 | 改为真实固定程序调度；未注册脚本明确 SCRIPT_RUNTIME_UNAVAILABLE。fail-loud 不等于通用 JS 已实现。 |
| Terminal reset 持锁重入死锁、跨盘 fs_search 故障 | 后续正式入口/专项有修复，本次全量相关测试通过；真机和链接权限边界另验。 |
| isolate 描述字符串导致 PTC/创造模式碰撞 | 改为唯一身份，正式多预设共存有回归；没有改预设绕过核心语义。 |
| projection cache write/close 顺序和路由 | 后续实现及本次 4 个配对场景通过；原版 rebuildable cache 的 late closed/fail-soft 警告不自动是 bug。 |
| 插件源码导出、升级回退、依赖/Client 一概未实现 | 10 月 1 日多个闭包已落地、本地测试通过；预展开纯 Python 锁不等于 wheel/native/版本求解。浏览器 lane 本次仍失败。 |
| 浏览器断连 WinError 64 导致 mux pump 未取回错误 | 10 月 2 日按 socket EOF 局部退役修复；不代替所有重连/backpressure/多页面旅程。 |
| 用旧域 helper 测试代替正式 Web | 已新增正式入口测试，部分 helper 待退役；先迁移必要断言，不因文件名字有 parity 就认证。 |

早期 P1 复审还记录约 95 个实现 MUST-FIX、62 处测试保真度问题（docs/superpowers/plans/p1-reverify/CROSS.md）。**本轮未逐条重审**：旧数量不能当作现存缺陷数，新测试绿灯也不能自动关闭全部旧条目。需要 finding→当前实现/源版本→回归/双侧收据的处置映射，重点检查错误预期钉死、弱身份断言和只检查文件存在的旧测试。

### 仍保留的语言/平台适配，不是原版 bug

- **PY38-RESOLVED-AWAIT / C58**：JS resolved Promise 与 Python 已完成 Future 调度不同。raw 差分保留，acceptance 只接受精确签名，C59 checkpoint 必须匹配；不能写 67/67 无差异。
- **Python Host / Python process**：明确原生语言后端，没有偷偷运行 Node/QuickJS；固定翻译不能证明任意原版 JS 可原样执行。Host 仍 shell-trusted，不是安全沙箱。
- **WinPTY inferred_idle**：静默推断不是 stdin_read 检测，缺完整 console input-wait inspection。
- **Windows ACL partial boundary**：Everyone grants/hardlink 边界存在，不能包装成强文件系统隔离。
- **环境关闭/时序诊断**：历史 250ms HTTP 敏感性、Proactor socketpair 停滞及析构 warning，不是已确认的原版 bug，也未因一次绿灯证明根因清除。
- **Telemetry 禁用条件**：历史/隔离发行旅程显式关闭 telemetry。OTel 已有实现，不应再说完全缺包；禁用下通过不证明原生依赖/Win7 认证。

## 5. 八类已审核原版缺陷例外

这不是未修复的 Python bug，也不是任意忽略差异：**Python 有有意修正，固定原版仍复现，门禁允许精确差异**。本次相关 gate 全部重新通过。一个缺陷可以产生多个场景，不能按例外行数计 bug 数。

| 标识 | 固定原版故障 | Python 处置 / 本次例外 |
| --- | --- | --- |
| UPSTREAM-REPEAT-001 | 普通对象排序丢失 JSON __proto__ own key，错误认定参数重复 | 保留合法数据键；1 个精确旅程。 |
| UPSTREAM-TOKEN-METER-001 | step/start 快照早于已接受 user input，usage 与 surface delta 双计输入 | 首个匹配 chunk/无 chunk 最终 assistant 前捕获输入面；1 个场景。任意同时写入归属不在证明范围。 |
| UPSTREAM-COMPACTION-POLICY-001 | provider + NUL + model 串接键碰撞，误判合法配置重复 | 真实 tuple；1 个精确场景。 |
| UPSTREAM-COMPACTION-SUMMARY-001 | summary 额外字段覆盖 prepared 元数据，写入错误 shadowedTokenCount | 元数据分离，只复制支持字段；1 个精确场景。 |
| UPSTREAM-CORDIS-INSPECT-001 / INSPECT-001 | Context 卸载不清理 pending Client inspect 查询，等待者不结算 | 幂等 cleanup；1 个精确场景。 |
| CORDIS-GUARD-001 | callable service Proxy 缺 apply trap，同步/异步返回 Context 绕过 guard | __call__ 检查结果/await 结果；2 个场景，同一缺陷。 |
| CORDIS-RUNTIME-001 | 含 NUL 的 method/message 拼接键碰撞，漏报第二个独立错误 | tuple 去重；1 个旅程，同时保留 Python 指导语适配。 |
| CORDIS-LIFECYCLE-001 | stop/undefine 不失效正在 apply 的 activation，迟到提交复活服务/Client | transition 所有权、失效检查、排空和禁止迟到发布；6 个场景，同一缺陷。 |

源记录分别为 10 月 1 日 repeat-tool-reminder、token-meter-replay、compaction-policy、compaction-transaction、cordis-inspect、cordis-guard、cordis-runner、cordis-retirement 进展文档；识别逻辑在对应 scripts/*_oracle.py。固定 reference 没有偷偷修改。

建议统一例外清单：ID、target SHA、精确配方、两侧完整签名、影响消费者、修复提交、源端 issue/修复状态、当前收据。新 target 必须复验；源端修正后匹配就关闭例外，不能扩大 allowlist。语言栈、随机身份和错误文本的比较边界另行登记，不伪装严格全文匹配。

## 6. 新确认和主要未完成项

### ACP：明确迁移版偏差，不只是缺认证

`dsh/acp/server.py:147` 的 _on_session_event 收到任意 Session 的 turn/end 后，遍历**所有**正在 prompt 的记录设置 stop_reason，没有 Session 身份和 turn 身份筛选。

实际 handler 复现：alpha、beta 均有 inflight prompt，只派发 alpha 的 interrupted turn/end，**alpha 和 beta 都从 end_turn 变成 cancelled**。收据为 `.goose/out/migration-audit-acp-session-routing.json`。这是实际 handler 的有界反例，不冒充已经跑通 ACP stdio 或完整双侧 integration。

固定原版 `reference/packages/acp/acp/src/index.ts:134` 按 ID 找记录并检查 ownsSession(session)，`session.ts:387` 还检查 inflight turn identity。原版已有正确归属：此项是**迁移版 bug**，不是第九个原版例外。

原版正式连接注册 initialize/authenticate/new/list/resume/close/setConfigOption/prompt/cancel，带 MCP 和权限处理；本地只有部分直接方法，缺同等 stdio 注册与完整生命周期消费者，显式拒绝 mcpServers。additionalDirectories 拒绝、authenticate 空行为两边均存在，不据此错报缺陷。完整 ACP 需要提供端/消费者闭包，不是只扩 codec 单测。

### 其余独立验收范围

1. **通用原版脚本**：任意 JS Workflow/Host、Node VM/builtin、跨 realm/动态机制未等价。固定 Ralph、普通 Client 构建不能替代；若继续限定原生 Python，必须明确源码兼容边界，不能静默缩小 1:1 目标。
2. **真实 Web 用户流程**：question/approval widget、附件、取消/steer、jobs、子代理、重连、多页面 ownership、HMR 联合失败恢复、压缩历史和完整设置。先修首次使用驱动，再验必要消费者。
3. **业务 projection/instructions/搜索**：文件版本缓存、预算排除集、执行祖先与 step 提交边界的即时 inbox 仍需逐场景认证；web_search.py 重建临时 FTS 视图，不证明原版增量索引/大历史性能。
4. **Provider 深度**：OAuth/刷新、专属认证与云协议；目录模型不等于路由可用。真实 API smoke 另行授权和预算，不用付费网络替代确定性协议测试。
5. **插件交付/治理**：SDK AgentRun/card、跨插件 priority/组件归属、复杂 Remote、preset 引用的升级卸载事务；wheel/native ABI、PEP 440、namespace、公共目录/npm/PyPI、来源信任。指定哈希 HTTPS ZIP 不再整体列为缺失。
6. **发行/平台**：当前候选 clean-checkout、实际解压包、完整授权、资产保留/数据回退、公开发布。Win7 实机/目标浏览器继续用户暂缓，不自行恢复或冒充完成。
7. **覆盖治理**：全范围源断言/参数展开及动态提供端→消费者边不完整；旧 tasks 与新研究记录回填有效 revision，不只增加 pytest 数量。

## 7. 后续行动计划

按依赖和验收风险排序，不估算缺乏依据的剩余工时/百分比；每项带实现、必要消费者和证据共同交付。

| 顺序 | 行动闭包 | 退出条件 |
| --- | --- | --- |
| P0-A：恢复 browser gate | 两个观察器经原版真实按钮完成无凭据 provider onboarding，并等待遮挡移除。保持原版前端不变，不注入 API key 绕过。 | 五个 lane 全执行通过；检查 Runtime/console/network/Host 预期诊断；保留本次失败。 |
| P0-B：当前候选验收整合 | 固定 Node 22.22.2；统一 gate 纳入 Wire/compaction/approval/动态 runner/插件/browser/实际解压 verifier。 | clean candidate→ZIP→隔离解压→五个完整 profile 旅程；receipt 绑定 commit、原版、依赖/前端/观察器哈希；browser/Portable 不许 skip 成功。 |
| P0-C：台账回填 | 保留历史；为后续 Wire/Session/Web/Tools/插件闭包创建或修订 contracts/tasks；统一旧 finding 与八类例外索引。 | check/ready 合法、阻塞准确、当前证据清楚；不自动设置 accepted_upstream。 |
| P1-A：用户主链组合 | 正式 profile 的模型→真实工具→下一请求，question/approval UI、取消、关闭、新进程恢复；standard/creative/PTC 共存。 | source fixture + 本地反例 + HTTP/WS/browser + 源码/解压包同旅程，不止 dump。 |
| P1-B：ACP 提供端/消费者 | 先修 Session/turn 归属，再补 stdio/list/resume/close/config/MCP/权限/取消关闭；必要 subagent 消费者一起交付。 | 两 Session 无串扰、signal/迟到结果/排空匹配原版；真实 stdio 和持久恢复通过。 |
| P1-C：业务状态/长历史 | instructions、projection/cache、FTS、存储边界；损坏尾部、失效重载、取消重放和规模数据。 | 官方断言/参数可追溯、完整两侧值/时序；性能单列，不用小 fixture 推定大历史。 |
| P2-A：剩余功能合同 | OAuth/云协议、通用 JS 明确方案、SDK 治理、experimental Inspector/CDP 和其他未验收模块。 | 各范围有支持合同/反例/消费者验收；不因不属 MVP 写 full parity completed。 |
| P2-B：插件/稳定发行 | native/wheel/版本范围/来源信任与公共获取；授权、升级保留资产、业务回退。 | 离线干净环境和失败注入通过；第三方插件共享 Loader 生命周期，不旁路装配。 |
| 独立平台门禁 | 用户恢复 Win7 验证后，测 Python/DLL/wheel、PowerShell fallback、WinPTY/ACL、TLS、目标浏览器。 | Win7 SP1 实机日志/产物，当前 Windows/Edge 不替代。 |
| 旁线 upstream delta | 只读核实 observed SHA，比较 manifest/exports/tests/协议，计算必要消费者重验集合。 | 不擅自推进 target；换批次经明确决策；原版 bug 例外复核。 |

**下一轮优先 P0-A/P0-B，不是继续泛化扩充 Core 测试。** ACP 的共享提供端/消费者适合一个 owner 共同闭包，不能按目录机械拆开。本轮未启用多智能体、调度器、付费 API、发布或提交。

## 8. 明确限制

本轮覆盖近期核心闭包、八类已审核缺陷例外、选定 source oracles 和浏览器现场；未展开全部 14659 字面源声明、未逐条重审所有早期 P1 findings、未运行完整 verify_release.py/新 Portable 构建，未认证全部 profile/外围模块、远程模型或 Win7。

部分近期文档引用的历史 .goose/out 收据在本 checkout 不存在，主 checkout 也无 dist。不据文档命令/旧 pass 数字推断当前发行状态。本报告分别标注实际复跑、历史声明和计划；新增报告不将问题标为已修复，不更新验收状态。
