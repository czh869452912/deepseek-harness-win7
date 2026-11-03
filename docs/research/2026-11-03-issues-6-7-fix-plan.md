# Issues #6 / #7：分析、修复与验收计划

调查基线：`c7f9a8eb5c116b4dd0bd86b1b518dce582cebfe6`，2026-11-03。
工作分支：`codex/fix-win7-install-and-folder-dialog`。

## 现象与证据边界

- [#7](https://github.com/czh869452912/deepseek-harness-win7/issues/7)：Web 版选择工作区时，系统“浏览文件夹”窗口落在浏览器后面。报告者与维护者均观察到。
- [#6](https://github.com/czh869452912/deepseek-harness-win7/issues/6)：安装报错；维护者提供“后台实例未退出”和“升级 .NET / PowerShell 后恢复”两类现场线索。没有安装日志、错误截图、Standard/AIO 或系统架构信息，不能将所有现场失败归为同一个根因。

## #7：已确认的窗口层级缺陷

Python `NativeDirectoryPickerService` 在 Windows 上通过 `run_native` 启动 PowerShell STA 子进程；子进程使用 `CREATE_NO_WINDOW`，调用无显式 owner 的 `FolderBrowserDialog.ShowDialog()`。它与浏览器没有 owner 关系，也没有 topmost 层级保证。修改上游 TS 原生选择器不会修复实际执行的 Python 路径。

修复：在同一子进程中创建透明、无任务栏图标的临时 topmost WinForms owner，显示其 HWND 后调用 `ShowDialog(owner)`。正常选择/取消都在 finally 中释放窗口；请求中止仍走原有 kill/wait 路径。标准输出仍仅返回 UTF-8 路径，取消返回空值。

这采用 Win7 现有 WinForms API，不尝试把任意当前前台窗口强制变成浏览器 owner。临时 owner 和对话框只在选择期间置顶，不设置浏览器的全局置顶状态。

参考：[FolderBrowserDialog API](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.folderbrowserdialog)、[Windows owned/topmost windows](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features)。

## #6：实例占用、兼容性与误诊应分别处理

1. 运行中实例：`uninstall-files.ps1 -CheckOnly` 检测安装目录下的可执行进程，退出4。这是预期保护；退出窗口到托盘、关闭浏览器都不等于 Host 退出。保留拒绝及不杀进程行为，新增 PID/完整路径，避免建议用户终止所有 python.exe。
2. 误诊：NSIS 先运行上述脚本，再执行 prerequisite policy；原来任何非零结果（包括脚本异常、超时、PowerShell 无法启动）都提示关闭应用。现在仅4表示占用，其余错误明确提示检查失败、退出码、Details/日志以及独立离线升级入口。预检原文写入与补丁检查共享的临时日志。即使 AIO 尚未进入补丁阶段，也能明确指出独立恢复路径。
3. 旧 CLR 兼容：清单登记/清理使用 `$hash.Dispose()`，但公开的 `HashAlgorithm.Dispose()` 从 .NET Framework 4.0 才存在；stock Win7 的 PowerShell 2.0 使用旧 CLR，改用 `Clear()`。快捷方式路径也移除较新 CLR 的 `CommonStartMenu` 枚举依赖，改为已有 WScript.Shell 的 `AllUsersPrograms`。
4. Standard 的“不修改系统组件、允许环境能力受限”策略不变；AIO 继续按 SSU → SHA2 → D3D → .NET → WMF 顺序安装缺失组件，遇到重启立即停止。未把 PowerShell 5.1 设为 Standard 安装的强制门槛。

参考：[HashAlgorithm.Dispose 适用版本](https://learn.microsoft.com/dotnet/api/system.security.cryptography.hashalgorithm.dispose)、[SpecialFolder 的原始 API 版本记录](https://github.com/dotnet/dotnet-api-docs/blob/main/xml/System/Environment%2BSpecialFolder.xml)。旧 CLR 缺口与现场“升级后恢复”一致，但没有现场日志，不能确认它是报告者遇到的唯一失败点。

## 已完成的定向验证

运行环境：Windows 11、Windows PowerShell 5.1 / CLR4、CPython 3.8.20；不是 Win7 认证。

- 第一轮31项通过：安装清理、生成的卸载器登记、失败代回滚、篡改/未知用户文件保留、junction 拒绝、x86/x64 补丁选择与失败/重启边界、目录选择 RPC、原生子进程取消。
- 新增真实进程与窗口控制20项通过（与第一轮存在重叠，不相加）：运行目录内 Host 返回4并保留进程，兄弟目录进程不误拦截；真实 WinForms owner 和对话框都有 `WS_EX_TOPMOST`，取消和请求中止均回收子进程。
- 对原始 HEAD 选择器脚本执行同一真实窗口测试，两项均在 owner 非置顶处失败，证明回归测试能识别原缺陷。原始失败 XML：`.goose/out/issues-7-before.xml`；通过记录：`issues-6-7-initial.xml`、`issues-6-7-native.xml`。
- 最终合并范围35项通过，12.32秒；额外确认正常取消与请求中止后，dialog/owner HWND 都已销毁。命令：`.venv/Scripts/python.exe -m pytest tests/test_directory_picker_windows.py tests/test_desktop_packaging.py tests/test_desktop_prerequisite_flow.py tests/test_directory_picker_remote.py tests/test_native_command.py -q --junitxml=.goose/out/issues-6-7-final.xml`。
- 固定 NSIS 3.13，Standard/AIO × x86/x64 四种组合均编译退出0。只使用占位 payload 验证实际 NSIS 脚本编译，不执行安装，不是正式分发。结果和四份编译日志位于 `.goose/out/issues-6-nsis-smoke-verified/`。SourceForge 初次下载实际返回 HTML，被原有尺寸校验拒绝；后从 Chocolatey portable 包取得内嵌官方 ZIP，尺寸2363925，SHA256 `ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8`，与仓库固定清单完全匹配后才使用。原拒绝目录保留。

## 后续发行验收顺序

1. 源码定向收口：本次新增控制、目录选择直接消费者、安装/补丁现有回归，以及 Standard/AIO × x86/x64 的固定 NSIS 编译。编译夹具不能作为应用安装包交付。
2. Win7 SP1 快照矩阵：x86/x64 分别覆盖 stock PS2/.NET3.5、已升级 PS5.1/.NET4.7.2；Standard 全新安装/旧版覆盖/卸载；AIO 缺组件、WMF3、待重启、补丁失败和重启后再次运行。检查每一阶段实际退出码、用户数据与原安装代保留。
3. Win7 窗口矩阵：浏览器最大化/普通窗口、多屏、连续选择、OK/取消、浏览器断连取消；确认窗口可见、中文/含空格路径正确、无残留 owner 或 PowerShell。Win11 本次窗口测试不替代这一项。
4. 稳定候选冻结后按 `docs/testing.md` 执行一次完整 `scripts/verify_release.py` 门禁，并执行真实 Standard/AIO 管理员生命周期；资格绑定精确提交、输入和实际发行文件。未完成前不关闭 issue、不宣称新发行包已修复。

本次没有运行系统补丁、替换用户安装版本或修改 GitHub issue；没有把源码定向结果算作 Win7/完整发行验收。

## PR 前复核

2026-11-03 对照最新 `origin/master` 复核，基线仍为 `c7f9a8eb`，没有新增上游差异。实际比较 WScript `AllUsersPrograms` 与原 `CommonStartMenu/Programs` 的解析结果，二者一致。

窗口回归改为直接调用 `NativeDirectoryPickerService.pick_native`，覆盖服务分派、路径规范化和取消返回 `None`，并增加真实窗口“确定”选择中文/含空格目录。非交互式 Windows 会话明确跳过原生窗口测试，不能据此认定窗口验收通过。三种交互结束后都检查 dialog/owner HWND 销毁及子进程回收。

新增选择控制第一次错误地把测试进程内的字符串地址传给跨进程 `WM_USER` 消息，导致 chooser 子进程异常退出；这是测试驱动错误。修正为仅在本测试启动的 chooser 子进程内分配、写入及释放字符串，再同步发送选择消息；三项真实窗口检查通过。原失败记录保留为 `issues-6-7-pr-review.xml`、`issues-7-review-selection.xml`，修正后记录为 `issues-7-review-selection-fixed.xml`。

最终五模块定向复核36项通过，报告为 `.goose/out/issues-6-7-pr-reviewed.xml`；固定 NSIS 四组合编译结果仍适用于未再修改的安装脚本。Win7 真机、补丁重启和完整发行资格仍按上面的计划单独验收，PR 关联两项 issue 而不自动关闭。
