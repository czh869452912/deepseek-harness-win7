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

后续继续设置及完整应用组合；最终资格使用 C9 冻结候选的完整门禁。
