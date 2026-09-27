# 本批次交付与边界

用户已删除旧发行目录与 ZIP；本批次从 a7e65ba9 的产品代码重建，新包包含 Python 3.8.10、固定 @vscode/ripgrep-win32-x64@1.18.0、框架、Web 静态资源与客户端包。双启动器仅调用相邻 python.exe。构建时工作树有迁移记录修改，来源文件摘要已核对包内 dsh 文件，没有冒充 clean build。

当前 Windows：五个 profile 隔离 dump-config、真实空 profile boot/shutdown 均通过。完整 pytest 为 2989 passed、2 skipped、2 warnings。警告及服务器断连诊断保留在原始日志中。Win7 SP1/浏览器按用户明确要求暂缓，发行文件名不构成平台认证。

跨盘搜索修复保留异卷绝对路径，与 Node Windows path.relative 语义对齐。旧基线三个失败已经消除；历史证据保留原结果。

Cordis 61/62 源码探针对齐，C58 原生 await 调度差异保留；C59 是显式 checkpoint 适配。所有已实施 HMR、Preset 和 profile 恢复工作都有单独提交，但完整必要消费者逐项审核尚未完成。不得把本批次成功回归当成全范围 1:1 认证。
