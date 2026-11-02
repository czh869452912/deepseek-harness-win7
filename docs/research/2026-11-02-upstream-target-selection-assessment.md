# 0.1.5-rc.3 之后的上游对齐目标选型

日期：2026-11-02（Asia/Shanghai）。产品工作区检查提交：`d29fae0e8761b10c7855d5f0b71f3adfdec2e220`。
性质：Release 核对、固定 Git tree 源码评估与迁移建议；本次未实施版本迁移。

补充范围：当前省略包是否应补齐，见[省略包必要性评估](2026-11-02-omitted-package-assessment.md)和[完整静态筛查表](2026-11-02-omitted-package-review.json)。建议先闭合rc.5默认合同，再独立推进LSP等高收益能力，不以补全所有包名作为目标。

## 1. 决策

**建议下一轮正式对齐目标选择 `dsh-v0.2.1-rc.5`，固定提交 `b830ec950faba0a46dda564be3e2d854afed94f1`。**

以当前已交付 `dsh-v0.1.5-rc.3 / a4c74a91` 为差分起点，按依赖拆成多个实现批次，最终围绕同一个 rc.5 候选统一验收。没有必要把 0.1.7 和 0.2.0 各做一轮正式发行。0.2.0-rc.2 保留为范围收缩时的备选；0.2.2-alpha.2 用于后续观察与问题回移研究。

理由是 **0.2.1 已提供与本项目相关的插件发现、创造入口、会话恢复、终端和模型体验收益，而 0.2.2 又增加了一轮 Session、工具执行、PTC 和 Cordis 公共接口调整**。应把本轮工程投入用于闭合 rc.5 的跨模块合同，避免同时承担后一轮接口演进。

这是选型判断，不是 Win7 兼容认证。rc.5 仍是官方预发布，不能称为“正式稳定版”或“最终 RC”。本次不改 `migration/baseline.json`、reference checkout、生产注册表或任务状态；上游目标、本产品版本号和发行资格继续分别管理。

## 2. 本次核对与旧报告的变化

核对来源为 [GitHub Releases](https://github.com/deepseek-ai/deepseek-harness/releases)、Release REST API、`git ls-remote --tags origin`，以及本地对象库中候选 tag 对应的最终 tree。远端 tag SHA 与本地候选一致。摘要、精确 SHA、计数命令及预检结果保存在[结构化核对记录](2026-11-02-upstream-target-selection-evidence.json)。

旧的 [10 月14日评估](2026-10-14-upstream-baseline-iteration-assessment.md) 以 0.1.2-alpha.1 为起点，其“0.2.1 仍为早期 Alpha”的时间判断现已过期。以下新发布记录均晚于旧报告日期，日期按北京时间列出：

| 版本 | 发布日期 | 对选型的影响 |
| --- | --- | --- |
| 0.2.1-alpha.3 | 10-14 | 旧报告之后继续完善恢复、SDK resume、终端与模型设置。 |
| 0.2.1-alpha.4 / alpha.5 | 10-15 / 10-16 | 加入自定义插件索引、兼容版本声明，继续修正技能刷新和终端行为。 |
| 0.2.1-rc.1 | 10-17 | 汇总相对 0.2.0-rc.2 的功能和接口变化，已进入 RC 线。 |
| 0.2.1-rc.2 | 10-17 | 适配 DeepSeek-V4.1-Flash-1017 与 DeepSeek Search/Fetch API。 |
| 0.2.1-rc.3 | 10-23 | 增加浏览/创建插件菜单，修复草稿，调整 API Key 模型列表更新。 |
| 0.2.1-rc.4 | 10-28 | 修复 ACP 诊断混入 stdout。 |
| 0.2.2-alpha.2 | 10-28 | 功能更多，但引入新的运行时和公共接口迁移。 |
| 0.2.1-rc.5 | 10-30 | 在 RC 线上改善思考内容呈现，成为本轮首选。 |

这些候选在 API 中均为 `prerelease: true`。0.2.2-alpha.2 语义版本更高，但并非最后发布者，也不包含 rc.5 的全部提交：`rc.5...alpha.2` 的对称提交数为 **4 / 2,161**。两个固定 tree 必须分别比较，不能把 Alpha 当成 RC 的简单超集。

旧报告的“包数很少、RC 因而低风险、Win7 绝对兼容”等结论不能复用。当前台账仍是 `accepted_upstream: null`；已有完整门禁只认证绑定的有限合同和产物。

## 3. 候选比较

下表均相对当前上游基线 `a4c74a91`。提交数含 merge；路径数使用 `--no-renames`，仅统计 `apps/ packages/ cordis/`，仍含测试、文档、locale、manifest 和生成文件，不是待移植代码量，也不能换算人日。

| 候选 | 提交增量 | 上述目录变更路径 | 判断 |
| --- | ---: | ---: | --- |
| 0.1.7-rc.2 | 3,647 | 5,992 | 不作为正式过渡目标：已经承担较大的协议/自动化变更，却拿不到后续累积收益。 |
| 0.2.0-rc.2 | 4,095 | 6,187 | 可作预算明显受限时的备选，但会推迟 0.2.1 插件生态及恢复修复，并产生后续重复验收。 |
| 0.2.1-rc.4 | 6,035 | 8,317 | 与 rc.5 成本接近，没有充分理由停在前一补丁候选。 |
| **0.2.1-rc.5** | **6,039** | **8,319** | **首选：收益足够明确，固定目标后可按合同推进；总体复杂度高。** |
| 0.2.2-alpha.2 | 8,196 | 11,550 | 暂缓：在本轮已很大的差分之外，又改变多项基础接口。 |

rc.4 到 rc.5 的四个新增提交包含发布/合并提交和思考渲染修复；业务改动集中于 ui-chat、翻译展示消费者和 Cordis slot catalog。它不是又一次 Host 架构跃迁，但仍需验证这些客户端消费者。

## 4. 为什么 0.2.1 值得作为下一轮目标

### 插件生态与创造模式

[rc.1 发行说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.1-rc.1) 已提供自定义插件索引发现/安装、保留草稿进入创造模式的入口、依赖同步与可替换插件的热更新，以及 `engines.dsh` 版本兼容判断。这比只保留动态 define/inspect 工具，更接近用户能发现、创建和交付插件的完整流程。

但上游安装实现仍属于 Node/npm 生态，不能直接让 Win7 目标机依赖 pnpm，也不能假定 npm 插件可由 Python Host 执行。本项目已有 Python 安装、导出、Client build、升级与回退能力；迁移应让原样管理 UI 消费这些有明确支持范围的服务，定义索引条目、兼容性、事务和重启恢复合同。任意 JS Host 插件兼容仍需单独立项。

与[本日创造模式评估](2026-11-02-creative-win7-plugin-authoring-assessment.md)衔接：Python 开发说明、动态 facade 示例与上游 JS 技能的语言边界仍需修正。新版创造入口本身不会解决提示和 API 示例不一致。

### 日常可靠性与部署

0.2.1 累积了会话续接、退出时最后记录保存、持久 PowerShell 收尾、PTY 清理及远程连接/偏好恢复的修复，并改变凭据优先级。它们直接影响当前产品的真实使用路径，迁移时应核对最终实现与现有 Python 修复的交集。

Web 增加对外 URL/反向代理前缀、指定地址监听和 HTTPS 配置；模型 UI、Search/Fetch 和插件入口也有增益。这些能力应各自测试，不能以“换了新版前端”作为已实现证明。SDK resume 和独立子代理 preset 则要求恢复、调度和消费者一起升级。

## 5. 必须先闭合的迁移合同

### 5.1 Session v4 是第一条主线

rc.5 的 [generated catalog](https://github.com/deepseek-ai/deepseek-harness/blob/b830ec950faba0a46dda564be3e2d854afed94f1/packages/session/session-format-catalog/src/generated.ts) 明确 `currentVersion: 4`。当前产品为 v3，这不是改一个版本号：

- v3→v4 把工具结果提升为 tool 角色，转换消息来源，保留扩展数据并拒绝不受支持的输入。
- 转换涉及继承截点、事件坐标、delivery 代际和子代理目录证据；不能只拿一份孤立 transcript 证明父子恢复完整。
- JSONL 提供端负责只读准备、源修订检查、独占后继发布及失败保留；Agent、请求历史、投影、Remote、SDK 和 ACP 都消费这些结果。

详细规则以固定 tree 的 [v3→v4 规范](https://github.com/deepseek-ai/deepseek-harness/blob/b830ec950faba0a46dda564be3e2d854afed94f1/packages/session/session-format-v3-to-v4/README.zh.md) 为准。首批应覆盖 v0–v3 升级、原生 v4 冷恢复、压缩/明文、fork/子代理、取消和发布失败。旧 v3 字节及旧程序可读取的代际必须保留；新 v4 追加不自动具备反向迁移能力。

### 5.2 Connection、Gateway 和身份权限

固定 rc.5 的 Connection 已公开 Peer、Principal、Invocation 及 admission 接口；base bundle 要求 `remote-access` 提供方法级访问控制。应迁移会话访问、API 连接参与方式、鉴权/重连、上传与实际 Remote 消费者，继续使用 canonical Connection/Typert 链路。

需要实际拒绝用例证明非 owner 调用边界；本机 loopback 能打开页面不足以证明协议对齐。不能恢复旧 ApiProxy/双业务 SSE 来兼容新 UI。

### 5.3 Boot、Loader、配置与插件生命周期

需处理 invariant 入口退出、子路径元数据、`engines.dsh`、依赖同步、热替换与不能热替换时的重启语义。新版原样 UI 的 index/manager RPC 必须由真实服务提供，并与本机 Python 包分发格式保持清楚的边界。

默认预设也有产品差异：上游 Minimal 已增加图片/压缩能力；本项目约定 Minimal 为 shell + editor。应继续将这个差异登记为明确产品 overlay，不能静默扩展 Minimal 后宣称完全同构。

### 5.4 子代理、Team、PTC 与凭据

子代理立即返回 child ID、`session/wait`、独立 preset、Team Inbox 直接投递及旧 outbox 退出，需要连同工具结果和冷恢复迁移。Python PTC 的 Session sandbox/sandboxPolicy 注入与 native/PTC 展示模式也须检查。

Web/Desktop 优先保存凭据、headless 默认使用环境/.env 的新优先级会改变真实请求身份。应验证既有配置升级和实际启动请求，不能只改 UI 的设置文字。

## 6. Win7、Python 与浏览器边界

| 层 | 源码事实 | 本项目决策及待验证项 |
| --- | --- | --- |
| Python Host | 上游 rc.5 根 Node engines 为 `^22.19.0 || >=24.0.0`。 | Source 运行/构建环境和 Win7 产品运行环境分开；目标机仍为 Python3.8.10。不能据 Node 要求直接排除该版本，也不能据 Python 重实现直接断言兼容。 |
| 构建工具 | rc.5 使用 pnpm11.28.5；alpha.2 根 Node 要求升至 `>=24.9.0`。 | 在现代构建机固定实际可运行工具链，并核对 pnpm/打包工具自身要求；根 engines 不是完整工具链兼容证明。 |
| Desktop | rc.5 与 alpha.2 的上游 Electron 均为 `^44.7.0`。 | 延续本项目 Electron22.3.27 外壳适配，审查 IPC/preload/原生接口、安装与更新，不照搬上游 Electron 依赖。 |
| 原样 Web | rc.5 Vite 配置为 `target: 'es2022'`。 | 语法目标不足以认证 Web API、CSS 和依赖；必须在 Chromium108/Electron22 中实际验证。若必须改上游浏览器业务代码才能工作，应重新评估本轮范围。 |
| 自动化与外部运行时 | browser/computer use、SSH helper、Node PTC 具有独立驱动/运行时需求。 | 逐项做 provider、依赖、OS、位数和分发分类；当前没有证据保证全套 Win7/x86 可用。可选能力不得制造空壳激活成功或成为基础 profile 的隐藏依赖。 |
| Windows ACL | rc.5 有诊断/修复技能，仍披露受限令牌和 ACL 的部分强制边界。 | 本项目 [issue #4](https://github.com/czh869452912/deepseek-harness-win7/issues/4) 的继承/NULL DACL 问题继续独立处理。不能把新版技能存在等同于现场问题已修复，也不能用新基线自动接受旧候选方案。 |

本轮没有执行候选 Source、真实浏览器或 Win7/安装验收；目前没有任何一项新增兼容能力可据本文签收。

## 7. 为什么暂不选 0.2.2-alpha.2

[alpha.2 发行说明](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-alpha.2) 包含有价值的插件更新失败恢复、引用与完整 Markdown 复制、国际化、后台任务和缓存优化，值得持续跟踪。但它同时带来：

1. Session 的快照、事件、状态和投影订阅拆分，异步投影句柄及审批恢复依赖变化。
2. 按步骤启用工具，`tools.resolve/executable` 与提示词接口调整；模型选择提前固定，`agent/request` 不再改路由。
3. native/PTC 执行插件拆分、overlay 替代旧 mode 配置、Node PTC birpc 与 SSH 协议2→3。
4. Cordis Timer 返回值、Fiber 配置访问、官方 bundles 导出位置以及底层运行时要求变化。

这些是提供端和所有消费者共同迁移的合同，工作量不能按新增 UI 功能数估计。暂缓的依据是额外接口成本及本项目当前落差；不能单凭 Alpha 名称认定实现不稳定。若产品明确把这些能力列为近期必需，才值得重开 0.2.2 的取舍。

## 8. 建议实施顺序与决策检查点

| 批次 | 工作与完成判据 |
| --- | --- |
| S0 输入与风险探针 | 准备独立、干净的 rc.5 Source；固定构建工具链。先验证原样 renderer 的 Chromium108/Electron22 启动/预览、v3→v4 最小父子恢复，以及插件管理协议接入 Python 分发的可行性。 |
| S1 Session/Agent | v4 格式链、存储发布、请求历史、投影及子代理消费者配对；覆盖旧数据保留、冷恢复和拒绝路径。 |
| S2 Remote/Boot | Peer 权限、Connection/Gateway、canonical profiles、配置升级、Loader/依赖/热重载；连同 SDK/ACP/stdout 合同闭合。 |
| S3 产品路径 | 原样插件管理/索引与创造入口、模型/Search/Fetch、终端、预设、实际浏览器流程；维护明确的 Win7/Python overlay。 |
| S4 统一资格 | 已知修复和定向回归完成后冻结候选，以 `verify_release.py` 执行新鲜单次完整门禁；双架构 Portable、Desktop 安装升级、旧数据及真实服务按各自范围验收。 |

S0 的结果用于校正实施范围与估算。如果原样 renderer 或必需 Host 合同无法在既定环境成立，应保留探针失败并重新选范围；不能以修改前端或伪造 provider 悄悄绕过。0.2.0-rc.2 只是重新评估的备选，也要独立探针，不能当成自动兼容的退路。当前没有足够的实际探针结果承诺工期。

选择 rc.5 作为终点不要求中途逐个版本发布。读取中间版本的相邻格式或协议差分有助于实现，但每个开发批次仍须以 rc.5 最终合同核对，避免在中间语义上积累新的兼容层。

## 9. 本次验证与限制

本次仅新增评估文档和结构化核对记录，并给旧报告加接续链接。验证范围为 Release/tag 身份、固定源码、计数复核、JSON、相对链接与 diff 检查；未运行 pytest 或构建 Portable，因为没有修改运行时代码，也未进入候选资格阶段。

启动时 `git status --short` 已显示 reference 变动：其 checkout 为 `cd5ef814`（0.1.2-alpha.1），台账目标仍为 `a4c74a91`。实际 `migration.py check` 和 `ready` 均退出1，原始错误为 `migration: missing file: reference/apps/desktop-host/package.json`。因此本次没有取得当前迁移预检通过，也没有改动 reference 来消除这一现场；所有候选源码读取都显式指定 tag。

Release API 原始返回和临时源码摘录保留在 `.goose/out/upstream-selection-20261102/`；该目录不是正式迁移验收证据。结构化摘要已保存来源 URL、原返回 SHA-256、候选身份和统计口径，关键源码可由固定 SHA 重建。以后上游继续发版时，应重新核对选型依据，不能把本报告变成自动跟随新 tag 的授权。
