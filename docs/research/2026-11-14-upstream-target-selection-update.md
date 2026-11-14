# 下一轮上游对齐目标复核

日期：2026-11-14（Asia/Shanghai）。检查工作区 HEAD：`0e86930b`。
性质：目标选型与实施入口确认，未切换生产基线或实施迁移。

## 决策

**建议下一轮以 `dsh-v0.2.2-rc.3` 为统一对齐终点，固定提交 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。第一批工作是 S0 兼容性探针与合同发现。**

本判断更新[11 月 2 日选型](2026-11-02-upstream-target-selection-assessment.md)中首选 `0.2.1-rc.5` 的建议。rc.5 保留为需要收缩范围时的备选，不安排中间版本逐个正式发行。整个开发周期以固定 rc.3 合同为准；后续新 tag 需另行评估。

目标选择与生产 pin 切换分开。当前正式台账/reference 仍为 `a4c74a91`，`accepted_upstream` 仍为 null。本次没有修改它们，也没有新增迁移签收。

## 判断依据及前次分析的变化

1. 11 月 2 日的暂缓对象是 `0.2.2-alpha.2`；此后上游已发布 rc.1（11 月 4 日）、rc.2（11 月 11 日）、rc.3（11 月 13 日）。均仍为 Pre-release，不能据 RC 名称推断稳定或兼容。
2. rc.1 汇总了插件更新及失败恢复、宿主级自动化、发送确认与草稿保留、历史会话修复，以及 Session/工具执行接口迁移。rc.2 继续统一具名多层子代理与 AgentTeam，增加动态 MCP 管理，并调整工具错误、Session 批量追加、Creator 文档和 Windows 额外目录授权范围。rc.3 补充 Windows 应用内更新修复与实验性 DeepSeek 会话导入。
3. 当前尚未正式启动 rc.5 迁移。现在直接针对 rc.3 迁移，可以减少在 rc.5 接口上完成 Session、子代理、工具、Loader 后再做第二轮接口改造的重复工作。这是工程取舍，不是已经证明新版本总成本更低。
4. [11 月 7 日创造模式收尾](2026-11-07-creative-closeout.md)已有 `e6443396` 的独立完整门禁与预览分发记录。新迁移应以当前产品实现为代码起点，保留其 Python Host/JS Client 适配；不再把这项工作列为未完成前置任务。新版 `dsh-doc` 则是新迁移合同，要重新适配，不能把旧技能直接复制后视为完成。

官方依据：[rc.1](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.1)、[rc.2](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.2)、[rc.3](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.2-rc.3)。Release API 和 tag REST API 交叉核对 rc.3 为上述 commit 对象；rc.5→rc.3 的 Compare API 返回 ahead 4,197、behind 0。提交数含合并，不是移植工作量。

## 固定源码核对与实际风险

下列路径均读取 rc.3 精确 SHA 的原始源码，未改 reference checkout：

| 固定源码 | 观察 | 对迁移的含义 |
| --- | --- | --- |
| `package.json` | Node `>=24.9.0`；pnpm `11.28.5` | 在现代构建机准备 Source 工具链；目标机 Python 3.8.10 的运行能力另验。 |
| `packages/session/session-format-catalog/src/generated.ts` | `currentVersion: 4` | 当前产品 v3→v4 仍是首要数据迁移；不能把 API 变化误称为新增 v5 格式。 |
| `apps/web/vite.config.ts` | `target: 'es2022'` | 不构成 Chromium108 的 Web API/CSS/依赖兼容证明。 |
| `apps/desktop/package.json` | Electron `^44.7.0` | 本产品 Electron22 外壳仍须单独适配和验收。 |
| `vendor/cordis` / `vendor/loader` / `vendor/include` 的 `package.json` | 4.1.0 / 1.1.0 / 1.1.0 | 以发布分支实际依赖为准；不要混入 master 的其他演进。 |
| `packages/subagent/subagent/src/types.ts` | 名称、父级路径、parent/caller delivery、interrupt authority | 子代理迁移包括身份、消息、权限与消费者，不能只增工具参数。 |

源码入口：[固定 tree](https://github.com/deepseek-ai/deepseek-harness/tree/38a6a5c965aa99ab525161efb7cc5cf1fe62fced)。本轮只核对关键文件与发布合同，没有完成整个 tree 的行为审计或新候选的 Source/native 配对。

旧报告列出的成本依然存在：Session 快照/事件/状态/投影订阅拆分、异步 projection 持有，按步工具准入、固定模型选择，native/PTC 执行拆分及取消分类，Cordis 配置和 Loader 持久化。进入 RC 没有消除这些成本。选择新终点的理由是一次完成最终合同及其修复，而非忽略它们。

## 下一步与完成判据

| 批次 | 范围与完成判据 |
| --- | --- |
| **S0：立即下一项** | 独立准备固定 rc.3 Source，升级候选发现器以处理新 profile 语法，列出默认组合真实 provider/consumer；构建原样 renderer，在 Chromium108/Electron22 验证关键启动、聊天/文件预览入口；用受控旧 v3 父子数据验证 v4 转换及保留策略；核对原样插件 UI 接入 Python Host 的协议可行性。所有失败须保留。 |
| S1：数据与协作 | Session v4 格式链、压缩/明文、继承坐标、批量追加、订阅及异步 projection；连同 Agent、具名多层子代理/Team、SDK、ACP、Remote 的恢复与取消消费者闭合。 |
| S2：运行时与协议 | Cordis/Fiber、Boot/Loader、依赖与热更新、Connection/Typert/方法权限、模型固定和 native/PTC 工具准入、错误与取消分类；覆盖失败、卸载与重连。 |
| S3：产品旅程 | 原样插件索引/管理/创造入口及 dsh-doc 的 Python 适配，模型/凭据/Search/Fetch、终端与自动化、Windows 安装升级；必要宿主合同不能因界面能显示而省略。 |
| S4：统一资格 | 已知问题与定向检查完成后冻结候选，执行一次 `scripts/verify_release.py`；按约定分别取得双架构 Portable、Desktop、旧数据及 Win7 资格，不拼接旧运行认证新产物。 |

S0 中 renderer 的静态启动不能替代新 Host 的端到端浏览器检查；v3→v4 的小样也不能替代完整数据链。若原样前端或必需合同在 Win7/Python3.8 边界不成立，先保留失败并重评范围，再决定是否启用 rc.5 备选，不静默修改上游浏览器业务代码。

范围继续遵循[省略包评估](2026-11-02-omitted-package-assessment.md)：先闭合有效默认组合和承诺能力，再独立考虑 LSP、Worktree 等可选闭包。DeepSeek 会话导入、Computer Use、Office、外部 CLI 不因出现在新发布中就全部成为默认移植承诺。若有效组合实际依赖其中的服务，则必须实现或明确审核产品 overlay，不能留空壳 provider。

Minimal 继续遵守既定双工具产品约定。Windows ACL issue #4 及 Win7 实际兼容性保持独立检查；新版授权范围说明不等于该问题已修复。

## 本次验证及资源处理

- `scripts/migration.py check` 和 `ready` 经项目 venv 执行，均退出 0。reference 当前已回到 `a4c74a91`，11 月 2 日记录的 checkout 错位不再是当前阻塞。
- 两个命令明确只核对索引与 checkout，未验证外部归档字节，不建立新的验收资格。
- 本轮仅更新分析文档；采用相对链接和 diff 检查，不运行 pytest、Source 构建、Portable 或完整门禁，不声称新增 Win7/浏览器资格。
- 网络结果只在进程内读取，没有新建下载归档、Source checkout、浏览器配置或测试夹具；本轮命令已结束，没有待清理的自有测试载荷。原有 `.gitignore` 用户修改保留。
