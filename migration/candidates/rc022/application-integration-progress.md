# 应用提供方与组合接入

固定目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。本页记录定向检查；生产 pin 已在 C9-CC 协调切换，`accepted_upstream` 仍为 null，完整资格待后续验证。

C9-GL: Closed the C9-GK cleanup finding: 12 completed `files/` roots retired (1,667,734 file bytes), 94 raw observations retained, and original top-level observations/receipts unchanged. Declare the synthetic root for 115 constructing drivers and reject runtime undeclared roots. Retain exact inventories/raw observations before unlinking, guard paths/receipt overwrite, and delete modern-Windows read-only entries without changing shared hardlink attributes. All 67 targeted controls/actual FS consumers and two real Git/client-registry pairs passed, with their fixtures retired. [Record](current-paired-fixture-retention-checks.json).

C9-GK: Use checkout-root Python module entrypoints for all paired drivers, removing dependence on inherited PYTHONPATH or individual bootstrap shims. All 54 controls passed, including an actual direct-file failure/module-success fixture; both sync and async configuration adapters matched their same 180 actual Source schema graphs. Original 47-pass/next-bootstrap-failed lane remains failed. Targeted fixtures and failed temporary roots retired; 12 completed `files/` synthetic roots found by the immediate C9-GL audit remain to be cleaned before the next paired run. [Record](current-paired-module-entry-checks.json).

C9-GJ: Source run21 reached batch14 with zero failed cases, then correctly rejected two unaccounted files excluded by original Windows config. Keep all 476 inventory entries, validate the exact two upstream exclusion patterns, and record planned/executed/excluded identities separately. The affected final 60 entries passed targeted verification: 58 executed files, 1,540 cases passed, two original exclusions unexecuted. All 53 gate/orchestration guards passed; 1,536,242 fixture bytes and 18 links retired. Original failed run and full logs remain; this is not complete Source or release acceptance. [Record](current-source-platform-checks.json).

C9-GI: The original cache eviction test reproduced a Node24.9.0 Windows `rmSync` defect: the dangling `vanished` file symlink remains after removal. Node's official 24.13.1 includes fix #61040 and satisfies unchanged Source's `>=24.9.0` engine. A separately selected/frozen unit-test runtime now runs Source tests; contract observers still use Node24.9.0 and original prepared builds keep their original provenance. All 18 unchanged repository-cache tests and 45 gate/CLI/role-separation controls passed. Original Source lane15 and all raw diagnosis remain failed/preserved; owned temporary caches and both targeted workspaces retired. [Record](current-source-runtime-checks.json).

C9-GH: Run12 complete Python passed (22,601 passed, 34 skips, 3,966 required cases executed); Source batch3 failed the real Git approval case's default 5-second deadline. An isolated reproduction preserved the timeout, and the unchanged case passed in 7.18 seconds under the upstream-supported shared-host budget. Pin 30 seconds in the gate plan for tests/hooks/polling, preserve explicit case deadlines and add human-readable failure diagnostics beside JSON. All 41 gate/orchestration controls passed. Preserved 15,718 original Python observations and removed 1,924,665,022 bytes of synthetic fixtures plus owned caches. Original run12 remains failed without final input recheck or release acceptance. [Record](current-source-budget-checks.json).

C9-GG: Fresh frozen `700d4843` x64 Portable passed all five actual profile smoke cases with its own Python (5 passed, zero skipped). ZIP SHA256 remained unchanged; three targeted workspaces retired (3,702 bytes). This targeted result retains its original scope; run12 later passed Python and failed Source as recorded above. [Record](current-packaged-smoke-checks.json).

C9-GF: Isolate smoke DSH_HOME and disable bundled bytecode writes, since dump-config prepares profile roots. All 25 selected checks passed; 5 unsupplied dist cases remain skipped targeted-only. Actual minimal/standard profile roots were observed inside their owned test homes. Three workspaces retired (9,942 bytes). Run11 stopped during initial freeze before tests/build; its empty output removed and command/log preserved. [Record](current-smoke-isolation-checks.json).

C9-GE: Original frozen run10 remains failed because five mandatory Portable smoke checks skipped, despite 22,593 passing Python cases. Its original XML and 15,701 raw observations are preserved. Removed 47,079 reconstructible files (1,924,597,393 bytes), 6,712 reparse entries and 2,530 read-only directory entries without following targets or changing shared attributes. Clean candidate `2c2bf337` is independently running run11. [Record](current-mandatory-smoke-retry-checks.json).

C9-GD: Run10 completed 22,593 passing Python cases and 39 skips without failures, but the required roster correctly rejected five Portable smoke skips: the current orchestrator built the product only after regression. Build x64 first, explicitly smoke its bundled Python, and reuse the same unchanged ZIP later. All 20 orchestration/negative controls passed; 3 targeted workspaces cleaned (8,494 bytes). Original run10 remains failed, without final input integrity or unified acceptance. [Record](current-portable-order-checks.json).

C9-FT：嵌套完整回归使用同一次冻结的 checkout 清单，严格原件与所有权校验保持；92 项通过，3 个目录清理、回收 685,519,985 字节。见[检查](current-nested-preflight-checks.json)。

C9-GC: Complete frozen run09: 22,592 passed, 39 skipped, one failed, no setup errors. The single Git cleanup assertion has C9-GA/GB targeted fixes; all prior run07 failures are absent. This remains failed qualification without final input recheck. Preserved 15,702 raw observations, removed 47,080 reconstructible files (1,924,891,251 bytes); unlinked 6,712 reparse entries without following targets and 2,530 read-only entries without shared attribute changes. [Record](current-single-failure-retry-checks.json).

C9-GB: Remaining pwsh kill/abort, ripgrep and sandbox-shell direct-done assertions await existing managed-range cleanups. All 41 relevant actual process consumers passed; 3 workspaces cleaned, 4,774 bytes removed. Owner-unload and production semantics unchanged. [Record](current-process-consumer-cleanup-checks.json).

C9-GA: Run09 exposed a remaining GitRunner fixture race between direct done and managed-range cleanup. The fixture now awaits existing cleanup tasks; all six actual Git cases passed, production behavior unchanged. Three workspaces cleaned, 114,020 bytes removed. Run09 remains an independent frozen diagnostic. [Record](current-git-range-checks.json).

C9-FZ: All known run07 failures have targeted follow-ups. Independent clean candidate `01499ca4` started its single complete qualification in run09 after 23 bound inputs were verified. Run08 stopped before tests and remains incomplete; no release acceptance is implied. [Candidate record](current-stable-candidate-start.json).

C9-FY: Frozen run07 completed 22,626 Python cases: 22,511 passed, 46 skipped, 51 failed and 18 setup errors. It remains failed, without final input recheck or release acceptance. Original diagnostics and 8,548 raw observations preserved; 37,205 reconstructible files removed, reclaiming 1,249,473,666 bytes. Known failures have targeted follow-ups; the next stable candidate requires its own complete gate. [Record](current-complete-regression-retry-checks.json).

C9-FV: All 8 original remaining HMR update consumers and the Web preset composition identity check passed. A wider 360-second diagnostic timed out; its result remains incomplete. 9 owned directories cleaned, 202,672 bytes removed. [Record](current-final-consumer-checks.json).

C9-FW: Use the real Cordis effect runner in the editor fixture, dispose fixture effects, and accept canonical content block arrays in the ACP observation predicate without changing the expected child result. 13 targeted tests passed. [Record](current-editor-acp-fixture-checks.json).

C9-FX: Preserve original receipt bytes in Git for explicitly bound inputs. Existing corpus, expectations and input hashes remain unchanged. 872 targeted tests passed. [Record](current-released-checkout-checks.json).

C9-FU：SQLite Remote 夹具显式隔离 DSH_HOME，真实迁出、三预设模型/分叉/搜索/冷启及 Session Remote 共 7 项通过；3 个目录清理、回收 1,592,334 字节。见[检查](current-sqlite-home-checks.json)。

C9-FS：规范 Source 路径下实际生成终端描述与双向通信通过，保持 wire 字段；Shell Job 等既有范围清理后再断言无活动进程。3 项通过，3 个目录清理、回收 17,414 字节，保留 6 份观察。见[生成通信检查](current-generated-carrier-checks.json)。

C9-FR：当前 Source 时区观察的 Node 版本断言由残留的 22.22.2 对齐到固定 24.9.0，UTC/上海偏移、日期恢复/解析和属性格式仍精确比较。8 项实际原版与 Python 3.8 检查通过，3 个工作目录清理、回收 29,124 字节，历史观察器运行时保持独立。见[当前 Source 时区检查](current-source-timezone-checks.json)。

C9-FQ：实际 PowerShell 回归先等待既有 managed range 清理任务，再断言 live 集合为空；与固定原版的直接 `done`、后续 `waitForExit` 分离保持一致，生产行为不变。80 项真实输出/普通进程/资产保留检查通过，两次定向的 6 个目录清理、回收 448,092 字节。见[进程范围排空检查](current-pwsh-range-drain-checks.json)。

C9-FP：07 checkout 本身位于系统临时目录，真实文件系统政策允许临时目录写入，令“目录外拒绝”夹具失真。下一独立候选移到临时目录之外，保持实际政策不变；干净候选、独立固定 Source 及 30 项真实围栏/输入/生命周期/HMR 检查通过。3 个定向目录清理、回收 937,783 字节；活动 Source 复制品与依赖链接明确保留到下一统一资格最后消费者结束。见[隔离布局检查](current-isolated-workspace-checks.json)。

C9-FO：检查注册表身份断言按当前 Cordis 返回值追踪在两端解包 `cordis.original`；保留类型、37 毫秒期限、查询拒绝和 Host/监听器回收断言。完整 Runner/Inspect 7 项通过，3 个工作目录清理、回收 30,246 字节，生产身份行为不变。见[检查代理身份](current-inspect-proxy-identity-checks.json)。

C9-FN：以 120 毫秒扫描延迟复现原 60 毫秒夹具未观察到删除而误判为修改；原版与 Native 夹具均先等实际目录库存观察到删除，再开始既有间隔，生产 watcher 与时间窗口不变。3 项回归、全部 9 场景实际配对及修复前后控制通过；5 个目录清理、回收 903 字节，原始观察保留。见[删除检查点](current-hmr-unlink-checkpoint-checks.json)。

C9-FM：HMR 静态扫描遇到已加载独立模块中未执行的相对导入，不再因缺失包名或越过顶层而中断；有效导入边、缓存与替换所有权保持。48 项图扫描、热替换和实际包安装/更新/恢复/卸载消费者通过，图与 Profile 两组当前原版/Native 配对通过。三次定向运行的 9 个目录已清理、回收 656,808 字节；原失败和实际配对观察保留。见[相对导入图检查](current-hmr-relative-import-checks.json)。

C9-FL：70 份测试/探针的旧准备 Source 路径统一改为规范 `reference`，Analytics 使用明确输入或门禁 PATH 中的 Node；保留原 pin、字节与实际 artifact 检查。31 项实际消费者及 5 组原版/Native 配对通过，71 份修改的 Python 文件均由 3.8.10 解析通过；3 个定向工作目录清理、回收 1,075,163 字节，实际观察保留。07 其它独立失败另行修复，尚未统一签收。见[规范 Source 路径检查](current-canonical-source-path-checks.json)。

C9-FK：07 的全新 Windows 检出暴露账号语言文件缺少字节保留属性，16 份 LF 文件被转成 CRLF，严格原版摘要正确拒绝。现为包内 locale 增加 `-text`，保持原摘要及全部断言；3 项账号回归通过，显式 `core.autocrlf=true` 的新鲜检出中全部 18 个成员精确摘要通过。4 个工作目录清理、回收 45,883 字节。见[语言文件检出检查](current-locale-checkout-checks.json)。

C9-FJ：确认早先失败的 03 轮已结束且没有活动进程后，按原映射清理其失效合成工作区；3740 个文件共 26,705,419 字节已移除，1006 份原始观察逐份核对后保留。36 个链接只删除自身，476 个只读 Git 目录项未改共享属性；原失败、输入清单、收集记录及日志保持。自动审批已拒绝的旧 Edge 配置和零字节标记未再次尝试，当前 07 与活动依赖输入不受本次清理影响。见[过期回归资产检查](current-stale-regression-retention-checks.json)。

C9-FI：冻结 `c756b9fc` 的 07 发现读取身份破坏性控制把预期已为 false 的字段再次写成 false，实际没有修改输入；严格校验器保持正确。负例现明确断言原值后改为 true。整组 39 项通过，含全部读取回执控制、实际当前原版/Native 16 场景及观察器控制；3 个临时目录清理、回收 18,878 字节，真实观察保留。该测试修正不计入冻结 07，后者继续收集其它问题。见[读取身份控制检查](current-read-identity-control-checks.json)。

C9-FH：发行回执正例及 SDK 值、运行时、必需消费者控制共 54 项通过。冻结 `ee1e7f5a` 的 06 在共享 SDK 初始化重复失败后停止，停机快照 200 项、最终原始失败 206 项均保留；完整 Python 与最终输入复核未完成，不构成资格。已清理原短工作区、本次定向工作区和六个 SDK 合成 home，回收 119,309,768 字节；950 份原始观察、六份真实 SDK 会话及冻结清单保留。C9-FD/FE/FG 已定向关闭已知问题，下一稳定候选重新执行单次完整资格。见[SDK 回执与重试检查](current-sdk-receipt-retry-checks.json)。

C9-FG：保留的 v3 机器观察器为自身旧子代理提供方显式接上真实后代排空方法，适配随 Context effect 撤销；生产 SDK 与当前提供方保持不变。四项旧 SDK 旅程明确标记为历史兼容，连同完整共享 Agent 机器消费者共 69 项通过；3 个临时目录清理、回收 1947 字节。当前 SDK 资格仍由独立 rc022 探针和新鲜统一候选验证。见[旧 SDK 关闭兼容检查](current-retained-sdk-shutdown-checks.json)。

C9-FE：SDK 严格导入清单补齐当前查询/ACP 接入实际新增的三个模块，保留全部缺失、额外模块及字节校验。实际当前 Source/Native 三场景与严格消费者/路径检查通过；本次合并定向运行共 66 项通过、两项旧机器子代理关闭用例失败，后者另作兼容夹具跟进。原始完整运行及定向失败均保留，不标为通过；已清理 3 个工作目录、回收 6,216,430 字节。见[SDK ACP 导入检查](current-sdk-acp-imports-checks.json)。

C9-FD：冻结 `ee1e7f5a` 的统一门禁 06 发现更新启动检查把替换 Host 进程预热计入一秒生命周期等待；定向注入第二次预热 1.1 秒延迟后稳定复现。夹具先以独立 15 秒边界等待宿主准备，再保留全部原一秒检查及行为比较，生产期限不变。整组 20 项通过，6 个临时目录清理、回收 7495 字节。该修复不计入冻结 06，后者继续收集其它问题。见[退场夹具准备检查](current-retirement-preparation-checks.json)。

C9-FC：冻结 `e99904f4` 的统一门禁 05 在约 17% 因已知预设启动错误持续产生无效失败，保存 30 项原始失败后停止自有进程树，保持失败/未完成身份；未执行最终输入复核。修复后 12 项完整 Python 诊断、19 项完整插件退场回归通过。两次定向运行及原短工作区已清理，保存 721 份原始观察，合计移除 7,031,039 字节；只读 Git 对象仅删除自有目录项，未更改共享属性。下一干净候选重新执行单次统一资格。见[诊断与重试](current-unified-diagnostic-retry-checks.json)。

C9-FB：服务返回值追踪保留 `cordis.original` 原始身份，符号调用仍绑定使用端；返回插件构造器时不调用实例 `_extend`。72 项协议/作用域、8 项构造器、83 项 Session/Commands/Loader、140 项 Cordis 消费者、3 项实际原浏览器及新增身份/构造器 Source/Native 配对通过。8 个已结束运行的 24 个工作目录已清理，回收 1,780,912 字节并保存失败原始观察。冻结 `e99904f4` 的统一门禁 05 不含本修复，仍独立收集问题；本项仅为定向完成。见[追踪身份检查](current-trace-identity-checks.json)。

C9-EV / EW / EX：当前 Agent v4 的实际 Source/Native 取消与恢复配对及 4 项回归通过，28 项维护/压缩消费者通过；持久化取消原因仅保留原版规定字段，实时信号原因身份不变。Context 的定义/使用双层作用域、返回影子解包和子插件独立 inject 按原版修正，47 项直接消费者、20 项签名回归和实际配对通过。最后 6 项旧启动/配置/命令/epoch 断言经正式入口更新，42 项通过，分别提交 `3f4ea72d`、`535439e7`、`e41cac3e`。这些结果均为定向检查；见[取消信号](current-agent-signal-checks.json)、[作用域](current-shadow-context-checks.json)、[启动消费者](current-loader-consumers-checks.json)。

C9-EY：失效准备版 Portable、修改过的解压副本和三份重复输入已移除，回收 1,112,124,487 字节；保存旧 provenance、修改模块、会话观察和一份字节相同的压缩输入。两个约 11 MiB 的旧 Edge 配置及零字节标记此前被自动审批拒绝删除，继续明确保留，未绕过策略。用户开启开发者模式后文件符号链接实测通过；新统一门禁 04 在干净 `e41cac3e` 上启动，仍在进行，不构成签收。见[清理与系统条件](current-preparation-retention-checks.json)。

C9-DA：同步全部 673 份当前原版 `apps/web` 源码镜像，既有 371 份原样构建产物哈希保持。PWA、启动/资源 URL、真实活动 Loader、反馈 v3→v4 夹具及文件引用行所有权已定向修复；最后广域 164 项通过/两项失败后，其余四项消费者复验与实际 25 行 Source/Python 配对通过。40 个历史快照保留原 pin 和 207 文件字节身份，不冒充当前 74 个场景。首轮完整回归原失败保留，完整资格仍待新的稳定候选。[检查](web-source-contract-checks.json)。

C9-DB：当前统一门禁一次执行完整 Python 集合并收集普通用例失败；既有内部调用保持默认首错停止。55 项定向检查包含真实的三失败/一失败隔离执行，工作区已清理。`8f69c6a1` 原门禁的最终输入与候选复核均未漂移，结果仍为失败，未执行后续 Source/配对/打包。[检查](complete-failure-collection-checks.json)。

C9-DC：补齐另外两份授权事件/网关观察器的当前凭据夹具，26 项消费者与实际 9 行、8 行 Source/Python 配对通过，临时资产已清理。这些后续提交不计入已冻结 `3f20446c` 的完整诊断运行。[检查](credential-observer-consumers-checks.json)。

C9-DD：冻结依赖时复用普通文件已有的类型信息，仍逐文件读取 SHA-256 并核验链接边界。27 项相关回归通过；原版 653 文件的只读样本清单完全相同，减少 1428 次重复类型查询，不推广样本用时。3145 字节合成夹具已清理，当前冻结候选运行保持不变。[检查](freeze-metadata-checks.json)。

C9-DE：独立检出暴露两份原版 JSONL 夹具此前被日志忽略规则挡住，现以局部精确白名单纳入 Git，并使源码镜像检查同时验证索引。11 项相关检查通过，全部 673 份当前原版源码的暂存 Git blob 完全一致；用户根 `.gitignore` 修改保持独立。空工作区已清理，原门禁继续收集其它问题。[检查](tracked-web-fixtures-checks.json)。

C9-DF：HMR 根事件分类改用运行时缓存的 `has(url)` 查询，保持字典载体回退；相对/绝对别名和规范 URL 均覆盖。18 项定向、19 项当前原版监听测试、6 组实际 Source/Python 对照通过。6045 字节夹具和两个测试链接已清理，原门禁继续独立收集完整失败。[检查](hmr-cache-query-checks.json)。

C9-DG：旧重载事务回滚断言改按当前原版的尽力应用、原始候选/目标所有权保留和修复后恢复验证；完整移植当前重载文件的四类失败、初始文件、schema 和 overlay 用例。修复新建 Context 缺少 Loader 被误判为退出的问题，23 项最终定向、10 项原版及 11/8/8 组实际对照通过。约 43 KiB 夹具已清理，原失败诊断保留；完整门禁继续收集其它问题。[检查](current-reload-contracts-checks.json)。

C9-DH：81 个旧 LLM 用例和 21 类能力观察保留历史 Source 原始字节，当前兼容提供方重新执行，124/29/34 项定向通过，原始失败诊断保留。独立当前 Messages/Session 七组实际配对通过；搜索 Source 观察器触及原有 60 秒期限，作为未解决项继续诊断，不作通过声明。约 3.69 MiB 夹具已清理，真实会话日志另存。[检查](historical-llm-capability-checks.json)。

C9-DI：SDK 三场景导入清单补齐当前问题服务的四份实际模块，64 项真实 Source/Native 与严格消费者检查通过；约 5.97 MiB 夹具已清理，八份实际观察保留。搜索超时隔离后，完整原始观察器与 Native 对照重新通过；原超时诊断保留，未放宽期限或修改原版，取消时序仍随完整门禁观察。[检查](sdk-question-import-closure-checks.json)。

C9-DJ：39 个共享门禁夹具同时缓存失败初始化，后续消费者仍逐项失败并引用原始原因，避免重复启动进程和复制相同目录。11 项定向通过，临时夹具清理完成。`3f20446c` 完整运行在约 19% 因重复 SDK 初始化失败主动终止，保持失败/未完成状态且继续最终字节复核；剩余用例另作诊断子集，不能拼接为完整验收。[检查](shared-gate-observer-checks.json)。

C9-DK：预设清单按包声明读取全部补丁，真实 Launcher 帮助、当前资源解析、独立检查工具和 Python 管理扩展分别验证；修复提前取消的插件包装任务遗留未启动协程。106 项定向通过，约 12 KiB 合成夹具及帮助命令临时 home 已清理，原失败和警告保留。[检查](profile-setup-ownership-checks.json)。

C9-DL：五类 Cordis 历史观察固定原 pin，以 16 份最小原版源码字节核验，兼容检查与当前 Web 消费者分别验证。原 323 项通过后，剩余分发/订阅入口修正的 7 项及五份身份复验通过；当前原版检查注册表 26 组实际对照通过。约 143 KiB 合成资产清理，19 份实际观察保留，不提升历史 bug 例外为当前资格。[检查](cordis-historical-current-consumers-checks.json)。

C9-DM：12 类生命周期和两类 Loader 消费者改用当前原版实际观察，Include 刷新归属、失败树保留、Handle 恢复和服务实例 epoch 均按新合同验证。38 项首轮通过后，单项 epoch 修正及 2/1 项消费者/身份复验通过；当前 HMR 公共接口 7 组实际对照通过，退役 API 不再冒充当前证据。六轮已结束合成资产清理，旧失败保留；冻结运行 03 最终输入与候选均未漂移，仍为失败/未完成。[检查](current-include-lifecycle-checks.json)。

C9-DN：Client 定义预检从旧 Node 22 语法限制迁至当前 Node 24.9，支持资源声明、新正则修饰符和分支重复命名组；以 token 前瞻区分 `await using` 表达式，保留 Acorn 原字节和只编译边界。115 项实际 Node、双架构解析、定义原子性和 Native runner 兼容检查通过，首轮 9 项执行边界检查亦通过；失败分类已修正并保留原日志，临时工作区清理完成。[检查](current-client-syntax-checks.json)。

C9-CX：Win7 Desktop 外壳的旧来源与当前宿主/前端输入分开核验，明确私有管道 v3 并非当前原版 Desktop v4 生命周期。首轮 158 项通过、一项旧异步消费者失败，修复后 26 项及诊断编码两项复验通过，原始失败保留；失效工作区已清理。[范围与限制](../../../docs/research/2026-11-18-win7-desktop-current-scope.md)、[检查](desktop-current-scope-checks.json)。

C9-CV：统一入口接到当前完整合同，冻结实际安装依赖/双架构构建输入和观察器；新鲜 x64/x86 包运行完整 SDK、Office、元数据、原版浏览器、应用冷恢复及 Standard Desktop 打包检查。相关 89 项与最后 47 项定向通过；这些单元控制不构成实际统一资格。已清理约 2.0 MiB 失效夹具。[编排检查](current-orchestration-checks.json)。

C9-CU：8 组旧域消费者明确转为历史兼容单元模型，518 项定向检查及 14 个独立当前原版/Python 配对通过；原始历史观察未改写，未提升为当前资格。C9-CT 同时修复贡献方生命周期所有权，124 项相关检查通过。临时工作区已清理；完整候选验收仍待统一门禁。[历史消费者](historical-domain-transition-checks.json)、[生命周期](lifecycle-compatibility-checks.json)。

C9-CS：正式启动解析表已接入新版提问服务和工具；生成的授权 Remote 调用修复为使用明确导出适配器，并保持其资源读取与调用前授权。41 项本地通过，实际隔离解压 Python/原版 Chromium108 完成限时提问、迟到回答、刷新与新进程恢复两阶段；没有浏览器或 HTTP 错误。调试解压修改单独留档，不认证旧 ZIP；旧兼容消费者失败仍待后续处理。已清理本轮失效资产。[记录](current-question-canonical-checks.json)。

C9-CR：限时提问提供者完成：前台等待与 Client 声明、超时后可回答投影、迟到答案消息及接纳、重复回复所有权、Remote 与两种工具 schema。37 项本地、98 项原版及两组当前配对通过，输入前后不变；正式启动链路接入和浏览器验收仍待下一部分。已清理自有合成工作区。[记录](current-question-providers-checks.json)。

C9-CP：回执破坏性控制改用内存 JSON 值，保留文件边界和全部原案例并新增 3 项。首轮时限前 1,383 个连续成功标记、余下 147 项完整 XML 通过分别记录，未拼接成单次完整资格；失效合成工作区已清理。[记录](parser-memory-controls-checks.json)。

C9-CQ：实际构建输入身份工具完成 12 项控制，以及当前 Node/Source 135,100 文件、10,363 链接和双架构 Python 的实测枚举；绑定标准库、DLL 与精确锁定分发包，缺失可选链接的出现也会改变身份。仅为输入工具定向完成，尚未接入新的统一编排或提供冻结验收资格；临时夹具已清理，输入清单和原失败诊断保留。[精确记录](current-input-identity-checks.json)。

C9-CO：权限旧 SettingsProvider 合同转为明确的历史兼容回归，原版成员及其输入摘要原样保留、Native 旧域重新执行；所有旧案例及拒绝检查保留，相关 137 项通过。新版权限目录与配置编辑表单分别重新执行当前原版/Python 配对，冻结输入前后不变。没有用旧域观察替代新版资格，临时工作区已清理。[精确记录](permission-contract-transition-checks.json)。

C9-CN：保留回执解析器的 1,527 个单元案例全部覆盖通过（前 865 项、修正清单后的余下 662 项分别记录，最终 5 项复验）。旧版原始成员只支撑显式测试模型，当前 SDK/元数据独立采集；没有跳过案例或将历史观察提升为新版资格。已删除约 13.1 GB 合成回执及失效工作区，并修正临时定向运行器的清理映射。[精确记录](retained-parser-controls-checks.json)。

C9-CM：SQLite 历史读兼容检查移除当前原版已删除、且未参与该检查的五个包路径；实际使用的 Native 编解码器、组件资源、生成器和封存 alpha 帧仍受摘要保护。38 项定向检查通过，包含 826 个完整编解码观察；已清理重建输入和重复 Source 拷贝。[精确记录](historical-sqlite-inputs-checks.json)。

C9-CL：Windows 元数据消费者使用当前固定原版和 Node24 重新对照；原有 38 项控制保留，最终相关定向检查 50 项通过。实际解压 Python 完成全部 7 类文件和 256 次句柄探测，显式检查所选解释器和导入字节；只读测试文件在最后消费者结束后恢复并清理。完整冻结资格仍待后续。[精确记录](current-metadata-consumers-checks.json)。

C9-CK：SDK 消费者迁移至当前 Messages/v4 协议，保留原有 59 项控制，新增上传区间、会话、事件和时钟破坏性检查；新增检查与解压门禁等共 17 项通过。实际解压三场景完整事实与原版一致，运行末尾因同时更新门禁清单触发输入冻结失败，原失败保留并另行定向复核，未声明完整资格。清理约 18.6 MB 已用完资产。[精确记录](current-sdk-consumers-checks.json)。

C9-CJ：实际解压的隔离 Python 3.8.10 与原版 Chromium108 完成 Schedule/Discover 的首次运行和冷恢复四阶段。修复 Portable 插件列表重复扫描安装图造成的阻塞；每次查询复用解析器，下一次查询重新读取文件。48 项定向控制与固定 Source 清单/选择对照通过，旧失败诊断和会话保留，失效测试资产已清理。此次使用显式修补的调试解压目录，不认证原 ZIP；冻结包统一资格仍待完成。[精确记录](current-application-journeys-checks.json)。

C9-CF：当前 SDK 的实际 Source/Python 正常工具往返、错误和取消进程配对通过；补齐默认会话日志上传、UTF-8 限额与调用者所有的排除规则。12 组独立 Source 对照及 49 项直接消费者检查通过，已清理本轮失效工作区。[精确记录](sdk-process-upload-checks.json)。

C9-CG：显式整理 472 个原版测试文件、399 个当前配对入口，另记 6 个待实际安装/解压验收接替的开发载体。新门禁通道的 14 项控制、110 项原版测试和 4 种实际配对回执检查通过；整份清单及完整 Python/解压浏览器资格尚未执行。[通道记录](current-gate-lanes-checks.json)。

| 单元 | 已验证边界 | 记录 |
| --- | --- | --- |
| C8-A | 带类型的上传回执、已存图片准入、混合图片预算和取消/卸载 | [上传](upload-checks.json) |
| C8-B | 工作目录状态、串行变更、丢失恢复、系统提示词和卸载等待 | [工作目录](working-directory-checks.json) |
| C8-C | 由 volatile 配置推导表单、密钥默认值清除与表达式保留 | [设置表单](settings-schema-checks.json) |
| C8-D | 实际 Config 实例的表单描述、版本、脱敏、继承重置与字段编辑 | [设置描述与编辑](settings-forms-checks.json) |
| C8-E | 真实 profile 持久编辑、配置重挂载、激活失败回滚和重启 | [配置编辑器](config-editor-checks.json) |
| C8-F | 注释保留、HMR 并行编辑串行提交、旧设置重命名导入 | [设置生命周期](settings-lifecycle-checks.json) |
| C8-G | 会话技能目录使用实际工作目录、冷读预设租约、热替换与失败释放 | [技能目录](skill-catalog-checks.json) |
| C8-H | 目录切换后的文件读写、检索、补全索引、一次性 shell 与绝对交付路径 | [工具目录消费者](directory-consumers-checks.json) |
| C8-I | 本地终端启动目录、持久 shell 复用、重置及实际 WinPTY 检查 | [终端启动目录](terminal-directory-checks.json) |
| C8-J | 持久 PowerShell 的分段输出、退出竞争、取消、创建合并与卸载回滚 | [持久 shell 协议](persistent-protocol-checks.json) |
| C8-K | 指令双用户根目录、配置空列表、基线身份与全局/项目逻辑作用域 | [指令配置与作用域](instruction-config-checks.json) |
| C8-L | 用户级/项目双链预算、截断与生效记录、变更批次及帧转义 | [指令预算渲染](instruction-render-checks.json) |
| C8-M | 指令发现、限额流读取、内容去重、作用域探测与文件系统 BOM 解码 | [指令文件读取](instruction-files-checks.json) |
| C8-N | 会话可见指令、候选去重/提升、元数据快路径与失败组回滚 | [指令状态协调](instruction-state-checks.json) |
| C8-O | 指令运行时、嵌套工具/步骤提交边界、串行投影及真实 Agent 请求 | [指令运行时](instruction-runtime-checks.json) |
| C8-P | 终端流字节背压、窗口独立保留、活动观察与失败清理重试 | [终端流与保留](terminal-flow-checks.json) |
| C8-Q | 执行环境默认 shell、并行候选发现、PATH/PATHEXT 与带类型缺失错误 | [终端 shell 发现](terminal-shells-checks.json) |
| C8-R | 屏幕逻辑行投影、最新相对分页与 Unicode 16 字素安全截断 | [终端屏幕投影](terminal-screen-checks.json) |
| C8-S | 原版 xterm 在既有 Win7 JS 引擎运行、屏幕序列化/标记与工作进程生命周期 | [原版终端屏幕引擎](terminal-engine-checks.json) |
| C8-T | BrowserTerminal 有序输入/输出、控制权、重连、尾部排空和关闭重试 | [终端进程所有者](browser-terminal-checks.json) |
| C8-U | 会话终端分配去重、关闭排他、失败保留、沙箱启动和所有者卸载 | [终端控制器](terminal-controller-checks.json) |
| C8-V | 规范 WinPTY 异步输出、真实缩放、前台/活动身份与完整 Job 清理 | [本地终端提供方](winpty-terminal-checks.json) |
| C8-W | SDK 服务端目录 RPC、真实子进程 stdio 调用与会话持久目录隔离 | [SDK 工作目录](sdk-directory-checks.json) |

| C8-X | 新版 Workflow PTC Host、固定目录、绑定校验及晚启动子代理取消回收 | [Workflow PTC Host](workflow-host-checks.json) |

| C8-Y | 原版 Workflow Guest 私有执行域、真实子代理、进度排空与 v4 冷查询 | [Workflow Guest 执行](workflow-guest-checks.json) |

| C8-Z | 新版 Workflow 引擎准入、事件、卸载后运行及 Workflow/Ralph 消费者 | [Workflow 引擎](workflow-engine-checks.json) |

| C8-AA | SDK 持久会话恢复、拥有者等待、定时恢复共享与托管子树退出 | [SDK 会话所有权](sdk-session-checks.json) |

| C8-AB | SDK 审批归属、提问回答校验、实际工具往返及即时取消 | [SDK 人工交互](sdk-interaction-checks.json) |

| C8-AC | 内置命令定义身份、精确名称/中文别名优先级与 SDK 查询输入准入 | [SDK 输入与命令身份](sdk-input-checks.json) |

| C8-AD | SDK 原生命令查询、活动归属、输入静止屏障与目标终态通知 | [SDK 查询活动](sdk-query-checks.json) |

| C8-AE | SDK 高层 run、持久回执区间、命令生命周期及会话恢复消费者 | [SDK 客户端运行](sdk-client-run-checks.json) |

| C8-AF | SDK 传输首次失败、EOF 最后一帧顺序与错误封装 | [SDK 传输关闭](sdk-closure-checks.json) |

| C8-AG | SDK 直接创建者谱系、原始子会话来源及退出后的通知快照 | [SDK 子会话谱系](sdk-lineage-checks.json) |

| C8-AH | 子进程错误继承、启动失败分类与原始原因保留 | [子进程错误合同](subprocess-errors-checks.json) |

| C8-AI | 规范普通进程对象合同、挂起后 Job 分配与后代生命周期 | [普通进程启动](ordinary-spawn-checks.json) |

| C8-AJ | 任务输出绝对字节环、UTF-8 淘汰与生产者终态后的最终拉取 | [任务输出环与泵](job-output-checks.json) |

| C8-AK | 当前任务注册表、会话所有权、输出消费游标与终态清理 | [任务注册表](job-registry-checks.json) |

| C8-AL | 当前任务工具、内联/暂存通知、读取撤回与用户输入释放等待 | [任务工具与通知](job-tools-checks.json) |

| C8-AM | Shell 准备及进程生命周期到任务的适配、转后台与沙箱输出标记 | [Shell 任务桥接](shell-job-checks.json) |

| C8-AN | 当前 PowerShell 执行对象、准备期限、结果投影与真实 Windows Job 进程 | [Shell 执行生命周期](shell-execution-checks.json) |

| C8-AO | 当前沙箱提权类型错误、有效模式短路及八语审批显示文本 | [沙箱提权合同](sandbox-escalation-checks.json) |

| C8-AP | 当前 PowerShell 工具动态注册、前台转后台、实际进程输出接续与取消 | [PowerShell 工具](pwsh-tool-checks.json) |

| C8-AQ | 当前受限 PowerShell、每进程沙箱事实与真实 ACL 拒绝映射 | [受限 Shell 执行](sandbox-shell-checks.json) |

| C8-AR | 当前共享沙箱策略、执行环境路径与会话级可写目录授权 | [共享沙箱策略](sandbox-policy-checks.json) |

| C8-AS | 当前物理可写根派生、目录联接拒绝与每次操作重新校验 | [物理可写目录](writable-roots-checks.json) |

| C8-AT | 补丁批量解析、原输入行诊断及 Unicode/EOF 文本匹配 | [补丁解析与应用](fs-patch-checks.json) |

| C8-AU | 当前文件补丁/删除/移动、双目标锁、部分成功与五类修改沙箱 | [文件修改与权限闭环](fs-mutations-checks.json) |

| C8-AV | 当前文件监听就绪、过滤、错误/取消清理与可等待关闭 | [文件监听生命周期](fs-watch-checks.json) |

| C8-AW | 整份补丁预检、顺序提交、部分成功与删除观察 | [补丁执行器](patch-execution-checks.json) |

| C8-AX | 补丁模型工具、差异回放、配置选择与当前单次提权 | [补丁工具接入](patch-tool-checks.json) |

| C8-AY | 当前文本工具、规范执行路径、差异元数据与类型化校验 | [文本工具消费者](file-consumers-checks.json) |

| C8-AZ | 权限目录 Remote、当前选择投影与 Auto 生命周期/恢复准入 | [权限目录](permission-catalog-checks.json) |

| C8-BA | 当前图片工具、异步附件存储、格式/模型准入与错误码保留 | [图片工具消费者](image-tool-checks.json) |

| C8-BB | Auto 审核封闭决策协议、流结束/关闭与拒绝显示文本 | [Auto 审核协议](auto-review-decision-checks.json) |

| C8-BC | Auto 审核会话快照、调用事实校验与指令权限分层 | [Auto 审核输入](auto-review-snapshot-checks.json) |

| C8-BD | Auto 审核工具钩子、当前审批服务与卸载/关闭语义 | [Auto 审核接入](auto-review-gate-checks.json) |

| C8-BE | 后台任务 Remote、非消费观察、输出续传与人工停止 | [后台任务 Remote](job-controller-checks.json) |

| C8-BF | 真实 Loader 插件清单、失败恢复、禁用条目元数据与预设组合 | [Host 插件清单](plugin-inventory-checks.json) |

| C8-BG | 插件安装 Registry 并行探测、共享缓存、超时与 HTTP 清理 | [Registry 探测](registry-probe-checks.json) |

| C8-BH | 插件启停补丁、冗余覆盖移除、注释/锚点/别名与原子保存 | [持久化插件启停](plugin-switch-checks.json) |

| C8-BI | 管理器插件 Remote、可编辑性、操作锁、变更事实与 HMR 结果 | [插件管理核心](plugin-manager-core-checks.json) |

| C8-BJ | 安装来源解析、固定 Git 身份、凭据脱敏与失败分类 | [插件安装身份](install-spec-checks.json) |
| C8-BK | Bundle 清单、官方目录、来源与更新资格、平台兼容性及真实 HMR 启停 | [Bundle 管理](bundle-inventory-checks.json) |
| C8-BL | 精确版本豁免 Remote、风险确认、实时重新准入与撤销及诊断身份 | [管理器版本豁免](manager-exemptions-checks.json) |
| C8-BM | 注册源规范化、私有源隔离与重试归因、已发布版本排序和元数据 | [注册源与版本规则](registry-policy-checks.json) |
| C8-BN | 构建脚本待批准策略、精确许可、凭据过滤与 YAML 原子编辑 | [构建批准](build-approval-checks.json) |
| C8-BO | 插件详情文档选择、语言回退、本地文件边界与图片响应 | [详情读取基础](plugin-detail-checks.json) |
| C8-BP | 详情 HTTP/CDN 实读、重定向边界、超时取消与正文完整性 | [详情网络读取](detail-http-checks.json) |
| C8-BQ | Bundle 详情 Remote、官方待安装包与可逆 Connection 图片路由 | [管理器详情集成](manager-detail-checks.json) |
| C8-BR | 包元数据查询进程、参数与环境边界、超时取消及回收 | [包查询进程](package-view-checks.json) |
| C8-BS | 仓库配置、安装前检查、版本列表 Remote、兼容性及取消重试边界 | [管理器包查询](manager-inspection-checks.json) |
| C8-BT | Git 连接预检、HTTPS/SSH 选择、完整日志与取消后进程树回收 | [Git 预检](git-connection-checks.json) |
| C8-BU | 安装服务进程的完整日志、字节尾部、静默期限、运行记录与回收 | [安装进程执行层](package-run-checks.json) |
| C8-BV | 安装前后兼容性与目标校验、配置恢复修复、Bundle 选择及遗留运行准入 | [安装服务事务](package-operations-checks.json) |

| C8-BW | 管理器安装、移除、等待与取消，进度流、构建批准及热启停 | [安装管理接口](manager-installation-checks.json) |

| C8-BX | 更新前校验、移除/安装/恢复、请求取消后旧版本恢复及热启失败 | [更新管理接口](manager-update-checks.json) |

| C8-BY | 真实 Git 提交与连通检查、503 保留旧包、403/缺少 Git 交由安装器及原提交恢复 | [Git 更新链](manager-git-update-checks.json) |

| C8-BZ | 无 Node 注册表元数据、真实 pnpm 版本选择、配置/认证路由与有界读取 | [Python 包元数据](python-package-query-checks.json) |

| C8-CA | Python 查询执行器接入真实管理器，空 PATH 下检查与列版本及请求取消 | [Python 包查询执行器](python-package-command-checks.json) |

| C8-CB | SRI 固定 tarball、解压前限额与路径/类型校验、真实 pnpm 归档和 Native 存储/启动 | [Python 包 tarball](python-package-tarball-checks.json) |

| C8-CC | 注册表身份/版本与原始归档绑定、Python ABI/兼容性双重检查及真实 TLS 安装 | [Python 注册表获取](python-package-acquire-checks.json) |

| C8-CD | 单宿主租约升级、准入间隙排他、其他宿主拒绝与原锁恢复、事务借用能力 | [运行中事务租约](profile-mutation-lease-checks.json) |

| C8-CE | Native 注册表来源/精确依赖、禁用包版本历史、离线回滚和真实管理器库存 | [Python 注册表代际](python-registry-generations-checks.json) |

| C8-CF | 独立 Python 子进程准备、父进程复验、提交前零写入与下载取消收尾 | [Python 包准备所有者](python-package-prepare-checks.json) |

| C8-CG | 宿主租约服务、提交前依赖图准备、共享导入状态与卸载后复制清理 | [动态 Python 依赖所有权](python-dependency-changes-checks.json) |

| C8-CH | 原生后端动态服务、真实 TLS 安装/热启用/调用/卸载、提交取消与服务收尾 | [运行中 Python 包后端](python-package-backend-checks.json) |

| C8-CI | 按次保留已验证安装文件、来源记录原样恢复、过期与篡改拒绝、离线启动 | [安装文件恢复快照](python-plugin-snapshot-checks.json) |

| C8-CJ | 更新作用域、真实目标移除/装载、旧依赖图恢复、失败恢复副本与原失败输入复验 | [原生更新与离线恢复](python-package-update-checks.json) |

| C8-CK | canonical CLI 恢复命令、禁用恢复、运行中拒绝与带空格路径的错误操作提示 | [恢复入口与用户操作](python-recovery-cli-checks.json) |

| C8-CL | 本地目录/ZIP/tgz 子进程准备、逐文件复验、真实热启用与中文 PAX 路径 | [本地原生包准备](python-package-local-checks.json) |

| C8-CM | 更新中后端卸载/宿主退出、完整排空、恢复副本与等待者取消独立性 | [更新生命周期](python-update-lifetime-checks.json) |

| C8-CN | 真实 Git 提交/标签/分支/子目录归档、限额、取消排空及单链接对象清理 | [Git 原生获取](python-package-git-checks.json) |

| C8-CO | Git 父进程复验/固定来源、真实管理器更新、离线来源恢复与深路径隔离 | [Git 原生管理器](python-git-backend-checks.json) |

| C8-CP | 停止状态的 canonical CLI 注册表/Git 安装升级、联网前拒绝与离线来源回滚 | [原生包 CLI](python-native-cli-checks.json) |

| C8-CQ | 直接远程 tarball、独立来源/字节身份、真实安装/取消及显式 CLI 离线回滚 | [远程 tarball 获取](python-package-url-checks.json) |

| C8-CR | 原样 Typert 延迟 schema 工厂/Remote 声明读取、严格输入与原版 Zod 逐值对照 | [新版 Typert 生成物](typert-artifact-checks.json) |

| C8-CS | 原版管理器生成物、真实 HTTP RPC/mux 安装事件、鉴权/输入拒绝及定义退役 | [管理器实际传输](manager-wire-checks.json) |

| C8-CT | 全部 40 份原样 Typert 生成物、声明字节附件程序、快照及 RPC 编码适配 | [Typert 字节结果](typert-binary-checks.json) |

| C8-CU | 226 个原版 Remote 命名方法、独立输入/投影缓存及保持参数和结果身份的直接调用 | [RemoteInfo 方法能力](remote-info-checks.json) |

| C8-CV | 新版工作区统一字节读取、真实 multipart/lookup、完整文件限额与 junction 目录边界 | [工作区文件预览](workspace-preview-checks.json) |

| C8-CW | 固定 ripgrep 解析、增量 UTF-8/记录、提前终止后排空及进程范围退出屏障 | [ripgrep 流读取](ripgrep-checks.json) |

| C8-CX | 工作区名称/路径搜索、独立限额、取消/超时与 Unicode 16 大小写和 UTF-16 排序 | [工作区搜索](workspace-search-checks.json) |

| C8-CY | 目标 watcher 订阅、当前元数据重读、取消/卸载等待及真实 mux 退订释放 | [工作区变更订阅](workspace-changes-checks.json) |

| C8-CZ | Office 普通输出限额、打开后元数据、变化拒绝、PDF/PNG 完整性与句柄回收 | [Office 输出读取](office-output-checks.json) |

| C8-DA | Office 元数据准入、前后台容量、同源/内容共享、LRU 与取消后的实际工作所有权 | [Office 共享队列](office-queue-checks.json) |

| C8-DB | Office 会话输出存储、串行容量、删除失败重试、限时回收及真实 junction 排除 | [Office 输出存储](office-outputs-checks.json) |

| C8-DC | Office 四类操作组合、授权版本重查、受控引擎错误/清理及真实二进制 Remote | [Office 提供方](office-provider-checks.json) |

| C8-DD | Office 工具输入族、各操作参数约束、格式诊断与附件/临时文件模型内容 | [Office 工具格式](office-formats-checks.json) |

| C8-DE | Office 技能准入、逐调用读取授权、模型图片能力与真实附件/会话临时输出链路 | [Office 工具接入](office-tools-checks.json) |

| C8-DF | 固定 Office 原生引擎的 Win7 普通导入阻碍（功能验收仍待兼容载体） | [引擎平台审计](office-engine-platform-checks.json) |

| C8-DG | Loader 按包名启动鉴权 Web 绑定、真实文件凭据及 mux 取消释放 | [候选 Web 绑定](web-bindings-checks.json) |

| C8-DH | 显式 v4 Session/投影根与 Loader Agent、原生执行器和工作目录文件读取 | [候选运行时绑定](runtime-bindings-checks.json) |

| C8-DI | Loader 子代理提供方、命名委派/发现、spawn/fork 完成及同会话冷恢复 | [候选子代理绑定](subagent-bindings-checks.json) |

| C8-DJ | 进程范围退出后的完成/句柄释放屏障及直接父进程完成边界 | [普通进程清理](ordinary-cleanup-checks.json) |

| C8-DK | Loader 原生 shell/作业绑定、原版 Job Remote 输出/终止与独立模型游标 | [候选 shell 作业绑定](shell-job-bindings-checks.json) |

| C8-DL | Loader 权限预设/沙箱策略/Auto 绑定、原版目录与命令请求及停用状态迁移 | [候选权限绑定](permission-bindings-checks.json) |

| C8-DM | ConfigEditor/表单绑定、原版设置 Remote 的脱敏/冲突/落盘/冷启动及文档打开取消 | [候选设置绑定](settings-bindings-checks.json) |

| C8-DN | 浏览器终端 Loader 绑定、真实 WinPTY 双向 Remote/xterm 及持久 PowerShell 状态/卸载 | [候选终端绑定](terminal-bindings-checks.json) |

| C8-DO | 固定 Source 空 Client Host 的可复现绑定及快捷键/文档预览页面配置注入 | [候选浏览器 Host 绑定](client-bindings-checks.json) |

| C8-DP | 声明式预设/工作目录工具/registry 探针绑定、原版目录/文档/切换 Remote 与工具可见性 | [候选预设绑定](preset-bindings-checks.json) |

| C8-DQ | 新安装清单下规范 run_profile 的管理器绑定、真实 HTTP Python 包安装/停启/移除 | [候选管理器绑定](manager-bindings-checks.json) |

| C8-DR | Workflow/显式 Python PTC Loader 绑定、真实 Guest→v4 子代理及进程工具回调 | [候选 Workflow/PTC 绑定](workflow-bindings-checks.json) |

| C8-DS | 跨源码目录的空浏览器 Host 绑定、独立交付文件引用提示词与 UI 原生动作生命周期拆分 | [交付引用绑定](file-reference-bindings-checks.json) |

| C8-DT | 稳定开发提示词、v4 历史段落保留、当前路径/Web URL 上下文及卸载 | [开发上下文绑定](harness-dev-context-checks.json) |

| C8-DU | 当前 Web 运行时/服务绑定、公告 URL 与代理前缀、认证页面及 Loader 就绪/SSH 行为 | [Web 运行时](web-runtime-checks.json) |

| C8-DV | Web 启动 TLS/公告 URL、参数拒绝与帮助、共享解析器及惰性配置消费者 | [Web 启动](web-startup-checks.json) |

| C8-DW | MCP 资源作用域/共享工具、继承覆盖、原始二进制值与模型投影及异步卸载 | [MCP 资源](mcp-resources-checks.json) |

| C8-DX | 实际 MCP stdio 资源/说明接线、SDK 资源投影分页、取消及重连代次 | [MCP 资源连接](mcp-resource-connection-checks.json) |

| C8-DY | MCP SDK 2 发现响应分发 schema、版本纠正/回退及 HTTP/网络错误决策 | [MCP 协商决策](mcp-negotiation-checks.json) |

| C8-DZ | MCP 原始探测窗口、消息守卫/回调移交、重试、关闭守卫与版本纠正状态机 | [MCP 探测](mcp-probe-checks.json) |

| C8-EA | MCP stdio 一次性探测进程/回收隔离、现代握手与结果解码及实际 Loader 接线 | [MCP stdio 协商](mcp-stdio-negotiation-checks.json) |

| C8-EB | MCP HTTP 原连接探测、JSON/SSE、业务请求头/会话 ID 及取消清理与实际接线 | [MCP HTTP 协商](mcp-http-negotiation-checks.json) |

| C8-EC | MCP 稳定状态单元/观察者、UTF-16 脱敏与原因链及不取消后台工作的期限 | [MCP 状态基础](mcp-status-primitives-checks.json) |

| C8-ED | MCP 代次任务所有权、共享有界清理/独立关闭确认、原始传输启动与 Windows 短期限复核 | [MCP 代次](mcp-generation-checks.json) |

| C8-EE | MCP 凭据模板语法、逐次连接解析/引用复用、动态提供者与实例历次值脱敏（Web 配置组合回归缺口保留） | [MCP 凭据模板](mcp-template-binding-checks.json) |

| C8-EF | MCP 一次性服务器探测、客户端代次接口/分页、探测专用握手身份与有界取消清理 | [MCP 服务器探测](mcp-server-probe-checks.json) |

| C8-EG | MCP 生产监督器：代次/状态、凭据刷新、期限与发布资格、关闭失败替换阻断及实际 Fiber 重载 | [MCP 连接监督器](mcp-supervision-checks.json) |

| C8-EH | MCP 管理条目：易变配置、写入校验顺序/跨传输字段、模板与客户端配置隔离转换 | [MCP 管理条目](mcp-manager-entries-checks.json) |

| C8-EI | MCP 管理服务：实例协调/注册寿命、重启、观察/Remote 探测及清理失败保留与替换阻断 | [MCP 管理服务](mcp-manager-checks.json) |

| C8-EJ | Canonical Web 组合：新启动值、安装依赖/原版 Remote 元数据、MCP 与工作目录服务及零未激活条目 | [Web 组合](web-composition-checks.json) |

| C8-EK | MCP 现代响应分派：避免旧 schema 遮蔽、默认续请求/轮数限制、手动返回及无处理器诊断 | [MCP 现代响应](mcp-dispatch-checks.json) |

| C8-EL | 图片卸载恢复：Agent/摘要失败接缝、持久化图片选择与失败信息、重新派生计价及 V4 检查点 | [图片恢复](image-offload-checks.json) |

| C8-EM | 工作区改动输入：numstat/重命名、路径与显示排序、有限字节捕获/内容去重及取消所有权 | [改动输入](change-inputs-checks.json) |

| C8-EN | 工作区 Git 快照：私有 index/对象库、改动/重命名/忽略、blob 与子进程期限/取消清理 | [Git 快照](change-git-checks.json) |

| C8-EO | 工作区文本差异：原版行匹配/三行 hunk、计数与超时整段替换及 1109 组对照 | [文本差异](change-compare-checks.json) |

| C8-EP | 工作区每轮记录器：快照与首个编辑捕获、事件覆盖、延迟差异、仓库状态不变及释放清理 | [每轮记录器](change-recorder-checks.json) |

| C8-EQ | 工作区变更服务：真实 Agent/文件策略调用链、会话寿命、Git 降级、Web 装配及可逆挂载 | [变更服务](workspace-recorder-service-checks.json) |

| C8-ER | 变更浏览器接口：摘要/差异/打开、原生应用查询、文件映射验证、认证 TCP 与取消释放 | [变更接口](change-routes-checks.json) |

| C8-ES | 变更接口真实 Peer 载体：非 owner 五路由拒绝、认证 TCP、默认文本响应头及生命周期回归 | [Peer 接口](change-route-peers-checks.json) |

| C8-ET | 插件管理工具：八种操作、逐次审批、分页/提示、注册回收与规范基础行及管理服务 | [管理工具](plugin-manager-tools-checks.json) |

| C8-EU | DeepSeek 模型缓存：凭证隔离、首次共享加载、自动刷新、迟到结果隔离与卸载等待 | [模型缓存](listing-cache-checks.json) |

| C8-EV | 模型列表解码与真实 HTTP：能力/版本/Unicode 标签、凭证来源、重定向拒绝、完整正文截止及压缩响应 | [列表解码与 HTTP](model-listing-checks.json) |

| C8-EW | 分离后的 Messages 配置与目录决策：新内置模型、能力分层、版本拒绝、覆盖校验和重试配置 | [配置与目录](listed-catalog-checks.json) |

| C8-EX | API Key / 账户路由配置与共享凭证：原版 Schema、权威来源、JS 归一化、目录跟随条件和账户覆盖 | [路由与凭证](deepseek-credentials-checks.json) |

| C8-EY | Messages 请求与事件状态机：原生思考签名、工具变更、历史系统更新、图片引用及真实块组装对照 | [Messages 核心](messages-wire-checks.json) |

| C8-EZ | Messages SSE 字节边界、错误分类与上游清理；修复 headless 执行器组合及 v4 标题生产者交接 | [帧与集成消费链](messages-framing-checks.json) |

| C8-FA | V4.1 图片网格与目标宽高、逐次计价、持久化 offload 准入及 Files 位置 | [图片请求规则](messages-images-checks.json) |

| C8-FB | 实际附件目标宽高编码与缓存：短边取整、独立 Pillow 身份、并发复用和原图保留 | [图片目标编码](image-targets-checks.json) |

| C8-FC | 请求级 Files 截止时间、过期映射单次恢复、Unicode 边界与实际图片位置诊断 | [请求 Files 策略](request-files-checks.json) |

| C8-FD | 扩展字段序列化与 HTTP 接受事务；当前 registry 按字段省略失败、一次警告及共享提交 | [请求扩展事务](request-extensions-checks.json) |

| C8-FE | Messages Files 真实 HTTP、请求头认证、日期元数据、multipart 与取消回收 | [Files HTTP](files-http-checks.json) |

| C8-FF | 上传索引批量精确失效、磁盘字节、并发胜出与 Windows 原子替换重试 | [上传索引](upload-index-checks.json) |

| C8-FG | 当前 Files 共享上传、独立取消、跨页配额回收及精确失效消费链 | [文件复用服务](file-store-checks.json) |

| C8-FH | 空闲超时直接竞争挂起 demand，并观察延迟失败 | [watchdog 竞争](watchdog-race-checks.json) |

| C8-FI | Messages 适配器真实 HTTP 全链路：Files/索引、扩展、SSE、超时与关闭 | [适配器消费链](messages-adapter-checks.json) |

| C8-FJ | 独立 API-key provider、当前 Host 接线、活凭据与目录注册生命周期 | [API-key provider](api-key-provider-checks.json) |

| C8-FK | Account provider 与基础 profile 切换；真实 headless Messages 重试链路 | [账户 provider 与组合](account-provider-checks.json) |

| C8-FL | 账户客户端身份、Cookie 合并、脱敏资料与精确十进制钱包投影 | [账户资料投影](account-projection-checks.json) |

| C8-FM | 账户受限地址／请求头、真实 HTTP 响应约束、取消收尾与安全诊断 | [账户请求协议](account-protocol-checks.json) |

| C8-FN | 通知数据与登录响应校验、旧 token 退出重试及取消清理 | [通知与退出](account-notification-checks.json) |

| C8-FO | 异步授权服务、提交准入后的取消语义与终态通知隔离 | [授权服务](authorization-checks.json) |

| C8-FP | 账户凭据与查询生命周期、身份缓存、状态流和任务取消接线 | [账户状态组件](account-state-checks.json) |

| C8-FQ | 账户浏览器登录、PKCE 回调与失败页面、基础 profile 和生成 Remote 协议接线 | [登录与启动](account-login-checks.json) |

| C8-FR | Search/Fetch 按序凭据与真实 HTTP、401 精确失效、共享传输与取消清理 | [Web API 传输](web-api-transport-checks.json) |

| C8-FS | 直接 Search/Fetch provider、结果映射、调用快照与含边界限速 | [Web API 组件](web-api-provider-checks.json) |

| C8-FT | 按当前模型路由与计费选凭据、Web 列表 Remote、动态选择和基础组合 | [Web API 组合](web-api-selection-checks.json) |

| C8-FU | 匿名抓取 URL/MIME/字符集策略、固定 Node 解码映射与流式错误恢复 | [抓取策略](fetch-policy-checks.json) |

| C8-FV | 有界匿名 HTTP provider、重定向/截断/取消、代理与规范 Web 注册 | [匿名抓取](http-fetch-checks.json) |

| C8-FW | 共享 HTTP 压缩编码、HTTPS 协商、x86/x64 解码与打包依赖 | [压缩传输](content-coding-checks.json) |

后续继续完整应用组合；最终资格使用 C9 冻结候选的完整门禁。

| C8-FX | Messages search account/readiness/live Config and per-carrier HTTPS coding negotiation | [Messages search](messages-search-checks.json) |

| C8-FY | Managed credential precedence, masked previews and initial-load notifications | [Credential references](local-credential-reference-checks.json) |

| C8-FZ | Staged credential document admission, alias budget and safe diagnostics | [Credential document](credential-document-checks.json) |

| C8-GA | Credential collection/merge admission and original-text flat upgrade | [Credential collections](credential-collection-checks.json) |

| C8-GB | Round-trip credential edits, annotations and x86/x64 packaging dependencies | [Credential editor](credential-editor-checks.json) |

| C8-GC | Current credential storage, durable queue, live reload and canonical Connection activation | [Credential storage](credential-storage-checks.json) |

| C8-GD | Account settings/onboarding and notification public Host configuration | [Account surfaces](account-surfaces-checks.json) |

| C8-GE | Staged OTel emitted records and session channel option admission | [OTel records](otel-records-checks.json) |

| C8-GF | Staged OTLP JSON request serialization and exact byte measurement | [OTel wire](otel-wire-checks.json) |

| C8-GG | Staged byte/count Session-log queue, exporter settlement and shutdown ownership | [OTel Session channel](otel-session-channel-checks.json) |

| C8-GH | Staged actual Session HTTP/TLS exporter, retry and explicit identity isolation | [OTel HTTP](otel-http-checks.json) |

| C8-GI | Staged cancellable ordinary-event HTTP transport and decoded response bounds | [OTel event HTTP](otel-event-http-checks.json) |

| C8-GJ | Staged ordinary-event count batching, timeout progression and shutdown signals | [OTel event channel](otel-event-channel-checks.json) |

| C8-GK | Registered Cordis otel service and actual independent HTTP channel composition | [OTel service](otel-service-checks.json) |

| C8-GL | Active feedback-only backend over ctx.otel, source-envelope redaction and canonical provider composition | [OTel backend](otel-backend-checks.json) |

| C8-GM | Registered product event policy, explicit application identity and cancellable fiber drain | [Product telemetry](product-telemetry-checks.json) |

| C8-GN | Staged analytics environment parsing, fixed query argv and field failure isolation | [Analytics environment](analytics-environment-checks.json) |

| C8-GO | Actual analytics query process, byte limits, timeout/abort and close ownership | [Analytics query](analytics-query-checks.json) |

| C8-GP | Default Windows OS metadata and actual bounded collector integration | [Analytics OS](analytics-os-checks.json) |

| C8-GQ | Product analytics Remote Host, live policy, cached environment, identity and actual ordinary HTTP consumer | [Product analytics](product-analytics-checks.json) |

| C1 follow-up | HMR module import syntax reuse, reload invalidation and weak ownership | [HMR import cache](hmr-import-cache-checks.json) |

| C8-GR | Desktop product composition, profile/HMR ownership, release stamp and current Peer HTTP/policy stream | [Desktop analytics](desktop-analytics-checks.json) |

| C8-GS | Primary runtime manifest normalization, distribution identity and entry paths | [Workspace manifest](workspace-manifest-checks.json) |

| C8-GT | Primary runtime filesystem validation, transactional install/recovery and linked-directory protection | [Workspace files](workspace-files-checks.json) |

| C8-GU | Canonical workspace dependencies tool, shared preparation/retry and disposal ownership | [Workspace tool](workspace-tool-checks.json) |

| C8-GV | Bundled Office skills, environment guidance, lazy reads/failure recovery and owned disposal | [Office skills](office-skills-checks.json) |

| C8-GW | Application Office/runtime composition, expression carriers and standalone SDK executor/directory closure | [Office composition](office-composition-checks.json) |

| C8-GX | Staged current read-only Cordis inspection tools and exact generated descriptors | [Cordis inspect tools](cordis-inspect-tools-checks.json) |

| C1/C8-GY | Private upstream Config projector carrier, exact graph semantics and shipped x64/x86 engine checks | [Config projection](config-projection-checks.json) |

| C1/C8-GZ | Live Python Schema identities, sequential lazy-builder RPC and cancellation ownership | [Config graph bridge](config-graph-checks.json) |

| C1/C8-HA | Live Loader Config directory/details and actual package-directory consumer closure | [Config inspection](inspect-config-checks.json) |

| C8-HB | Current generated API catalog/type closure and shared Host inspect provider ownership | [Inspect providers](inspect-providers-checks.json) |

| C8-HC | Current inspect deadlines, first valid page/diagnostic and cancellation/disposal ownership | [Inspect registry](inspect-registry-checks.json) |

| C8-HD | Current Dynamic Host runner Config, registry ownership and activation/panel notices | [Host runner](host-runner-checks.json) |

| C8-HE | Explicit Native Creative seven tools beside current inspect/Host ownership | [Native Creative composition](cordis-creative-checks.json) |

| C9-A | Actual official Web candidate boot; Node PTC and client resource ownership failures retained | [Application candidate attempt](application-candidate-checks.json) |

| C9-B | Current client graph/stat identities, canonical package ownership and restart metadata | [Client registry graph](client-registry-checks.json) |

| C9-C | Independent lazy immutable script/map bodies, prior batches and async Web/Desktop consumers | [Client resource bodies](client-resources-checks.json) |

| C9-D | Current on-demand async browser chunks, strict revisions and cache lifetime | [Client chunks](client-chunks-checks.json) |

| C9-E | Export-owned package images, exact cache headers and cancellable streams over all carriers | [Client package assets](client-assets-checks.json) |

| C9-F | Official current Web serves 75 client entries; Session preset record boundary fixed, later activation failures retained | [Current Web resources and Session composition](application-current-resources-checks.json) |

| C9-G | Official preset skills path expressions resolve through owning installation package | [Preset expressions](preset-expression-checks.json) |

| C9-T | Current Schedule tools close the Standard Session activation gap; PTC and Creative providers remain pending | [Schedule tools](schedule-tools-checks.json) |

| C9-U | Optional read-only market tool unblocks Creative Session creation; PTC runtime remains pending | [Market tools](market-tools-checks.json) |

| C9-V | Explicit Win7 Python PTC overlay creates all four preset Sessions; actual run_code calls Schedule through the process wire | [Runtime overlay](runtime-overlay-checks.json) |

| C9-W | SQLite atomic batch/version migration and backend quarantine close the direct Domain consumer | [SQLite batch](sqlite-batch-checks.json) |

| C9-X | Per-record JSON atomic batch/restore, accepted write draining and empty-tree authority | [Per-record batch](per-record-batch-checks.json) |

| C9-Y | Live default-model Config/save FIFO and actual timed/manual Schedule delivery through Agent and Session persistence | [Default model and delivery](default-model-delivery-checks.json) |

| C9-Z | Current live theme/locale companions close the index HTTP400; preview and Session-list browser failures retained | [Appearance](appearance-checks.json) |

| C9-AA | Live welcome acknowledgement and resource-aware Session controller candidate binding; Workspace browser gap retained | [General Settings](general-settings-checks.json) |

| C9-AB | Durable Workspace pin/default fields and queued pin/archive activity lifecycle | [Workspace pins](workspace-pins-checks.json) |

| C9-AC | First-use Workspace identity and current create/delete journal rollback with cold recovery | [Workspace default](workspace-default-checks.json) |

| C9-AD | Current Workspace commands and resource-filtered committed feed with reconnect and revocation replacement | [Workspace Remote](workspace-remote-checks.json) |

| C9-AE | First-use Documents policy and candidate Workspace binding remove the browser baseline crash; Schedule catalog failure retained | [Workspace directory](workspace-directory-checks.json) |

| C9-AF | Canonical Typert artifact ownership and current Plugin Inventory close the original Schedule catalog/details browser flow | [Typert ownership](typert-owner-checks.json) |

| C9-AG | Original Schedule pause/resume/edit/reload/run journey reaches actual persisted delivery; old-browser menu geometry defect retained | [Schedule browser](schedule-browser-checks.json) |

| C9-AH | Host CSS anchor compatibility fixes original menu placement/reopen/mobile resize without changing Source bundles; dynamic/color-mix ownership and cleanup checked | [Browser anchors](browser-anchor-checks.json) |

| C9-AI | Current Workspace missing-directory candidate ownership, attach admission, per-id reindex/replacement and persisted pruning | [Workspace membership](workspace-membership-checks.json) |

| C9-AJ | Pinned market index validation/install targets and multilingual MiniSearch in shipped x64/x86 Win7 worker; 110 paired observations | [Market index](market-index-checks.json) |

| C9-AK | Market configured-source URL rules and shared document cache: TTL/pins, monotonic identity, removal, cancellation and disposal | [Market cache](market-cache-checks.json) |

| C9-AL | Strict UTF-8/BOM + JS JSON acceptance and abort-safe parser process ownership; exact V8/QuickJS syntax diagnostics explicitly pending | [Market body](market-body-checks.json) |

| C9-AM | Actual bounded market HTTP + isolated parsing: no redirect, decoded size, deadline/lifetime abort, EOF and response cleanup | [Market HTTP](market-http-checks.json) |

| C9-AN | Market listing/search/entry composition, live installation/compatibility/Git updates, Settings/events and SemVer whitespace fix | [Market listing](market-listing-checks.json) |

| C9-AO | Market detail package-first selection, shared cache/failures, document-id lifetime and bounded adjacent images over controlled files | [Market detail](market-detail-checks.json) |

| C9-AP | Unchanged repository/manifest helpers and pinned hosted-git-info on Win7 worker; 822 paired identities + x86/x64 projection | [Market repository](market-repository-checks.json) |

| C9-AQ | Repository API reads and clone fallback: encoded GitHub/GitLab URLs, ambiguous misses, public/private checks and README order | [Market files](market-files-checks.json) |

| C9-AR | Actual Git partial clones, fixed/default commits, exact binary bounds, process-tree cancellation, cross-cache locks and deferred LRU eviction | [Market Git](market-git-checks.json) |

| C9-AS | Market detail Remote composes actual readers/cache, preserves original fallback/errors and owns reversible authenticated image route | [Market Remote](market-remote-checks.json) |

| C9-AT | Unchanged optional Discover bundle: strict Market RPCs, saved index, search, detail/image, reload and mobile; measured synchronous metadata cost retained | [Market browser](market-browser-checks.json) |

| C9-AU | Per-read resource resolution facts bound repeated locale/manifest I/O while edits and failure recovery stay fresh; original Discover journey remains passing | [Metadata reads](metadata-read-checks.json) |

| C9-AV | Separate Host process and fresh browser restore welcome confirmation and saved optional Market source, refetch listing and repeat search/detail/image/reload/mobile | [Market cold process](market-cold-checks.json) |

| C9-AW | One owned Win7 worker reuses pinned lazy search instances per live document; concurrent/cancel/refresh/retire/crash recovery and original browser journey checked | [Market search reuse](market-search-checks.json) |

| C9-AX | Event-driven owned stream handoff removes fixed per-chunk delay; actual default 128 MiB exact/overflow HTTP and x86/x64 parser boundary matches Source | [Market boundary](market-boundary-checks.json) |

| C9-AY | Exact pinned V8 JSON syntax prose/UTF-16 locations/context on Win7 worker; 7,849 exact pairs, full x86/x64 corpus and original body/Market consumers | [Market JSON diagnostics](market-json-checks.json) |

| C9-AZ | Holder-owned Workflow result survives independent observer cancellation/timeout and drains children; actual Guest/end-event checked, old production preset collision retained for promotion | [Workflow result](workflow-result-checks.json) |

| C9-BA | Separate Host/browser restores saved Schedule and inactive v4 Session; original mobile/desktop run adds a second receipt while preserving all 22 prior events | [Schedule/Session cold process](schedule-cold-checks.json) |

| C9-BB | SDK memoized handshake/close keep owner alive after independent observer cancellation/timeout; actual wire cleanup/retry, cold resume and forced reaping checked | [SDK operation ownership](sdk-ownership-checks.json) |

| C9-BC | Returned plain/TLS upgrade callbacks transfer socket ownership; later frames, half-open peer, real RST and unload checked against Original | [Upgrade ownership](upgrade-owner-checks.json) |

| C9-BD | MCP default connection cache honours TTL/refresh/bypass, isolates returned values and rejects stale in-flight writes after notifications; actual HTTP and consumers checked | [MCP response cache](mcp-cache-checks.json) |

| C9-BE | Pinned SDK output-schema provider runs in owned Win7 x86/x64 workers; pre-RPC errors, structured results, cached definitions and close/cancel ownership checked | [MCP tool output validation](mcp-output-checks.json) |

| C9-BF | MCP multi-round retries account for the first wire leg, shrink total budget and preserve per-leg/retry option ownership; actual HTTP pacing checked | [MCP flow budget](mcp-flow-budget-checks.json) |

| C9-BG | SDK 2 wire timers/progress, raw abort reasons, serving ProtocolError and per-request HTTP cancellation match Original; disconnect and overlapping siblings checked | [MCP wire requests](mcp-request-checks.json) |

| C9-BH | Pure x-mcp-header declaration reachability, primitive argument paths and exact field-value encoding match 275 Original observations | [MCP parameter header rules](mcp-param-headers-checks.json) |

| C9-BI | Modern HTTP filters invalid declarations, preserves reserved headers and recovers one header mismatch with refreshed schema; actual wire and consumers checked | [MCP header transport](mcp-header-transport-checks.json) |

| C9-BJ | Compaction recovery uses selected-span/whole-surface stability consistently and checks cancellation before retry; actual transactions paired, separate legacy lifecycle/preset integration failures retained | [Compaction recovery](compaction-recovery-checks.json) |

| C9-BK | Shipped presets resolve current Workflow and avoid duplicate controls; Minimal keeps two tools, four presets coexist and real Workflow/compaction/PTC records restore; legacy Loader fixture uses explicit owner joins | [Preset integration](preset-integration-checks.json) |

| C9-BL | Unchanged Office WASM compiles/initializes in Chromium 108 and actually converts DOCX→PDF/TXT and renders PDF→PNG; controlled font and production-carrier limits remain explicit | [Office WASM feasibility](office-wasm-carrier-checks.json) |

| C9-BM | Python 3.8 stdlib carrier runs actual pinned WASM conversion on x64/x86 Python, preserves bytes and owns worker/browser cancellation and cleanup; 17 actual browser boundaries checked | [Office Python carrier](office-python-carrier-checks.json) |

| C9-BN | Pinned Office SDK scan/match/export/raster bodies run through the browser volume; 16 actual Original/WASM pairs, exact PNGs and reproducible build checked | [Office SDK browser adapter](office-sdk-browser-checks.json) |

| C9-BO | Physical font reads enforce snapshot identity and bounds through opened Windows handles; post-operation validation, 16 actual SDK pairs, 71 checks and x86 identity/conversion verified | [Office physical font volume](office-font-volume-checks.json) |

| C9-BP | Office 独占文件事务、限额稳定读取、取消排空；42 项定向检查、12 组实际 SDK 对照与 x86 文件操作 | [文件事务](office-file-transaction-checks.json) |

| C9-BQ | 默认字体实体目录由原版 Office 扫描器筛选与排序；45 项定向、7 组根目录、5+5 组扫描及 16 组实际 SDK 回归 | [默认字体发现](office-font-discovery-checks.json) |

| C9-BR | 原版 SDK 格式/选项/A1/图片准入运行在 Win7 QuickJS；758+758 组实际对照、50 项定向与 9 组系统根目录 | [Office 请求准入](office-contracts-checks.json) |

| C9-BS | Office 转换器拥有者、排队/超时/取消、共享字体世代与独占输出；70 项定向、6+6 组原版公开转换器及 16 组 SDK Worker 对照 | [Office 浏览器引擎](office-browser-engine-checks.json) |

| C9-BT | 当前 office-kit 组合默认 Cordis 引擎、懒加载/重试/卸载及运行时身份检查；79 项定向含实际应用队列转换 | [Office 默认提供方](office-default-provider-checks.json) |

| C9-BU | Office x64/x86 离线输入、完整许可证与精确打包；98 项定向、6 项最终打包/超时回收、双架构隔离默认服务及独立采集 | [Office 运行时打包](office-runtime-packaging-checks.json) |

| C9-BV | 原版磁盘字体元数据缓存、实体路径互通和原子写入；103 项定向、13 项最终消费者及 8+8 组真实 Worker 对照 | [Office 磁盘缓存](office-metadata-cache-checks.json) |

| C9-BW | 实际 Calc/Impress 重算、格式转换、PDF/图片和错误矩阵；13+13 组公开 SDK 对照及 3 项比较器拒绝回归 | [Office 格式矩阵](office-format-matrix-checks.json) |

| C9-BX | 新版完整前端资源收集、受核验暂存成员与过期客户端回收；17 项定向、3 项最终 CLI/模式检查及实际 371 份 Source 核验 | [完整前端导入](frontend-import-checks.json) |

| C9-BY | 统一门禁冻结 Office 离线输入并核验实际解压资源/来源；16 项定向、双架构输入逐资源检查；旧完整回执探针失败单独保留待修 | [Office 发行输入门禁](office-release-gate-checks.json) |

| C9-BZ | 既有 JavaScript/LLM 配置门禁预加载闭包；66/60 项消费者、32/26 组原固定 Source 对照；SDK 取消失败留待新版入口协调 | [门禁导入闭包](gate-import-closure-checks.json) |

| C9-CA | 新旧目标切换时保留旧任务原状态且禁止提供当前资格；36 项迁移工作流定向检查 | [未完历史记录](migration-open-history-checks.json) |

| C9-CB | 前端原始构建记录随资源备份、核验和原字节导入，冷恢复不冒用旧归档；18 项导入与恢复定向 | [原始构建记录导入](frontend-build-record-checks.json) |

| C9-CC | 生产目标、原版元数据/371 份前端、40 份 Typert 声明和当前宿主绑定协调切换；真实 Web 四预设、Python PTC、关停与七配置入口定向通过，完整资格仍待后续 | [协调安装切换](coordinated-installation-checks.json) |

| C9-CD | Node 24.9/pnpm 11.28.5 原版 Source 准备、当前 Typert/Host/Client 构建顺序与五项静态库；实际构建及 6 项冷恢复/拒绝检查通过，371 份前端身份保持 | [Source 准备](source-preparation-checks.json) |

| C9-CE | 默认 SDK/ACP/Headless 实际进程入口、EOF/冷恢复及 Creative 七工具；ACP 准入等待启动提交、当前子代理退场接口和显式 Native 安装依赖，定向消费者通过 | [当前入口](current-entrypoints-checks.json) |

| C9-CI | 实际解压 SDK 三场景、Office 和现代/108 原版浏览器五步定向通过；修复导出 Client 的当前 codec/目标、Web 兼容插件挂载及隔离 ACL runner，清理约 801 MiB 中间资产；干净完整资格和应用冷恢复仍待后续 | [解压与浏览器](current-extracted-browser-checks.json) |

| C9-CY | 干净检出发现运行时字节差异，冻结阶段拒绝且未执行测试；保留 YAML 与两份历史元数据原字节、补齐根 Node 依赖冻结，32 项定向通过；新鲜统一资格待执行 | [检出与冻结](checkout-freeze-checks.json) |

| C9-CZ | 使用仓库内独立原版检出，保留路径边界检查；复用 pnpm 工作区时验证当前干净 pin 并冻结完整原工作区，27 项定向通过，原版 Git 指针元数据已原样恢复 | [复用 Source 冻结](prepared-source-freeze-checks.json) |

2026-11-19：C9-GM [嵌套夹具清理](current-paired-nested-fixture-checks.json)将可选 `files/` 合成根统一声明到 406 个新鲜自有探针输出，覆盖 `files/native` 和共享 helper；不依赖不完整的字符串枚举。凭据编辑 184 组实际配对及 67 项定向检查通过，run28 原始观察未改写、30,678 字节夹具已清理；三次定向调用的 9 个自有目录、3,167,199 字节和 43 个链接已退役。误选文件与中断的过宽测试范围单独保留，不作验收；run28 仍为失败，后续全门禁待执行。

2026-11-19：C9-GN [PTC 工作区所有权](current-ptc-workspace-checks.json)将 confinement/control/protocol/runtime 四个驱动从调用方共享 `tmp/workspace` 改为各自 `output/files/workspace`。57 项和 74 项定向检查及四个实际 Source/Python 配对通过，覆盖真实进程、沙箱拒绝、协议、取消和卸载；自有夹具与失败启动空缓存已清理。原 run29 在程序启动前失败的记录保持；剩余准备和单次完整门禁继续。

2026-11-19：C9-GO [终端诊断字段观察](current-shell-message-checks.json)修正探针将原版 `Error.message` 与 Python 展示用 `str(error)` 混比的问题，读取真实 `message` 并独立比较 code/子类，生产错误不变。19 组实际配对和 16 项终端/进程错误消费者检查通过；失败原始观察保留，已结束自有夹具和编译缓存退役。

2026-11-19：C9-GQ [实际生成 codec 形态](current-typert-codec-shapes-checks.json)让探针分别消费原版 factory codec 与已解析 `schema`，未知形态仍拒绝；不改原版制品或 Native 解析器、不跳过 reader。42/42 个实际制品、876 个 codec/15,768 次验证与 Native 一致，30 项解析/加载/注册消费者检查通过；原失败诊断保留，已结束夹具与空缓存退役。

2026-11-19：C9-GP [Desktop 离线 Office 清单校验](current-desktop-office-inventory-checks.json)将另行打包的 95 份已批准 Office 运行时文件与源码 provider 区分校验，逐字节核对固定清单、来源、架构及无未声明文件；源码比较仍拒绝旧 provider。58 项打包/来源/Office 定向检查通过，自有夹具和失败空缓存已退役；原实际失败与输入保持。实际 Desktop 重建、预检及浏览器仍待下一步，不据单元检查认证安装器。

2026-11-19：C9-GR [探针资产及时退役](current-probe-asset-retention-checks.json)补齐字体、文档和 TLS 合成输入的显式清理声明；16 个实际 Office SDK 配对均一致，最后消费者结束后删除 30,819 字节输入副本，保留完整实际文档、图像与比较。52 项定向检查通过、1 项需显式 Source 输入的检查跳过；旧准备运行的 20 组冗余输入共 8,717,350 字节及本次三个临时目录已退役。实际 Desktop 与新鲜单次完整门禁继续，不合并历史局部结果为发行资格。
