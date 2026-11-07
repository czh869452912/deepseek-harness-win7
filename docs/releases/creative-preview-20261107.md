# 创造模式预览版 · 2026-11-07

面向 dsh-win7 的 Python 3.8.10 插件开发预览版，已补齐与之前 Release 相同的七件分发包。固定上游为 `a4c74a91e06b00fe0b0937bde982170c526cc842`。

独立 **Pre-release** 标签 `creative-preview-20261107` 指向通过统一验收的提交 `e64433966650fa0257af4f243bcf22c2a0f06f7d`；既有 r2 正式发行保持不变。

## 本次更新

- 创造模式技能与工具说明对齐原版工作流，指导开发针对 dsh-win7 的 Python 插件，保留原版浏览器 Client 用法。
- 修复技能相对路径、审批后重复附着，以及 Python 异常调用栈和异常链诊断。
- 定义阶段检查 Host / Client 语法，修复函数体编译语境及已发现的正则语法接受差异。
- 初始同步求值支持强制超时，避免原生阻塞拖住主事件循环；默认资源操作通过 Context 服务取得。
- 补齐跨进程取消、冻结 JSON、迭代、深层数据和卸载清理，以及随包技能与参考资源。

## 下载与升级

| 用途 | 64 位 Windows | 32 位 Windows |
| --- | --- | --- |
| Portable | `dsh-win7-portable-creative-preview-20261107-x64.zip` | `dsh-win7-portable-creative-preview-20261107-x86.zip` |
| Desktop Standard | `dsh-desktop-standard-setup-creative-preview-20261107-x64.exe` | `dsh-desktop-standard-setup-creative-preview-20261107-x86.exe` |
| Desktop AIO | `dsh-desktop-aio-setup-creative-preview-20261107-x64.exe` | `dsh-desktop-aio-setup-creative-preview-20261107-x86.exe` |

独立离线组件包为 `dsh-win7-offline-upgrade.zip`，同时包含 x86/x64 系统组件，供 Standard 等载体使用。Standard 安装应用；AIO 在 Win7 上按需安装缺失组件，遇到重启要求后请重启并再次运行同一安装器。x86 应用运行在 x64 系统上时仍选择 x64 系统补丁。

Portable 解压到新目录后使用 `dsh.bat --profile creative`，Web 入口为 `dsh-web.bat`。包内包含 Python 运行时，无须安装 Node 或 TS 工具链。升级前保存工作，退出对应应用和托盘，并备份 `DSH_HOME` 及自定义会话目录。尚未配置公开自动更新服务，请手动下载升级。

**版本识别：** 本预览各应用包内部仍显示 `0.1.5-rc.3-r2`，请使用预览标签、提交和 SHA-256 区分既有 r2 正式发行包。x64 Portable 保留原合格 ZIP 字节；新增包也从同一冻结产品提交构建，仅外部文件名使用预览标签。桌面安装器使用不同应用代，已检查从现有 r2 的实际升级。

所有下载文件以本页附带的 `SHA256SUMS.txt`、`release-manifest.json` 和 `release-verification.json` 为准。另有原完整门禁证据 `CREATIVE-CLOSEOUT-20261107-E6443396.zip` 和本轮补件证据 `creative-preview-distribution-evidence.zip`，均不是运行所需文件。

## 验证范围

原精确 x64 Portable 的单次完整门禁为 **19,481 passed、6 skipped**，3,939 项必需 lane、21 组固定 Source 配置、82 个配对驱动及实际解压后的现代浏览器 / Chromium 108 检查通过，108 的 Minimal、Standard、Creative 均覆盖首次启动和冷启动。

补件验收独立记录：实际 x86 Portable 的包内运行时及现代浏览器 / Chromium 108 × 三预设的六组首次启动和冷启动；四份桌面包的实际内置 Node16/Python 通信；六组管理员安装、Standard 从 r2 升级、发布失败回滚、普通用户 GUI 首次启动和冷启动、卸载及用户文件保留；独立离线组件 ZIP 的固定输入和逐成员字节检查。安装检查结束后恢复原机器注册表及快捷方式。各范围保留独立回执，没有把局部结果合并为新的全套通过。

补件检查首次运行曾在 x86 创造模式等待审批按钮处超时；同包诊断旅程及后续原脚本整组六组随后通过，原始超时尚未确定原因。安装验收外层观察器曾因等待人工 UAC 超时，获准后由新观察器接续同一管理员进程完成六组原检查。原失败及诊断观察器自身错误均保留在补件证据中，不改写为通过。

当前候选没有新增 Win7 SP1 真机或客体补丁/重启验收，不继承旧 r2 的对应资格。任意第三方服务 ABI 和全部 JavaScript 语法仍不属于已认证范围，不能宣称所有分支一比一等价。原完整门禁证据保留 694 份根级报告并明确省略 21 个嵌套目录；补件证据同样省略可重建运行时和私有 home，逐文件清单可核查。详见[创造模式收尾记录](https://github.com/czh869452912/deepseek-harness-win7/blob/master/docs/research/2026-11-07-creative-closeout.md)。
