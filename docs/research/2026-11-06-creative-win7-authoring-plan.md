# 创造模式 Win7 插件开发指引调整计划

> 历史方案：用户随后明确要求仅做原版迁移的必要适配。独立技能/开发扩展接入决定已由[对齐记录](2026-11-06-creative-win7-authoring-alignment.md)取代；下文保留当时计划及证据，不是当前接入说明。

日期：2026-11-06。源码基线：`2477b0a768c877d961c43a76250b77fe07a67476`。
固定迁移目标：`a4c74a91e06b00fe0b0937bde982170c526cc842`。
状态：B1–B3 已实施并完成开发机定向验证；B4 已取得九次基线观察及两次反馈后的定向复测，尚不能据此认证普遍开发成功率或动态 Client 审批全流程。实际结果见[实施记录](2026-11-06-creative-win7-authoring-implementation.md)。Portable 发行验收与 Win7 目标机观察另行保留，不能由本轮结果代签。

依据：[11 月 2 日评估及其第 8 节修订](2026-11-02-creative-win7-plugin-authoring-assessment.md)。用户认可复核结论，并要求对齐原版创造模式指引，面向本机 Win7/Python 版本，不沿用原版 TS Host 工具链。

## 1. 目标与设计决定

沿用固定原版技能的开发流程、能力导航和诊断结构，提供本机可执行的实现与交付知识。验收终点是智能体依据实际可见技能创建、运行、清理并按需持久交付插件，而不只是提示包含 Python 字样。

- 动态 Host：Python 3.8.10 源码，定义 callable `plugin`；动态 Context 使用 guard 开放的 API。
- 原生源码 Host：公共 `dsh.plugin_api`、`dsh.python` 描述和 canonical Loader；与动态 callable 示例分别讲解。
- 动态 Client：保持 plain JavaScript 函数体；React 使用 `React.createElement`，不输入 TS/JSX/import。复用原版 Client、Slots 和 Connection/Typert 协议。
- 持久交付：沿用本机 export、受支持的 Client build、pack、add、upgrade、versions、rollback、remove。普通目标机操作无需安装 Node/pnpm/pip。
- 完整 TS/TSX 前端工程属于开发机预构建路径；本机导出项目 build 只封装受支持的 plain JS，不能描述为通用编译器。
- 运行时能力以实际 Inspect 和服务提供端为准；缺失能力明确说明，不用上游示例推定可用。

### 接入策略

采用独立命名的 `cordis-plugin-development-win7` 技能，作为显式 Win7 开发扩展的知识入口。CLI Creative 和 Web 用户开发 preset 共用同一份技能正文与参考资料。

扩展通过现有 Cordis 配置、技能 provider 和注册层接入，不增加启动参数或第二套技能发现器。CLI 使用现有 `--profile creative --patch <path>` 机制；Web 采用用户目录中的开发 preset，在保留原 cordis 组合的基础上挂载扩展。补丁和 preset 的实际可执行配置在实施阶段随代码交付，不能把本计划中的名字当作已安装能力。

扩展只注册自己的技能 provider、任务指引和显式导出工具，依赖通过 inject 声明，注册与清理通过 Context/effect 管理。技能资源位置从本机安装模块位置解析，不写死仓库绝对路径，不在目标机求值 Node URL API。

保留上游自带技能和默认发现合并规则；扩展明确引导本机任务先加载 Win7 技能。原版技能可用于 Client 和架构参考，其中 JS Host 示例不直接执行。旧本地同名 Python 技能也须修正，不能保留已知错误作为另一个入口。

此次不把技能或 export 隐式塞入默认七工具组合。默认提示、工具和 Inspect 的既有配对范围保留；扩展的提示、技能目录和工具增量单独记录、验证。若发现必须改变默认语言适配才能正确路由，须单列适配差异并更新相应观察，不能把变化冒充原合同未变。

## 2. 原版指引到 Win7 的覆盖矩阵

参照：[固定工作区原版技能](../../packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/SKILL.md)。这是结构与语义来源，不以当前远端最新版替换迁移目标。

| 原版主题 | 本机指引与实施要求 |
| --- | --- |
| Standard workflow / Tool usage | 保留 list → 最小 query → 新建或 inspect_self → define → run → 观察 → stop/undefine；使用返回的确切 pluginId/packageId，不把 define 当激活。 |
| Choose a platform | 先选 Host/Client/联合，再选 Host composition/Agent preset 所有权；两条轴分别解释，不把 Host 等同于共享全局。 |
| Provider navigation | 保留渐进查询；目录不等于已挂载服务；Client 查询需实际页面响应。 |
| Execution environment | Python Host、plain JS Client 分别列明语言、内置对象和执行环境；Python 进程内代码不是恶意代码安全沙箱。 |
| Access Services | 可选服务用 `ctx.get` 并处理 None；硬依赖用 callable 的 `plugin.inject`；按实际提供端解释 await、返回值和 UNDEFINED。 |
| Manage side effects / Timers | 使用真实开放的 effect、事件和 timer 能力；注入 timer 后使用混入方法；清理、取消和异步任务归属可观察。 |
| Listen to Events | 给出 emit、waterfall、serial、parallel 的本机监听示例；middleware 正确传递 next，不把所有事件当同步调用。 |
| Register Client UI | 保留 Slots、设置页、会话 props、Run 面板、工具卡和 overlays 的用途区分；仅覆盖当前 provider 实际支持路径。 |
| Themes and styles | 使用查询到的 token 与可逆覆盖，避免为局部需求替换全局界面。 |
| Call Host from Client | Python `harness.handle` 与 JS `host.call` 成对示例，说明 JSON 边界、所属运行版本和撤销后的行为。 |
| Dynamic model Tool | `harness.defineTool` 后用 `ctx.tools.register` 或 `harness.registerTool`；完整参数 DSL、execute、output.schema/render；说明与原生工具定义的区别。 |
| Internal live data | 不把实时 Host 对象直接放进长期状态或 RPC 返回；只返回实际合同允许的 JSON 数据。 |
| Versions / Approval / Repair | 保留不可变 Package、run/update/rollback 区别、waiting/starting/awaiting-approval 处理、错误诊断与原版异步状态续接语义。 |
| Modify @pluginId / Failure checks | 先读基版本，仅修改目标代码半部；按语言、依赖、审批、作用域、浏览器、render 分层定位。 |
| 本机增加：Win7 交付 | 补 Python 3.8、UTF-8、路径、powershell.exe/cmd、精确依赖闭包、发行清单、安装重启与升级回退。 |

服务绑定或 UI 能力无法实际验证时，记录明确的支持边界和后续项，不把删掉原版章节当作已经覆盖，也不杜撰 Python 方法名。

## 3. 实施批次与交付物

### B1：修正确认错误，建立可执行样例

涉及：[本地技能](../../dsh/skills/builtin/cordis-plugin-development/SKILL.md)、[动态 guard](../../dsh/extensions/cordis_guard.py)、[导出扩展](../../dsh/extensions/cordis_export.py)、[导出生成器](../../dsh/boot/python_plugin_export.py)。运行时文件仅在示例执行发现真实缺陷时改动。

1. 纠正动态示例中的 set_service/register_tool，使用 guard 已开放方法；不为迁就错误教程扩大 facade。
2. 提供可以原样执行的最小动态工具，包含参数必填写法、输入拒绝、输出校验、render 内容块、inject 和 stop 后撤销。
3. 将导出描述修正为：含 Client 的项目先走受支持 build，再 pack/install，并进行真实浏览器验证；核对生成 README 与 CLI 用法一致。
4. 原生类插件与动态 callable 示例分开，说明公共 API 1 的实验性质。

完成判据：技能代码片段被真实 define/run 消费，工具可调用、错误参数被拒绝、stop 后撤销；导出说明准确反映已有构建链。

### B2：完整 Win7 技能与实际接入

涉及：本机技能资源、原生扩展 provider、registry 映射（如新增插件）、CLI 开发 patch、Web 用户 preset 示例，以及配置和技能直接消费者测试。

1. 新技能正文严格按覆盖矩阵组织；详细 Python API 参考与交付规范放配套文件，通过相对资源链接导航。
2. 同一套资源用于两个入口；通过既有 CanonicalSkillFilesystem 注册独立 provider，避免复制维护两套正文。
3. 显式扩展提供简短本机路由指引并启用 export；不同挂载层各自验证所有权，不假设所有 preset 都是每会话实例。
4. 用空白 DSH_HOME、项目/用户技能根，捕获默认与扩展的首次实际模型请求：工具目录、完整技能目录、来源、实际 skill 返回内容。
5. 覆盖两个 Agent/两个 preset、同名用户技能、provider 卸载、旧技能并存和用户配置保留；扩展不可见或被遮蔽时应可诊断。
6. 从非仓库工作目录验证资源解析；发行阶段验证解压后的资源、补丁与 preset 同样可用。

完成判据：用户按文档启用一次扩展即可开展本机开发，不需要手动复制技能文件或向模型补充“请翻译成 Python”；默认合同与扩展增量分别可核对。

### B3：当前版本开发指南与三个完整项目

新增开发指南，拟放在 `docs/`，由技能和仓库用户入口链接。研究记录保留历史身份，增加接续链接。

| 项目 | 必须完成的旅程 |
| --- | --- |
| 动态 Host 工具 | Inspect、define/run、参数/输出验证、依赖、带状态运行与 stop 清理。 |
| 原生 Host 源码包 | 公共 API、package.json、cordis.patch.yml、显式 dsh.release.files、pack/add、冷启动、卸载、upgrade/versions/rollback。 |
| 动态 Host+Client 到发行物 | Python RPC + plain JS 最小面板、浏览器激活、精确版本 export、build、pack/add、重启后 RPC/UI、升级回退。 |

手写项目使用 `dsh.release.files`，导出项目使用 `dsh.sourceExport.files` 及来源校验，均按实际校验规则说明。规划时 python-echo 示例没有完整发行清单；实施已补齐并通过实际 pack/add 和冷启动验证。

指南区分 Host/session placement、preset fragment 和 isolateServices；动态 ID/Package ID 与包名/发行版本分开；临时运行、导出、构建、安装和冷启动是不同完成状态。

Win7 清单覆盖：Python 3.8 语法和标准库、UTF-8、中文与空格路径、实际 powershell.exe/cmd 能力、受支持纯 Python 精确依赖闭包、禁止隐式目标机安装构建依赖。现代开发机预构建 Client 的要求单独说明。

完成判据：新用户按指南即可复现三个项目，实际执行的命令和文件内容随验证留存，不依赖先读迁移研究记录。

### B4：真实模型开发任务评估

在确定性启动、技能与工具链旅程通过后，固定一个模型、参数和环境，对“只读工具”“有状态与清理的工具”“Host+Client 小面板”各执行至少三次独立任务。

仅提供用户需求和已启用开发入口，不额外粘贴正确答案。记录实际请求、技能加载、Inspect、生成源码、运行状态、安装/重启结果、人工介入与失败诊断，清除凭据。

分别统计首轮完成、允许修复后的完成和需要人工介入；九次小样本用于发现缺陷，不宣称稳定总体成功率。无法进行实际模型或 Win7 测试时，将相应状态保留为待验，不用 mock 或现代 Windows 结果代签。

## 4. 验证范围与执行顺序

| 批次 | 选择范围及理由 |
| --- | --- |
| B1 | test_cordis_guard 的真实注册/执行/撤销、test_cordis_tool_contracts 的语言和完整 roster、test_python_plugin_export/test_python_client_build 的直接交付消费者；新增用例读取技能真实片段，避免维护另一份测试专用示例。 |
| B2 | test_canonical_skill_journey、test_session_skill_catalog_scope、test_profile_boot_and_bundles 相关用例；新增正式 CLI/Web 首次请求、实际加载、扩展清理与安装相对路径旅程。 |
| B3 | 原生导出/依赖/安装/版本直接消费者与原版浏览器 oracle；覆盖面板、RPC、卸载、重启与回退，构建成功不替代浏览器成功。 |
| 默认合同 | 变化触及提示、工具注册或 Inspect 时，运行对应新鲜双侧观察，严格区分既有 native projection 与新增扩展；不放宽 fixture 来吞掉变化。 |
| B4 | 实际模型任务及其完整结果，不以字符串断言代替能力验证。 |
| 发行里程碑 | 批次稳定、准备发行时冻结候选，用新输出目录执行 scripts/verify_release.py；包含实际解压资源/技能和浏览器检查。Win7 支持声明另绑定新样例的目标机结果。 |

每批次使用新自有输出目录和现有短 pytest workspace，保存命令、范围、退出码、XML、日志和必要观察；失败后先定向修复。规划阶段仅做文档差异与链接检查，不重跑上一轮已通过测试、不构建 Portable、不更新迁移状态。

## 5. 与原评估的优先级对应

- A3、A5 过期说明：B1，先修明确错误。
- A1/A2：在实施顺序提升到 B2；技能实际可达是开发体验验收前提，不据此新增默认迁移阻断项。
- A4/A6/A7/A8：纳入 B2/B3 的主体内容，按覆盖矩阵逐项交付。
- A9：确定性观察从 B2 开始，实际模型结果在 B4；不能用任一层成功替代另一层。

## 6. 本次规划验证记录

本次只新增计划及评估接续链接；前轮 4 项定向通过仅作为已有能力参考，不是本计划实施完成证据。

- 两份文档共 35 个相对文件链接可解析；新增计划行尾空白检查和 `git diff --check` 通过。
- 已读取 migration/README.md、生成 status 和固定目标。调用 `scripts/migration.py check` 与 `ready` 后数分钟仍无输出；两者均会先校验历史 evidence 文件摘要。为将本次范围保持在规划文档，主动中断两项只读检查，退出码均为 1、无诊断正文；未确认具体耗时位置，不能据此判定台账失效或检查通过。实施前继续取得正式预检结果。
- 未执行本计划对应的新 pytest、模型任务、浏览器或发行门禁；未修改迁移状态或既有回执。
