# Windows 分发修订版 r2 发行准备

本轮修复针对 Issue #6 后续反馈，在真实 Win7 SP1 x64 / PowerShell 2.0 / CLR2 中复现了 NSIS 输入管道的访问拒绝，并修复 PS2 脚本退出码及系统补丁退出码采集。真实 AIO 已完成五项补丁、两次重启、应用安装、Host/终端和 GUI 验证，详见[实测记录](2026-11-05-issue6-instance-check-diagnostics.md)。第三方机器唯一根因尚未直接确认，不通过 PR 自动关闭 issue。

用户授权提交、PR 合并主分支并发布新版。远端默认主分支是 `master`，本轮以此为目标；新增 `v0.1.5-rc.3-r2`，保留 r1 标签及产物。版本号同步到 Python、Portable 构建和 Desktop 元数据。冻结候选后使用 `scripts/verify_release.py` 完整门禁，不把旧 r1 资格或前次局部结果重标为新版本验收。

版本调整后的直接消费者检查第一次为 1 failed / 53 passed：失败发生于 ACL 夹具准备阶段的目录 rename，尚未调用产品脚本；原记录在 `.goose/out/issue6-r2-release/version-targeted.*`。改为在目标路径直接构造相同夹具，取消不必要的移动，保留真实拒绝及精确 SDDL 恢复断言。四个模块再次验证 54 passed / 20.19秒，记录 `version-fixed.*`。该测试调整不改变安装器产品输入。

后续完整验收、精确分发包、PR/合并提交及 Release 身份以发行回执记录为准；本文件不预先宣称发布完成。

## 发行准备中的实际观察

候选 `6cb10c26` 的四个 Desktop 包完成实际包内通信检查，x86 Portable 六组现代/108三预设 fresh/cold 旅程通过，六条管理员安装、r1到r2升级、回滚、普通用户启动及卸载流程全部通过并恢复原状态。同候选真实 r2 x64 AIO（SHA-256 `5b8a11256a2a32d6d8dabb562c9e74aad4273520dd210ea41c31e0e803a32902`）在 Win7 基线三轮返回3010、3010、0，两次重启后9项通信、5项终端、GUI、重复安装及载荷核对通过，正常关机，记录 `.goose/out/issue6-r2-release/win7-receipt.json`。这些是该候选和该包的结果，不自动授予后续包完整资格。

首次完整门禁在 JavaScript workflow 配对观察器 runner-error 停止，4,156 passed / 1 skipped / 1 failed，保留 `gate-6cb10c26/`。原测试临时目录已自动清理，尚不能直接确定内部原因；独立34项配对、原失败用例和直接消费者87项复验通过（597.30秒），未放宽超时或忽略断言。云端运行42040408675在既有 DeepSeek HTTP-400 夹具3000ms超时失败，原诊断另存 `ci-42040408675/`，不与本地JavaScript失败混为一项。

第二次门禁 `gate-6cb10c26-b/` 因发现 README 仍将r1标为当前版本、Win7实测描述过时而中止。准备停止时仍在 Portable 构建，实际终止前已进入早期pytest；没有最终XML或回归通过结论，`aborted.json` 更正了阶段，保留工作区映射。补齐发行文档后重新冻结最终候选并构建验收；未完成运行不能拼成最终完整通过。
