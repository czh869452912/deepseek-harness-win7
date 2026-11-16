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

后续继续设置及完整应用组合；最终资格使用 C9 冻结候选的完整门禁。
