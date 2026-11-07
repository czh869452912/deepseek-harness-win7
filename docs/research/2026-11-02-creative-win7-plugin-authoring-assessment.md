# Creative 模式 Win7 插件开发引导评估

日期：2026-11-02。检查基线：`4899763340e560efd034699fbd3717581915f7bd`。
迁移台账目标：`a4c74a91e06b00fe0b0937bde982170c526cc842`。

2026-11-06 接续：用户认可复核结论，要求沿用原版创造模式指引并面向 Win7/Python 工具链调整；具体批次、技能接入和验收安排见[实施计划](2026-11-06-creative-win7-authoring-plan.md)。计划不代表运行时或技能调整已完成，下文保留本次评估基线。

后续用户明确仅做原版迁移的必要适配，当前入口与验证见[对齐记录](2026-11-06-creative-win7-authoring-alignment.md)；上一计划的独立开发扩展接入已被取代。

本文回答：创造模式能否引导智能体开发 DeepSeek Harness Win7 插件，哪些说明仍沿用原版技术栈，以及应调整哪些产品入口、开发知识和验证方式。本文是源码评估及调整建议，不代表这些调整已经实现。

## 1. 结论

**运行能力已具备 Python Host 插件基础；本次发现开发说明存在不一致，但没有足够证据判定实际智能体的插件开发完成率。**

当前不能概括为“仍然只会指导原版 Node.js 插件”。本机 Creative profile、Cordis 系统提示、`cordis_define` 参数描述及执行器都已经明确使用 Python Host；Client 保持 JavaScript 符合复用原版浏览器的路线。

主要问题是知识与入口分裂：

1. CLI Creative profile 与 Web 的 `cordis` Agent preset 是不同装配路径，不能以旧 `dsh/presets/creative.yaml` 的文件内容推断两者的实际行为。
2. 上游 `cordis` preset 自带开发技能仍要求 Host 使用 JavaScript，与本机系统提示的语言要求不一致。但本机提示已明确说明原版 Host 示例需要翻译，并不再要求先加载该技能；没有观察到模型实际照抄 JS 的证据。
3. 本地 Python 技能不只缺少完整示例，其工具注册和服务注册示例也不适用于动态插件 Context。该文件是否进入特定部署的会话技能目录，本次未做运行观察，因此不能把文件缺陷等同于当前默认会话故障。
4. API 自省保留上游 TypeScript 签名与类型声明，这是已有协议等价设计，并非发现迁移错误；可另提供 Python 调用参考，但不能直接改写默认自省输出。
5. 导出、Client 构建、安装、升级、回退等实现已经存在；导出工具仍有已过期的 Client 不可安装说明。默认不挂载导出工具是有意保留原版七工具的决定，不能列作功能缺失。

建议先完成 **P1：修正本地动态 Python 示例和导出工具过期说明，并准确披露原版技能的语言适用范围**。本机技能接入、API 调用参考和交付教程属于 **P2：可选开发体验增强**，不应未经配对验证就改变默认迁移基线。没有发现需要因此推翻 Cordis 架构或重写浏览器前端的依据。

## 2. 评估边界与证据

本次检查当前工作区源码、现有测试和历史实施记录，并运行两项定向合同测试。开始检查时 `git status --short` 仅显示 `reference` 已有变动；本文不修改该目录，也不把它当成干净冻结的上游观察输入。

主要证据：

| 编号 | 位置 | 可支持的结论 |
| --- | --- | --- |
| E1 | [canonical profile 模板](../../dsh/boot/profile.py)、[本机 Creative bundle](../../packages/bundle/creative/cordis.patch.yml) | CLI Creative 在 base/headless 上增加 runner 和 Cordis 工具，并声明 Host 使用 Python。 |
| E2 | [官方 cordis preset](../../packages/preset/agent-presets/presets/cordis/agent.cordis.yml)、[随附开发技能](../../packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/SKILL.md) | preset 配置自己的技能目录；技能仍要求两个代码半部都使用 JavaScript。 |
| E3 | [提示适配](../../dsh/extensions/cordis_prompt.py)、[工具注册](../../dsh/extensions/cordis_manager.py)、[Host runner](../../dsh/extensions/host_runner.py) | 系统提示和 define 描述要求 Python 3.8.10；Host 源码由 Python compile 检查。 |
| E4 | [Inspect providers](../../dsh/extensions/inspect_providers.py)、[固定 API 目录](../../dsh/extensions/inspect_catalog.json) | Builtin 已原生化，Service/Event 和 referencedTypes 主要来自原版目录。 |
| E5 | [本地 Python 技能](../../dsh/skills/builtin/cordis-plugin-development/SKILL.md)、[技能发现](../../dsh/skill/canonical_filesystem.py)、[目录合并](../../dsh/skill/registry.py) | 技能文件存在不等于默认可见；发现依赖配置和目录，重名还受 rank 和 scope 影响。 |
| E6 | [动态 Context 和工具 guard](../../dsh/extensions/cordis_guard.py)、[公共 Python API](../../dsh/plugin_api.py) | 动态 Context、原生完整 Context、安装包 SDK 不能混为一种 API。 |
| E7 | [导出工具](../../dsh/extensions/cordis_export.py)、[源码导出](../../dsh/boot/python_plugin_export.py)、[Client 构建](../../dsh/boot/python_client_build.py)、[plugin CLI](../../apps/cli/plugin.py) | 交付流程已有实现；导出说明部分过期，且导出是显式扩展。 |
| E8 | [Host 示例](../../examples/python-echo/python/echo/plugin.py)、[包描述](../../examples/python-echo/package.json)、[Web 示例](../../examples/python-web-echo/python/web_echo/plugin.py) | 有可复用原生示例，但还需接入模型可发现的开发导航。 |
| E9 | [默认导出扩展决策](2026-10-07-cordis-export-extension-progress.md)、[Client 构建记录](2026-10-01-python-plugin-client-build-progress.md)、[Session Client 记录](2026-10-01-python-plugin-session-client-progress.md) | 默认七工具与显式导出是已有设计决策；早期“Client 尚不能交付”不能代表现状。 |

静态代码能够证明说明冲突和实现入口存在，不能证明任意模型都会受误导、任意插件都可运行，或最新发行包已经携带未来调整。历史浏览器记录也不替代本次候选的新验证。

## 3. 必须明确的产品与开发边界

### 3.1 CLI profile 与 Agent preset

新建的默认 `dsh --profile creative` 从 canonical profile 模板加载 `@deepseek-win7/dsh-creative`，在 base/headless 之上增加动态插件能力；已有自定义 profile 不据此假定自动被覆盖。Web 中的 `cordis` 则是可选的 Agent preset，配置了随安装目录提供的技能。Web bundle 默认选择 `standard`；本文对 `cordis` 的判断不泛指所有 Web 会话。

`dsh/presets/creative.yaml`、`dsh/presets/creative/agent.cordis.yml` 和官方包下的 preset 都存在，但不是可以互相代替的运行证据。应在开发文档中列明各入口的提供者、技能路径、工具可见域和升级行为；后续测试必须观察正式启动后的首次模型请求。

### 3.2 Host / Client 与 Host / preset 是两条独立轴

Host / Client 决定代码运行位置和语言；Host composition / Agent preset 决定服务与工具的共享范围、注册层和生命周期。本地 Python 技能目前首先要求区分 Host 和 Agent Presets，遗漏了 Client 语言与联合插件路径。

建议所有开发任务先回答两个问题：功能需要 Python Host、浏览器 Client，还是两者；贡献属于进程共享的宿主装配，还是预设层的贡献。相同 standing preset 的共享语义也必须保留，不能把 preset 简化为“每个会话各创建一份”。

### 3.3 动态试作与源码插件

| 形式 | 当前入口 | 引导应说明的边界 |
| --- | --- | --- |
| 动态 Host 插件 | `cordis_define` 的 `code.host`，定义 callable `plugin` | Python 3.8.10；Context 经 guard；通过 inspect 确认能力；运行需遵守批准与状态流程。 |
| 动态 Client 插件 | `code.client` | plain JavaScript 函数体；不编译 TS/JSX；依赖真实浏览器与 Client provider。 |
| 原生源码插件 | `dsh.plugin_api`、`dsh.python` 描述、Loader | 使用受支持公共入口；原生类插件与动态 callable 示例分别展示；API 1 仍标为实验。 |
| 动态插件源码交付 | 显式 `cordis_export`，可选 Client build，再 pack/install | 固定所属动态版本；动态 ID 与发行包名/版本分开；Client 构建后仍需浏览器验证。 |

临时插件运行成功不等于已安装或重启后恢复。导出项目不等于成品插件，构建完成也不等于 Client 激活成功。

## 4. 调整项及优先级

P1 表示已定位到与实际接口/能力不一致的说明，应优先修订；是否已经造成实际任务失败仍需观察。P2 表示建议的开发体验增强或验证工作。优先级是本报告的工程判断，不是现有迁移签收标准，也不增加当前发布的阻断项。

| 项目 | 优先级 | 现状与影响 | 建议调整 | 完成判据 |
| --- | --- | --- | --- | --- |
| A1 本机开发身份与入口 | P2 | CLI persona 简述 Python，另有完整 Cordis 语言适配提示；多份配置的存在可能增加开发者定位成本，未观察到选错入口。 | 文档区分正式入口和语言边界；可选本机开发扩展仅加入任务所需提示，不强制给模型注入内部 profile 拓扑。 | 正式请求的语言说明准确；新增开发扩展单独验证，默认提示差异有明确归属。 |
| A2 技能发现与语言适用范围 | P1（说明）/P2（接入） | Web cordis 随附技能写 JS Host，但系统提示明确要求翻译；本地 Python 技能默认是否可见未实测。 | 先在开发文档解释原版技能的适用范围；可选本机开发扩展使用独立技能名、显式挂载。保留原版技能和默认发现规则。 | 空白根下分别观察默认与扩展会话的目录、内容、来源；验证同名和 scope，不把默认未新增技能判为失败。 |
| A3 修复 Python 示例 | P1 | 本地技能使用 `ctx.set_service` 和 `tools.register_tool`。动态 facade 未开放前者，`SandboxTools` 只提供 `register` 等接口；动态工具还要求 `harness.defineTool` 的标记与 output 合同。 | 动态示例使用 `ctx.provide` 和 `harness.defineTool`/`harness.registerTool`，补齐 schema、output/render；原生完整 Context 示例另列。 | 技能中的完整动态示例经真实 define/run 执行，工具可调用且 stop 后撤销。 |
| A4 Python API 调用参考 | P2 | Builtin 已描述 Python；Service/Event 保留 TS 描述是既定等价合同，Python 使用方式可另行补充，但未发现模型因此失败的证据。 | 在文档/可选技能提供已验证的调用参考；不向默认 Service/Event/Tool 输出增加字段或改写签名。额外 Inspect provider 若确有需求，仅作显式扩展。 | 默认目录完整输出仍严格配对；扩展参考的服务调用、空值、await、inject 和卸载经过独立验证。 |
| A5 导出与交付导航 | P1（过期文案）/P2（教程） | 默认七工具不含 export 是已有决策；原生导出工具描述仍称 Client 没有构建支持。 | 修正该原生扩展的过期描述；可选开发预设/补丁和教程串联 export/build/pack/add。保留默认七工具的完整定义与顺序。 | 默认合同不变；扩展符合其注册层的可见域和可逆所有权；教程只声明受支持交付路径。 |
| A6 生命周期和作用域 | P2 | 原版技能较全面，本地技能只有概念片段；易漏依赖停用、异步清理、错误恢复、共享 preset 及跨 Agent 隔离。 | 加入动态和安装包各自的清理方式，await/取消、依赖丢失与恢复、更新回退和旧引用失效案例。 | 两 Agent/两 preset、缺依赖、取消、stop、卸载/重装及回退的行为符合实际所有权。 |
| A7 Win7 与发行约束 | P2 | 系统提示要求兼容，但没有模型可直接遵循的完整交付清单。 | 技能涵盖 Python 3.8 语法、UTF-8、Windows 路径、powershell.exe/cmd 兼容、显式发行文件、纯 Python 精确依赖闭包与实验 API。 | 普通插件开发和安装流程不要求目标机 Node/pnpm/pip；新增依赖和 OS API 在目标范围验证。 |
| A8 示例和用户导航 | P2 | Host/Web 示例和多篇研究记录已有实现，但信息分散、旧结论与新结论并存。 | 编写当前版本开发指南，由技能链接最小示例和 CLI；研究记录继续保留历史身份，增加必要接续链接。 | 新用户无需阅读迁移历史即可创建、测试、打包、安装、升级和回退插件。 |
| A9 验收目标 | P2 | 现有提示和工具合同测试不测“模型是否能按实际技能独立完成任务”。 | 增加确定性启动/工具旅程，再做小规模真实模型任务评估，分别记录结果。 | 观察实际请求、代码、工具调用、安装与重启行为，不以提示文本存在或模拟回答代替任务完成。 |

### 4.1 A3 的具体错误边界

完整 `Context` 支持 `set_service`，所以不能把该方法全局删除或认定项目规范无效。问题在于技能标为动态插件开发，却把完整原生 API 当成动态 facade API。`cordis_guard.py` 的 `CTX_VERBS` 不含 `set_service`；`SandboxTools` 也不提供 `register_tool`。

动态工具还要求先由 `harness.defineTool` 生成受认可的定义，不能把普通 dict 任意传给动态注册器。技能应提供可运行的完整样例，而不是让模型从几个省略号推测 output schema 和 render。

### 4.2 A4 不应机械替换 TypeScript 字符串

TypeScript 类型信息在此不仅是可选参考，还是当前固定配对合同的一部分。[既有 Inspect 实施记录](2026-10-01-cordis-inspect-progress.md)已明确这一点。应在配套开发文档/可选技能解释其用途，并另给 Python 绑定的实际调用方式；不能把 TS 签名的存在判为实现缺陷。特别是 `UNDEFINED` 在部分原生协议中真实存在，不能将所有 undefined 全部改成 None；`Promise` 也不能不经提供端检查就一律改写为 coroutine。

优先覆盖常用开发能力，如工具、文件、事件、计时器、RPC 和 preset 查询。其余目录明确标注来源与语言，再逐项补齐。能力是否已经挂载仍应由当前运行时查询决定。

### 4.3 A5 需要修正文案，无需重做 Client 构建系统

`apps/cli/plugin.py` 已有 `build`、`pack`、本地目录/ZIP 与固定 SHA-256 HTTPS 安装、upgrade、versions、rollback 和 remove 路径。`python_client_build.py` 已支持导出 Client 的封装和 Host/Session placement 相关产物。

应将导出工具文案改成“含 Client 源码的项目先执行受支持的 build，再 pack/install，并在浏览器验证”，而不是继续声称没有构建支持。此 build 只处理已导出的 plain JS 结构，不是通用 TS/TSX 编译器；任意 Client 工程不能据此宣称可构建。

同样，`release_files()` 接受显式 `dsh.sourceExport.files` **或 `dsh.release.files`**；并非只有导出项目可以 pack。指南应分别说明手写项目、导出项目的发行文件清单与额外来源校验，不能将缺少发行清单的 `dsh.python` 示例直接当成可 pack 项目。

## 5. 推荐实现方式与顺序

### 第一批：统一模型实际看到的指导

先修复错误 Python 示例及原生导出工具的过期描述，并在开发文档中明确原版 Host 技能需要语言适配。可选的 Win7 开发技能正文按“选择运行位置—确认作用域—inspect—实现—试运行—清理—选择持久交付”组织。详细包格式和依赖规则放在配套文档。

CLI Creative 与 Web 的可选开发扩展可以共享一套本机知识，但共享正文不等于向所有默认会话增加技能或提示。接入方案应显式启用并单独命名，不改写安装自带的上游 preset/技能，也不改变技能 rank、scope 或合并优先级。若确需新增 provider/适配层，仍遵循 inject、服务动态查找与可逆 effect。

### 第二批：API 自省及端到端示例

为常用 Service/Event 增加经过实际调用验证的 Python 说明，建立动态工具、Host 源码包、Host+Client 联合插件三个完整示例。补齐导出项目和手写项目的不同交付前提，以及 Host/session placement 的安装、preset fragment 与使用方式。

保留独立 `cordis_export` 插件。建议提供明确的“Win7 插件开发”扩展 preset/补丁启用它，而非重新将它隐式塞入默认 manager。已有默认七工具决策不能因本次评估被无意撤销；如果未来改变默认产品组合，应单独记录行为变化并验证实际 roster。

### 第三批：任务完成率与候选验收

先用确定性旅程确认正式启动、技能内容、inspect、define/run 和安装链，再使用真实模型完成限定任务。只有该批次稳定、准备统一签收或发布时才运行完整发行门禁；不因每个提示文案修订重复构建 Portable 或跑全量。

## 6. 建议验收矩阵

| 场景 | 必须观察的结果 |
| --- | --- |
| 无项目、无用户技能的 CLI Creative | 观察首次请求和实际技能目录，确认既有 Python Host 提示、默认七工具和扩展状态；不预设本机技能默认存在。 |
| Web cordis / 本机开发扩展 preset | 默认保留原版技能和既有 Python 适配提示；扩展读到独立本机技能；技能来源正确且用户 preset 不被覆盖。 |
| 创建动态只读工具 | define/run、参数与输出校验、实际工具执行、stop 后不可调用；不使用 facade 未开放的方法。 |
| 可选/必需服务与事件 | None/UNDEFINED、await 与回调参数处理正确；等待、依赖消失及恢复行为可观察。 |
| 源码交付 | 明确版本 export；正确选择 Host 或 session；Client 项目 build；显式文件 pack；目录/ZIP 安装与冷启动。 |
| 升级、回退和卸载 | 版本及效果可核对；原有用户数据按约定保留；旧 handler/工具不继续成功；共享与隔离遵循实际注册层，不把同一 standing preset 改为每会话独立实例。 |
| 错误引导控制 | 给出原版 JS Host 示例时模型识别需适配；不为普通 Host 插件要求 Node/pnpm；不擅改自带 preset。 |
| 支持范围控制 | TS/JSX、原生依赖和未提供 Client/browser 能力得到准确解释；不把 build/define 成功当运行成功。 |

真实模型评估建议使用“只读工具”“带状态和清理的工具”“Host+Client 小面板”三类任务。保存模型与参数、完整实际提示/技能来源、生成源码、必要工具轨迹和失败诊断；评估材料需去除凭据。先固定一个模型和输入建立基线，单次成功不作为稳定完成率。

## 7. 本次验证与限制

本次新增报告，未修改运行时、上游文件、默认预设或迁移状态。按文档范围进行差异与相对链接检查；为核实核心判断，额外运行现有两个定向测试：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_cordis_tool_contracts.py::test_native_host_guidance_and_parameter_contract_are_explicit tests/test_cordis_tool_contracts.py::test_manager_registers_exact_source_tool_roster -q --junitxml=<本次自有输出目录>/contracts.xml
```

结果：**2 passed，0.82 秒，退出码 0**。范围覆盖原生 Host 语言提示/define 合同和 manager 实际注册工具 roster；不覆盖正式 CLI/Web 首次请求、技能实际选择、生成插件任务或 Client 浏览器旅程。保留 pytest-asyncio 的既有 fixture loop scope 提示。

日志与 XML 位于 `.goose/out/creative-authoring-assessment-20261102-092841/contracts.log` 和 `contracts.xml`。未重新执行全量 Python、真实模型调用、浏览器旅程、Portable 构建或 Win7 真机测试；本文不授予新的迁移/发行资格。

文档检查：24 个相对文件链接均可解析；`git diff --check` 通过，新增报告另检查行尾空白。迁移检查结果如下：

| 命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe scripts/migration.py check` | 退出码 1：`migration: missing file: reference/apps/desktop-host/package.json`。 |
| `.venv/Scripts/python.exe scripts/migration.py ready` | 退出码 1：同一缺失文件。 |

该缺失位于本次未改动且开始时已有变动的 reference 工作区；本次没有修复或还原它。因此无法报告迁移检查通过，也没有据此推广台账。既有历史接续记录仅用于辨别实现进展，不把其中旧通过数量累计成本次验证。

## 8. 事实与原版一致性复查（2026-11-02）

### 8.1 对初稿的更正

复查后直接修订了正文，以下保留更正依据，防止将设计建议误读为现存故障或既定迁移要求：

| 初稿中不够准确的判断 | 复核后的结论 |
| --- | --- |
| 开发引导尚未形成可验证流程。 | 已有多项真实 runner、导出、安装与重启测试；本次尚未测真实模型独立开发成功率。只能确认说明不一致，不能据此否定现有流程。 |
| JS Host 技能与 Python 提示冲突，可能误导模型。 | 文本语言要求确有不一致，但 `native_contracts()` 已明确告知需翻译 Host 示例，并移除了强制先读该技能的指令。实际加载、选择和错误生成尚未观察。 |
| 本地 Python 技能应接入默认路径。 | 本次没有实测默认技能目录。新增技能会改变可见目录和模型消息；应先做显式本机开发扩展，不将其默认缺席认定为迁移缺陷。 |
| API 自省中的 TS/undefined 信息需要修正。 | Service/Event 的 TS 信息属于既有固定协议等价设计；补充 Python 参考有价值，但直接改写默认输出会产生配对差异。A4 下调为 P2。 |
| 只有 sourceExport 项目可 pack。 | 实际也支持 `dsh.release.files`；正文已更正。是否可 pack 由完整描述、显式清单和校验决定。 |
| 显式扩展应只对一个 Agent 可见。 | 取决于挂载层：直接挂到 Agent 与挂到 standing preset 的所有权不同。保留现有注册层共享/隔离语义，不能一律收紧为每会话。 |

本地 Python 技能的 `set_service` / `register_tool` 动态示例不适用，以及原生 `cordis_export` 的 Client 构建说明过期，仍有直接实现依据。这些事实不意味着当前默认模型请求必然包含它们。

### 8.2 一致性约束与建议边界

初稿建议如果被解释为“修改默认技能、提示或自省输出，但仍宣称完整输出不变”，确实会与现有迁移验证产生冲突。修订后的建议遵循以下边界：

| 范围 | 当前等价/适配依据 | 本报告允许建议的调整 |
| --- | --- | --- |
| 七个默认 Cordis 工具 | [合同测试](../../tests/test_cordis_tool_contracts.py)与[双侧观察器](../../scripts/cordis_tools_oracle.py)检查实际注册及完整定义。 | 保留默认数量、顺序、参数、输出和除既有语言适配外的描述；export 继续为显式扩展。不能只保留名称就声称合同不变。 |
| 模型提示与语言转换 | `cordis_prompt.py` 精确替换固定文本；观察器核对已审查的 native projection。 | 原有 Python Host / JS Client 适配有依据。新增文字会改变模型输入，即便功能意图不变，也不能自动视为现有适配已覆盖；应归入显式扩展，或另行记录和验证新的语言适配。 |
| Service/Event/Tool Inspect | [Inspect 观察器](../../scripts/inspect_oracle.py)比较完整目录、逐项查询及相关类型；Builtin 的 Python 适配另计。 | 默认 provider ID、顺序、输入/输出和类型声明保持现状。Python 参考优先放在文档/可选技能；新增 provider 仅在显式扩展中出现，并单独测试。不能增加字段后放宽原配对判据。 |
| 原版 preset 和技能发现 | preset 自带技能；registry 按 scope、rank 和 provider 顺序合并。 | 保留原版文件、默认 roster 和合并算法。可选本机技能使用独立名字和明确所有者；分别验收默认基线与扩展后的预期差异。 |
| 生命周期和授权 | runner/guard、preset 挂载和导出插件已有所有权、批准及清理约束。 | 修正教程以遵循实际约束；不扩大 facade、自动批准、跨所有者调用、改变 standing preset 共享，或将动态插件自动持久化。 |
| 浏览器与 Client 构建 | 固定浏览器复用；动态 Client 为 plain JS；原生导出 build 不是通用编译器。 | 保留 React/TSX/CSS 与 Connection/Typert 链路；解释动态 JS 与开发机预构建 Client 的区别。现代开发机/CI 使用 TS/TSX 工具链并不与 Win7 端无需 Node 冲突。 |
| 本机持久源码交付 | `cordis_export`、Python 包安装与 build 属显式原生扩展。 | 修正其过期文案、补充支持范围和教程；不能把这些扩展宣称成原版默认七工具之一，或据此认证任意原版 JS Host。 |

因此，**说明修正和显式开发扩展可以与迁移一致性目标并存；默认合同的无记录改写不能。** 本报告没有批准扩大既有例外、忽略提示差异、修改 fixture 来容纳新输出或提升任何迁移状态。

### 8.3 复查验证

本轮按新增疑点选择六项现有用例：原生语言/define 合同、七工具实际注册、Inspect Host 注册合同、guarded 工具执行和撤销、显式 export 的 Agent 所有权，以及实际 export/build/pack/install/卸载/重启。最后一项通过原生 RemoteDispatcher 调用 Host，未启动浏览器，不将其写成 Client 实际激活验证。

结果：**6 passed，30.95 秒，退出码 0**。完整节点命令、日志和 JUnit 位于 `.goose/out/creative-authoring-review-20261102-093539/verification.json`、`contracts.log`、`contracts.xml`。这些结果证明现有相应消费链仍通过，不证明尚未实现的建议已经与原版等价。

首次选择了并不存在的 pytest 参数节点 `catalog/all-service-event-contracts`，导致收集阶段退出码 4，未运行测试；原日志/XML保留在 `.goose/out/creative-authoring-review-20261102-093506/`。该目录场景实际由 `scripts/inspect_oracle.py` 的完整双侧路径比较，不在当前参数化 pytest fixture 中。纠正为真实存在的 `registry/host-contract` 节点后运行上述六项；不能将后者称为完整 Service/Event 目录配对通过。

修订后 28 个相对文件链接和行尾空白检查通过，`git diff --check` 通过。本轮只修改报告；未执行新鲜双侧 oracle、实际模型任务、浏览器旅程或完整发行门禁，也未重跑首轮已失败的 migration check/ready。默认技能的实际可见性和模型采纳情况仍明确待观察。
