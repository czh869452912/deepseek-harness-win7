# 应用提供方与组合接入

固定目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。本页记录定向检查；生产 pin 和 `accepted_upstream` 尚未提升。

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
