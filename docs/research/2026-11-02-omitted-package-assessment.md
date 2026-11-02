# 目前省略的包是否需要补全

日期：2026-11-02。当前上游基线：`dsh-v0.1.5-rc.3 / a4c74a91`；拟选目标：`dsh-v0.2.1-rc.5 / b830ec95`。
范围：当前能力清单、Python 注册表/实现、历史有限证据和固定目标源码的静态审查。本文不实施补包、不提升迁移状态。

## 1. 判断

**有必要补齐实际能力缺口；没有必要把当前未单独注册的包全部照搬。**

建议保持 [rc.5 选型](2026-11-02-upstream-target-selection-assessment.md)，把后续工作分为：

1. **P0：目标实际启用链路的完整合同。** 默认组合、原样 Web UI 和已承诺的 Python 插件交付流程所需能力必须提供；平台替代要记录差异，不能用空类或仅存在的 manifest 宣称完成。
2. **P1：独立、有明确增益的可选能力。** 首选 LSP 三包闭包；再考虑 Worktree 与进程外 SDK 子代理。先做依赖/平台样机，通过后单独验收，不强制增加 Minimal 或普通 Portable 的依赖。
3. **P2 或保持省略：按真实需求选择集成。** 云搜索、Webhook、外部 CLI、语音、徽章等不作为本轮全体补齐目标。旧包已经退出目标时，按新合同迁移其必要职责。

“包全部有对应 Python 类”不是合适的完成标准。更合适的标准是：**选定产品能力可实际运行，依赖明确、卸载可逆、旧数据可恢复，并有范围准确的证据。**

## 2. 当前究竟省略了多少

当前 [rc.3 能力矩阵](../../migration/rc3-capabilities.json) 有297份 manifest、199个 Loader 入口，176个 manifest owner 拥有入口。剩余121个 owner 的分类为：

| 分类 | 无独立 Python Loader 入口的 owner 数 | 应如何解释 |
| --- | ---: | --- |
| runtime | 89 | 混合了接口库、启动器、组合包、工具库与可选功能，必须继续拆分。 |
| frontend | 8 | 包含原样编译资源/浏览器库、官网及可选 Team UI，不能一律要求 Python 插件。 |
| platform | 8 | 包含外平台二进制与 Win32 适配职责，不能一律照搬。 |
| tooling | 9 | 构建、生成器和测试支持；按验证/构建需要保留。 |
| fixture | 7 | 测试夹具，不应作为目标机功能补齐。 |

完整121行筛查及固定 rc.5 profile 的保守依赖图见[结构化审查表](2026-11-02-omitted-package-review.json)。这些数量只是静态筛查口径，不是“121个未实现包”，也不是正式省略政策。旧报告的“254包、163已迁移、91缺失”不能继续用作待办。

其中56行被标为 `audit-owner-contract`：它们没有独立 Loader 条目，需在所属合同内核对实现和消费者；本次没有逐一取得这些 owner 的新运行资格，不能把它们全算作完成，也不能全算作缺失。当前 `accepted_upstream` 仍为 null。

## 3. 先校正容易重复立项的项目

| 旧清单容易产生的判断 | 当前源码/记录及处理 |
| --- | --- |
| 文件引用两包仍待实现 | `file-reference-local` 已有正式绑定，抽象 `file-reference` 没有独立 Loader 不构成功能缺失；已有提供端、Remote、浏览器与冷恢复记录。按 rc.5 新工作目录语义复验，不重新开发旧缺口。 |
| 通用 JS 工作流仍不可执行 | Windows canonical boot 已挂载 `JavaScriptRuntime`，`WorkflowEngine` 消费 `jsRuntime`，有私有 QuickJS worker 及配对记录。保留其有限引擎差异和新版本适配任务，不能继续沿用9月“尚未实现”的结论。 |
| 终端/Bash 包未补，所以终端不可用 | 已有 `terminal-bash` 到本机终端实现的绑定、终端服务和持久 PowerShell。模型控制的六个 `terminal_*` 工具则是另一项可选能力，不能与侧栏终端混同。 |
| Agent Teams 完全没有实现 | 已有本机 `dsh.team` 和原生名称绑定；原版 experimental 包名、组合、UI 与新 Inbox 语义仍需单独核对。现有类和测试不能认证整个原版 Team bundle。 |
| `sandbox-windows-acl` / `win32-process` 无 Loader，所以缺失 | Win32/沙箱能力由平台实现及上层 provider 承担，应核对权限、失败、进程回收和消费者，而不是添加同名空插件。 |
| 必须新增所有接口库和微包 | Session format、授权、fs/jobs、atomic-write、Cordis 等已有所属领域实现；以公共行为及服务生命周期验收，保留动态插件实际需要的可发现接口。 |

参考：[rc.1 行动校正](2026-10-14-rc1-baseline-and-capability-action-plan.md)、[JS 工作流接续](2026-10-05-js-workflow-progress.md)、[当前注册表](../../dsh/boot/plugin_registry.py)、[canonical boot](../../dsh/boot/app_boot.py)。这些历史运行证据不自动认证 rc.5。

## 4. 值得补齐的能力与优先级

以下为工程建议，P1/P2不自动变成本轮发行阻塞；如被选定 profile 的实际启用路径直接依赖，应按该合同提升优先级。

| 能力 / 包族 | 必要性与收益 | 成本/边界 | 建议 |
| --- | --- | --- | --- |
| **LSP：`dsh-lsp`、`dsh-lsp-stdio`、`dsh-tool-lsp`** | 对大型工程、同名符号及影响分析有直接价值，是当前最明确的可选开发能力缺口。 | 中等；Python Host 可实现协议，但语言服务器可执行文件须另证 Win7/Python3.8/位数可用。 | **P1第一项，完整实现 seam→stdio→tool。** 不默认安装现代 Node。 |
| **Worktree：experimental worktree / tool-worktree** | 隔离 Agent 的代码修改，适合创造插件、并行任务和试验。属于 rc.5 新增范围，不是当前 rc.3 的旧遗漏。 | 中等；共享Git管理目录、切换cwd、权限、取消残留、已有分支都需处理。 | **P1第二项，保持可选。** 在 working-directory 与沙箱合同稳定后做。 |
| **`subagent-dsh-sdk`** | 让子任务用独立进程/profile运行，能隔离进程内插件状态。 | 中等至高；已有 SDK/ACP 接口不等于该 provider 已实现，需进程树、取消、隔离home和恢复闭包。 | **P1第三项。** 先说明哪些任务确实需要隔离；普通委派继续使用已有进程内后端。 |
| **Session 数据诊断** | 有助于定位v4迁移、历史/投影及原样聊天显示问题，维护收益明确。 | 低至中等，取决于现有 Remote 接口；与 Node Host DevTools 是两项能力。 | **P1开发辅助候选。** 优先复用目标 session-inspector 原样客户端，验证其所需服务。 |
| Exa / Perplexity | 可提供搜索供应商选择及不同结果形态。 | 低至中等；需要外部凭据、网络与实际端点证据，维护额外错误方言。 | **P2，按用户已有服务选一个。** 先完成目标 DeepSeek Search/Fetch。 |
| 模型终端六工具 | 对REPL、调试器及连续交互有独立价值；不是持久shell的完全同义项。 | 中等；所有者隔离、发送/读/信号、后台job及Win7终端语义。 | **P2，出现交互需求再补。** 不阻塞普通shell路径。 |
| Agent Team 原版bundle/UI | 团队任务板和显式消息协作可能有价值。 | 高；本机已有能力与原版接口需要辨别，rc.5消息规则变化，持久化/恢复/UI需联合验收。 | **P2独立批次。** 共享Inbox/子代理合同若为默认链路所需，先在P0闭合。 |
| Webhook / GitHub事件 / CLI hooks | 适合实际代码托管事件唤醒与外部工具协作。 | 中等；鉴权、重放、排空、持久化和可访问部署都有成本。 | **P2，明确事件源及部署后实施。** 本机聊天不因未挂载而缺功能。 |
| `storage-sqlite` | 提供另一种通用存储后端；不能与已有Session查询SQLite、旧会话SQLite reader混为一谈。 | 中等；所有权、事务、恢复和格式兼容。 | **暂缓。** 只有明确持久化/部署收益才补，不为包数增加第二后端。 |

LSP的固定源码将其定义为供模型使用的只读定义、引用、实现及hover导航，并非Web编辑器自动补全；服务器也不由stdio包安装。见[上游工具规范](https://github.com/deepseek-ai/deepseek-harness/blob/b830ec950faba0a46dda564be3e2d854afed94f1/packages/lsp/tool-lsp/README.zh.md)。验收应包括UTF-16坐标、Windows URI/中文路径、多工作区、修改后的文档同步、取消/超时及进程清理。没有可实际运行的服务器时，不能仅交付一个工具名称。

Worktree的[固定规范](https://github.com/deepseek-ai/deepseek-harness/blob/b830ec950faba0a46dda564be3e2d854afed94f1/packages/experimental/worktree/README.zh.md)从提交创建新checkout，不复制暂存/未暂存文件。补齐时必须保持这一行为，验证进入后文件工具、引用、shell、恢复都使用正确cwd；不能为其扩大沙箱授权。

## 5. 建议继续省略或采用替代的范围

| 范围 | 建议及原因 |
| --- | --- |
| E2B三包 | rc.5最终tree已没有 `dsh-e2b/fs-e2b/subprocess-e2b` 同名manifest。不要复活旧包作为升级前置；若有云沙箱需求另行选接口。E2B本身不是天然与Win7互斥。 |
| 旧code-runtime/worker-thread与Python实验入口 | rc.5改为PTC runtime等结构。迁移必要执行合同并保持Python适配，避免恢复过时名称；已有QuickJS工作流也不等于支持任意Node插件或Node内置模块。 |
| 外部Claude Code/Codex子代理与Mods | 在没有可支持的目标机运行时或远端部署前保持可选/延期。适配协议和安装可执行程序是两件事，不能增加默认Win7启动依赖。 |
| Node Host inspector | 不为Python Host模拟Node debugger。会话日志诊断、浏览器Client检查与Python Host诊断分别按实际价值提供。 |
| WebWorker runtime/packer | 浏览器执行原型不属于目前核心Host目标，继续延期；必要构建工具仍可存在构建机。 |
| Bash、tmux及Linux/macOS原生包 | 保留PowerShell/cmd及现有条件化实现；`tmux-context`已有绑定，不应再列为“完全没有移植”。不为Win7发行加入外平台二进制。用户另装Bash的支持需单独界定。 |
| badge / all-prompts-title、语音、翻译等 | 按明确用户体验需求启用，保持开销和外部依赖可选。改标题策略不必承担完整新能力线。 |
| UI微包、fixtures、官网和测试kit | 原样浏览器打包、构建与验证各自消费，不为每一项增加Python Loader入口。 |

## 6. 本轮必须防止“继续省略”的新目标合同

不能把所有新增包都归为可选。固定rc.5的profile/patch静态依赖图已出现 `plugin-manager`、`plugin-market`、`api-remote-access`、`session-format-v3-to-v4`、`working-directory`、preset registry等新职责。它们是否需要独立插件取决于目标服务和装配方式，但对应行为必须闭合。

具体应纳入rc.5主线审查：

- 插件索引/安装/兼容性/热替换的真实Host服务，衔接本机Python交付；不承诺任意npm Host插件可执行。
- Session v4、Peer方法权限、投影/历史/恢复、工作目录与preset生命周期。
- 已选native/PTC路径、调度、MCP资源和SDK消费者的依赖。静态出现PTC Node行不自动允许目标机依赖现代Node；不可用路径须有明确overlay及能力说明。
- Office/外部运行时按需获取与分发策略，不让Python3.8目标误装不兼容依赖；Minimal继续保留既定双工具差异。

本次依赖图包含字面量声明及条件禁用行；“可达”只说明必须审查，不能证明实际激活，“未发现可达”也不能证明永远可省略。最终以正式启动的有效Loader、服务和原样浏览器旅程判定。

## 7. 实施建议与完成边界

**不建议先补完旧省略包、再启动版本迁移。** 先推进rc.5默认合同与旧数据闭包；LSP可在接口稳定后作为第一个独立增益批次，Worktree与SDK进程外后端随后按需求安排。这样可以避免将已退役包迁移到旧接口后再重做。

每个获选能力应具备：明确provider/consumer、配置及可选依赖、目标OS/位数、取消和卸载路径、失败可诊断性、实际使用旅程及冷恢复证据。当前已有类/测试的项目先审核证据缺口；没有用户价值或依赖义务的包保持省略，并记录原因和替代。

本次检查完整121行筛查覆盖、候选manifest身份、JSON/链接及diff；不运行pytest或Portable构建，因为没有改运行时代码。本次未新增任何能力的通过声明。

沿用上一轮发现的reference checkout与生产台账不一致现状，读取上游均明确指定SHA。另实际尝试现有 `candidate_inventory.py`：系统Python缺少yaml；项目venv可加载依赖，但旧profile语法解析器拒绝rc.5已变化的模板。两个失败已登记在结构化表；后续改用本次局部只读提取器审查明确字面量模板，不修改正式发现器、不把失败改为通过。正式迁移S0应升级发现器并验证新语法及拒绝控制。
