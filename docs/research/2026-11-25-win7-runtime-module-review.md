# Issue 13 Win7 全模块运行时性能审查

审查日期为 2026-11-25。固定原版为 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`，原版检出的已跟踪文件保持干净。Win7 变更基线为 `199ef548`，前一阶段先提交了会话和终端调整。下文以当前 Canonical profiles 的插件、消费方、启动和持久化路径为准。测试在本机 Windows x64、CPython 3.8.10 运行。Source 配对使用 Node 24.9.0，并单独对实际 Electron 22 和 Chromium 108 的适配路径取证。 [固定原版](https://github.com/deepseek-ai/deepseek-harness/tree/38a6a5c965aa99ab525161efb7cc5cf1fe62fced) · [前一阶段传输审查](2026-11-25-win7-runtime-transport-performance-audit.md)

## 已提交的优化及实测

| 提交 | 路径与结果 |
| --- | --- |
| `d948525c` | 会话 JSONL 冷扫减少字节复制，终端小页按需要复制滚屏缓冲。详见前一阶段传输审查。 |
| `c94907c9` | 兼容 JSON 的常见数据走 C 编码器，特殊 JS 值保留兼容转换。复用 WebSocket 文本的已编码字节，保留 UTF-16 阈值。约 318 KiB 的 JSON 从约 50.0 ms 降至 9.8 ms，660 kB 文本帧从约 2.17 ms 降至 0.91 ms。 |
| `2e34e8bf` | Desktop 私有 v3 管道协商逐响应流信用额度，每流最多四个在途数据帧。一个 4 MiB 响应暂停消费 200 ms 时，独立小请求由 204.5–209.4 ms 降至 1.4–1.8 ms。实际 Electron 22 验证了信用路径和旧载体回退。 |
| `85eb30a1` | HMR 配置路径复用一次 stat，保持同尺寸同时间戳改动可见。递归扫描复用 `DirEntry` 元数据。2,048 文件的目录快照中位时间由 70.55 ms 降至 11.57 ms。 |
| `3f3e2200` | Web 对消息边界可靠且请求体完整消费的 HTTP/1.1 请求复用连接。TCP 断开通知由事件触发。180 次本机回环请求由 180 条连接降至 1 条，P95 由 23.85 ms 降至 0.32 ms。 |
| `de031d42` | WinPTY 正常使用 Proactor 等待进程句柄。保留其他事件循环的有界轮询和 Job 后代进程检查。 |
| `fb771c50` | Office 浏览器载体解析后释放原始 JSON 缓冲，逐项用解码值替换 Base64 字符串。8 个 4 MiB 合成附件的解码后跟踪分配由 74.68 MiB 降至 32.01 MiB。两侧跟踪峰值均为 85.34 MiB。 |
| `27e5fa96` | 完整缓冲的 gzip HTTP/1.1 响应用分块帧标记边界，并复用连接。现有 SSE 和已发送头部的流式路径继续按原帧规则处理。 |
| `fa378d03` | Desktop 启动文档、注入脚本和静态资源的读取移出 Python Host 事件循环。 |
| `505829de` | FS 单文件监听仅查询父目录和目标路径，保留删除后重建和原子替换观察。目录监听仍取目录快照。 |
| `e88057d5` | Settings 内部修订扫描直接使用 Loader 条目。受控表单夹具的完整配置读取由 18 次降至 7 次，11 项 Source 配对观察一致。 |
| `f1fc50fd` | Web gzip 对至少 256 KiB 的压缩输入使用执行器。4 MiB 合成文本在级别 6 的同机复测中，排队回调等待中位数由 122.91 ms 降至 0.86 ms，响应完成时间由 122.87 ms 增至 199.34 ms。另一次以级别 1、先执行修改版的测量得到 117.68 → 0.65 ms 和 117.62 → 106.24 ms。结果反映事件循环阻塞与响应耗时的不同指标。 |
| `1e8ffd3c` | 四项只读 Web 设置断言共享一次 Canonical Web 启动和 Remote 读取，仍分别验证并报告。原先四项合计约 24 秒，共用夹具后单跑四项用时 8.25 秒，JUnit 中的四个测试 ID 一致。 |

这些数字来自表内明确的本机负载，测量项包括 Python 修改前后对照、回环传输和受控夹具。端到端性能还受工作区体量、压缩级别和渲染负载影响。

## 模块核对

盘点覆盖 `dsh/` 下 50 个目录、1,148 个 Python 文件及 266 个 Harness Loader 绑定。对照依据包括固定原版包名、Win7 绑定和实际调用路径。先查找重复文件访问、轮询、全量解码、子进程和事件循环执行器，再核对激活中的入口及消费者。配对报告、真实载体用例和热点基准各自绑定到观察范围。

| 模块 | 对照路径及处理 |
| --- | --- |
| `acp` | 原版 ACP server 的初始化、请求排队和 session 事件转发对应 Native ACP 路径。本地回归覆盖 stdio 生命周期和独立会话。 |
| `api` | Session、Settings、Workspace、Terminal 经 Connection/Typert 转发。会话投影分页和终端增量页已减少重复构造，RPC 二进制 multipart 仍为整包组装。 |
| `attachment` | 核对原版本地附件存储的写入和引用时序。Native 分离磁盘操作及 Host 事件循环，定向回归覆盖附件身份、读取与路径。 |
| `boot` | 对照原版 app-boot/config-editor 的 Profile 解析、启动、修订和生效顺序。Canonical Loader 与 HMR 是持续运行成本的主要交点，HMR 去掉重复文件查询。 |
| `bundle` | 核对原版 base、web、headless 等包的组成与 Native Loader 绑定。Native Creative 的本地管理工具明确属于本地组合。运行中的业务 I/O 由插件持有。 |
| `client` | 原版浏览器程序保留固定构建。Native 提供 Host 服务、静态资源、注入及客户端模块基线。Desktop 静态读取移出 Host 循环。旧 Chromium 布局兼容脚本仍有待真实页面测量。 |
| `code_runtime` | 对照原版 tool-executor-ptc 的调用和生命周期。Native 使用受约束的独立进程和控制通道，退出及取消路径保留进程所有权。 |
| `compaction` | 对照摘要、旧工具结果修剪和图像转移。现有触发边界限制遍历及模型请求频率，定向回归覆盖 compaction 决策与载荷。 |
| `context` | 对照原版 instructions、file-reference、session-reference 和 time-context。文件探测与内容读取按实际使用发生。独立磁盘及 subprocess 适配仍按归属隔离。 |
| `cordis` | 对照原版 Loader、Fiber、事件和 HMR watcher。与原版 Chokidar 相比，Native HMR 仍有轮询，当前优化已降低单轮磁盘调用。HMR 写入配对通过。 |
| `core` | 对照 agent、scope、agent-loop、tool executor 和 system prompt 的服务分层。保留同步事件、串行钩子及有序并行工具的边界。定向回归覆盖工具管线。 |
| `credentials` | 对照写入、Provider、认证及事件边界。定向覆盖账号信息、脱敏及状态持久化，状态与密钥的存储归属保持分离。 |
| `deliverables` | 对照工具产物、文件引用和工作区变更。Native 通过执行器完成磁盘复核，工作区视图保留变更与发布边界。 |
| `diagnostics` | 核对 invariant 注册、状态观察和 disposal。当前入口随对应诊断插件挂载，观察成本出现在被订阅事件与生命周期转换。 |
| `extensions` | 对照原版插件检查、安装及 inventory。已加载项目从 Loader 条目取值，导入、安装和卸载有独立生命周期。大型清单及首次安装尚无端到端性能量化。 |
| `feedback` | 对照原版 command/message feedback 的会话事件与持久化。Native 根据反馈事件恢复当前反馈项，保留顺序和同一对象的后续编辑，已有反馈回归。 |
| `fs` | 对照原版 fs-local 路径、监听与本地变更语义。Native 精确文件监听跳过兄弟目录项，创建、修改、删除及归属的配对观察一致。目录监听仍按快照轮询。 |
| `goal` | 对照目标工具、回合驱动和 session 事件。Native 目标状态随会话更新，定向验证覆盖重复触发与终态。 |
| `guard` | 对照超时策略和重复工具提醒。Native 在工具执行边界维护各 agent 状态，定向测试覆盖超时、提醒及清理。 |
| `host` | 对照原版 WebServer、FrontendStatic、Connection 和 Desktop 宿主。完成 HTTP 连接复用、事件驱动断开、大 gzip 移出循环、Desktop 独立响应回压和静态资源读取。 |
| `identity` | 核对匿名 ID、系统身份和不变量插件。Native 持久身份读取属于初始化路径，系统用户查询按调用者获取。 |
| `interaction` | 对照问题、确认和交互路由的 Remote 事件。保留顺序及回答、取消生命周期，批量队列行为归入 Typert 流审查。 |
| `javascript` | Native JS 工具负责外部运行时和模块定位。固定原版 Node 运行时直接载入模块。进程探测和工具安装路径在定向回归内验证。 |
| `jobs` | 对照 jobs-local 与工具服务的作业状态、子进程与输出。Native 按 job 持有进程和取消生命周期。 |
| `llm` | 原版使用异步 Fetch，Native 以阻塞 HTTP 线程和异步单槽缓冲交付模型流，另有取消检查。线程和 wakeup 是已识别的平台适配开销，缺少相同并发及 token 帧分布的对照。 |
| `mcp` | 对照 SDK 的请求相关、通知、协商和响应缓存。16 项配对观察覆盖 TTL、显式刷新、分页和通知代数，定向用例覆盖 stdio 协商。 |
| `office` | 原版 Office Kit 按 slot 复用 converter。Native 浏览器回退按转换启动，已优化 Base64 结果驻留。冷启动、载体体积和两侧 converter 复用边界仍有差异。 |
| `plan` | 对照原版 Plan Mode 的 scope 与工具准入。定向回归覆盖许可与退出模式，状态匹配发生在执行工具前。 |
| `presets` | 按原版 minimal、standard profile 所选 provider 和工具目录核对。不同 preset 的活跃成本取决于对应组合，Native Creative 另有本地开发生命周期。 |
| `resources` | 静态资源目录。相关读盘与启动开销计入 boot、client、Office 和 skill 的实际消费方。 |
| `sandbox` | 对照策略分发、本地访问和 Windows ACL。Native 的 ACL 子进程成本取决于命令和缓存命中，回归覆盖策略范围与执行入口。 |
| `schedule` | 对照调度器时钟、CAS 和持久化。Native 保留 deadline 与串行一致性边界，26 项配对观察通过。 |
| `sdk` | 原版以 Node stdin 事件接收帧。Native 对继承的同步管道使用 `PeekNamedPipe` 和 10 ms 空闲轮询，保证卸载时可撤掉读取且保留 launcher 所有的句柄。 |
| `session` | 对照 JSONL 读写、会话投影、冷读验证、分页及修订缓存。已减少扫描复制和常用 JSON 编码开销。原版迁移验证有 Worker 隔离，Native 仍需测量大历史的解压、解析、回包及渲染各段。 |
| `settings` | 原版描述、表单编辑和冲突检测共用完整描述生成。Native 已让内部修订刷新避开 Profile 文件重读和表单值投影。生命周期和表单配对合计 24 项观察通过。 |
| `shell` | 对照持久 shell、执行和回收。Native PowerShell 会话保留状态，核对真实调用、取消及退出。 |
| `skill` | 对照技能发现、工具、Office skill 和 workspace dependencies。发现及文件 I/O 跟随已挂载的 provider 与工作区，定向验证技能装载和 catalog。 |
| `skills` | 托管技能资源目录。运行时成本计入 skill 服务及被调用的工具。 |
| `spill` | 对照原版按策略把大输出落盘。保留限额、引用和工具输出语义，定向回归覆盖 spill 与 policy。 |
| `storage` | 对照本地存储、版本原子写入与 cleanup。Native 写入部分借助执行器，保留关闭、修订和原子发布边界。 |
| `subagent` | 对照原版 SDK、ACP、子代理取消与继续。Native 进程启动依赖所选 provider，定向覆盖传播、重新接入和嵌套取消。 |
| `subprocess` | 原版 Node subprocess/PTY 与 Native WinPTY/asyncio 在 Windows 句柄上不同。Native 正常路径改用 IOCP 退出通知，现有回归覆盖后代回收。 |
| `team` | 对照原版团队操作、成员和队列语义。13 项配对观察验证现场状态、持久化及 CAS。 |
| `terminal` | 对照原版增量屏幕、滚屏和退出保留。Native 小页只复制所需历史，WinPTY 正常退出改为事件等待。 |
| `todo` | 对照原版 todo 的 scoped 工具和会话状态更新。处理量随本次条目数变化，现有工具与作用域回归覆盖其入口。 |
| `typert` | 对照原版 Remote/mux 的帧、序列化、取消和会话。已缩短编码并削减复制。大 WebSocket 帧的 deflate 仍占用 Host 循环，多订阅积压涉及流内顺序和交付合同。 |
| `util` | 核对被运行时选用的锁、原子写入与异步帮助函数。性能结论随消费者验证，原子写入、锁争用与取消释放的观察单独保留。 |
| `web` | 核对原版 Web Fetch、消息搜索及 API provider 的流和取消边界。入站 GUI 的连接与 gzip 成本由 host/connection 路径承担，工具 Fetch 仍依平台及服务端而变化。 |
| `workflow` | 对照原版编排、PTC 和工具调用边界。核对事件顺序、命令注册和运行归属。配套用例覆盖 workflow binding 和 engine。 |
| `workspace` | 对照原版注册表、文件发布和搜索。19 项 Source 搜索观察零差异，含 Unicode。安装在深临时目录命中一次 Windows 重命名 `EACCES`，同一组六项使用短自有路径重跑全部通过。 |

[Win7 Loader 绑定](../../dsh/boot/plugin_registry.py) · [原版包目录](https://github.com/deepseek-ai/deepseek-harness/tree/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages) · [原版 Cordis](https://github.com/deepseek-ai/deepseek-harness/tree/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/vendor/cordis)

## 验证结果

- 兼容编码、Gateway、mux 和会话相关定向运行共 946 项通过，另做了 5,000 组 JSON 差分。
- 本轮拆分验证包括 Desktop 114 项、HMR 104 项、HTTP 59 项、gzip 41 项与执行器改动 20 项、WinPTY 18 项、Office 29 项、FS 38 项、短路径工作区安装 6 项及 Settings 27 项。Windows 真实载体覆盖 Electron 22、Chromium 108、WinPTY 和 PowerShell。共享测试夹具的后续验证覆盖六项 Web 用例和 16 项门禁身份校验。
- 另外两批分别通过 233 和 252 项跨模块定向用例，覆盖实际消费者和邻接模块。各运行存在重复用例。
- 八组 Source/Native 配对通过，分别为 FS watch 5 项、HMR writes 9 项、MCP cache 16 项、Schedule runtime 26 项、Settings lifecycle 13 项、Settings forms 11 项、Team service 13 项和 Workspace search 19 项。
- 测试日志、JUnit、配对 JSON、计时脚本及复测记录留在自有忽略目录 `.goose/out/runtime-module-review-2fcc522a/`。包含真实 Remote 或 Web 启动的设置批次耗时约 72 秒，文件监听与事件子集约 3 秒。涉及真实安装与复制的复测使用短工作区。 [本地运行与短工作区说明](../testing.md#输出保留与清理)
- 已清理本次自有 pytest 工作区和配对夹具，包括短系统临时目录，移除 882 个链接和约 32.3 MiB 的普通文件数据，保留失败与复测的原始观察及清理回执。保留材料用于下次稳定候选验证时复查。
- `scripts/migration.py check` 与 `ready` 已运行，验证范围为当前索引和 checkout。验收索引保持原有证据状态。CI 和 Linux 配置沿用此次任务的低优先级，Win7 SP1 真机、x86 完整回归和发行验收需要各自的运行证据。

## 尚需目标环境数据的差异

| 场景 | 当前差异及验证边界 |
| --- | --- |
| 后台监听 | 精确文件监听与 HMR 已降低每轮操作数。切换 Windows 目录通知涉及原子替换、重挂载、目录树覆盖及同元数据修改的复核。SDK stdin 则涉及同步继承句柄的取消与移交。需要分别记录真正空闲进程的唤醒及故障恢复。 |
| Desktop 与 Web Remote | Desktop 的信用窗口解决同一管道的独立响应阻塞。完整双工仍受适配方式影响。Web 大帧压缩、订阅积压和 multipart 整包的性能数据需要与浏览器端消费及取消一起收集。 |
| 浏览器兼容 | 老 Chromium 的 DOM/CSS 兼容层有独立于 Host RPC 的成本。须绑定页面及真实渲染事件观察，不能由回环 HTTP 数据推算。 |
| 模型和 Office | Python 模型 HTTP 线程桥、Office 浏览器按次启动和 Base64 传输仍与原版不同。已验证 Office 解码后分配减少，载体峰值和多次转换耗时需要实测。 |
| 长会话 | 冷读恢复、视图构造、回包和旧浏览器首次或增量渲染需分别量化。当前本机基准只覆盖已提交的对应计算与传输段。 |

这些差异按已核对的调用路径记录。现有数据可复现本轮优化，表达的范围为实际运行的本机用例和配对观察。
