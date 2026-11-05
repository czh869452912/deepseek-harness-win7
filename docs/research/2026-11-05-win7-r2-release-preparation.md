# Windows 分发修订版 r2 发行准备

本轮修复针对 Issue #6 后续反馈，在真实 Win7 SP1 x64 / PowerShell 2.0 / CLR2 中复现了 NSIS 输入管道的访问拒绝，并修复 PS2 脚本退出码及系统补丁退出码采集。真实 AIO 已完成五项补丁、两次重启、应用安装、Host/终端和 GUI 验证，详见[实测记录](2026-11-05-issue6-instance-check-diagnostics.md)。第三方机器唯一根因尚未直接确认，不通过 PR 自动关闭 issue。

用户授权提交、PR 合并主分支并发布新版。远端默认主分支是 `master`，本轮以此为目标；新增 `v0.1.5-rc.3-r2`，保留 r1 标签及产物。版本号同步到 Python、Portable 构建和 Desktop 元数据。冻结候选后使用 `scripts/verify_release.py` 完整门禁，不把旧 r1 资格或前次局部结果重标为新版本验收。

版本调整后的直接消费者检查第一次为 1 failed / 53 passed：失败发生于 ACL 夹具准备阶段的目录 rename，尚未调用产品脚本；原记录在 `.goose/out/issue6-r2-release/version-targeted.*`。改为在目标路径直接构造相同夹具，取消不必要的移动，保留真实拒绝及精确 SDDL 恢复断言。四个模块再次验证 54 passed / 20.19秒，记录 `version-fixed.*`。该测试调整不改变安装器产品输入。

后续完整验收、精确分发包、PR/合并提交及 Release 身份以发行回执记录为准；本文件不预先宣称发布完成。
