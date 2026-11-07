# rc.3 分发与升级

产品目标为 dsh-v0.1.5-rc.3，Python3.8.10、Windows7 SP1 及以上；桌面壳固定 Electron22.3.27。当前资格以迁移台账中绑定的提交、SHA 和回执为准。现代 Windows 上的运行结果不能代替 Win7 实机、系统补丁和重启验收。

当前精确交付位于 [v0.1.5-rc.3 Release](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/v0.1.5-rc.3) 和本机 [dist/dsh-v0.1.5-rc.3-6cbcbf1c-qualified](../dist/dsh-v0.1.5-rc.3-6cbcbf1c-qualified/)，包含两份 Portable、四份 Standard/AIO 安装器和独立离线组件 ZIP，附 SHA256SUMS 与 manifest。这些文件从已验证源逐字节复制，没有重建。包内文档保留构建时的冻结快照；当前验收状态以[发布说明](releases/v0.1.5-rc.3.md)和正式回执为准。x64 单次完整门禁、x86 独立包内验收和六组实际管理员安装生命周期分别保留范围；查看[正式回执](../migration/evidence/RUN-RC3-DESKTOP-COMPLETION-20261018-6CBCBF1C.json)。2026-10-20 用户确认已完成导入 Win7 测试、未观察到问题并授权发布；[反馈记录](../migration/evidence/HANDOFF-WIN7-RELEASE-20261020-6CBCBF1C.json)不补造未提供的系统补丁/重启、架构和浏览器逐项结果。

2026-11-07 新增[创造模式 Pre-release](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/creative-preview-20261107)，同样提供七件完整分发套装；[发布说明](releases/creative-preview-20261107.md)列出下载文件、SHA 与独立验收范围。产品冻结在 `e6443396`，包内版本仍为 `0.1.5-rc.3-r2`，请用预览标签和 SHA 区分旧正式发行。当前补件验收在现代 Windows 完成，不继承旧包的 Win7 系统组件/重启资格。

## 用户升级与数据

合格候选 `6cbcbf1c` 在默认会话配置没有显式压缩选项时，让 canonical CLI/Web 和 Desktop 共用默认目录的历史编码保留策略：已有单一明文历史沿用 `none`，新目录继续使用 zstd。Minimal 本身显式使用 none，继续遵循其配置。自定义根目录和显式配置须选择匹配的 `compression: none` 或 `zstd`，混合编码不自动转换。若旧程序因该冲突无法启动，按[会话升级与恢复指南](session-upgrade-recovery.md)备份配置并选择匹配后端；本轮新候选的实际验收状态见[完成记录](research/2026-10-18-desktop-completion-validation.md)。

升级前退出主窗口和托盘，备份整个 DSH_HOME，以及 patch 配置到其他位置的 Session 存储根目录。未设置 DSH_HOME 时使用用户目录下的 `.dsh`。保留升级前程序，先用备份副本试运行；不要让新旧程序同时打开同一存储。

新程序按原版目录布局写 v3 JSONL。旧日志只读时转换而不发布，写打开才验证并发布 `session.v3.jsonl.zstd`（或显式明文配置下的 `session.v3.jsonl`），旧代际保留。更高/损坏代际不会静默回退到旧文件。压缩和明文必须使用匹配的配置及独立根目录，不能通过改后缀转换。旧私有 SQLite 可通过既有只读导出入口迁出，不是当前 canonical 存储。

rc.1 不能读取新增 v3 数据。需要回退时退出新程序，恢复升级前的整个配置与存储备份，再运行原版本；只替换 EXE、删除最新代际或覆盖原目录都不能保证保留升级后的对话。安装器升级/卸载保留 DSH_HOME；卸载只移除仍与自有清单哈希一致的安装文件，用户新增和修改文件会保留。

## 安装包选择

| 载体 | 用途 |
|---|---|
| x64 Standard | x64 Windows，安装应用，缺少系统组件时提供离线升级指南。 |
| x86 Standard | 32位 Windows，或在 x64 Windows 上运行32位应用。 |
| x64 / x86 AIO | 离线携带所需微软组件；x86 应用在 x64 OS 上选择 x64 系统补丁。 |
| `dsh-win7-offline-upgrade.zip` | 独立环境升级工具，供 Standard 使用，不包含桌面应用。 |

运行安装器需要管理员权限。AIO 只在 Win7 安装适用组件：先处理 SSU / SHA-2，再处理 D3DCompiler47、.NET4.7.2 和 WMF5.1。遇到需要重启即停止后续步骤；重启后再次运行同一安装器。已有 WMF3.0 时按微软指南先移除，不自动卸载。安装目录保留版本隔离；升级前退出应用，安装器不会强杀正在运行的客户端。

Standard 不修改系统补丁。应用内可关闭的环境提示及安装完成页提供本地指南。默认只创建主应用和卸载的开始菜单入口。更新通道未配置时保持空闲；维护者可按[内网更新指南](desktop-lan-updates.md)提供 HTTPS 地址、Ed25519 公钥及可选的私有 CA 配置，下载验证通过后交给完整 Standard 安装器处理，不使用 Electron44 更新通道。

## 维护者构建

前置组件必须放在仓库外。以下变量由维护者填写，不应把私有绝对路径提交到源码：

```powershell
$prerequisiteInputs = '<仓库外的组件目录>'
.venv/Scripts/python.exe scripts/windows_prerequisites.py --output-dir $prerequisiteInputs --architecture both
.venv/Scripts/python.exe scripts/windows_prerequisites.py --output-dir $prerequisiteInputs --architecture both --verify-only
.venv/Scripts/python.exe scripts/build_windows_upgrade.py --external-prereq-dir $prerequisiteInputs --architecture both --output-dir .goose/out/offline-upgrade-candidate
.venv/Scripts/python.exe scripts/build_portable.py --output-dir .goose/out/portable-candidate
.venv/Scripts/python.exe scripts/build_desktop.py --edition both --architecture x64 --portable-dir .goose/out/portable-candidate/dsh-win7-portable --external-prereq-dir $prerequisiteInputs --output-dir .goose/out/desktop-x64-candidate
```

Electron 和 NSIS 输入使用 `scripts/desktop-tool-inputs.json` 的固定文件与哈希，可通过 `--electron-archive` / `--nsis-archive` 指定已下载的归档。x86 使用 `scripts/x86-inputs.json` 及 `prepare_x86_runtime.py` 准备实际32位运行时；以 `build_portable.py --architecture x86 --python-runtime ... --site-packages ... --output-dir ...` 构建，再向桌面构建器传入对应 `--portable-dir` 和 ia32 Electron 归档。不能用 x64 Python 或任意同名 wheel 替代。

所有输出目录必须新建；构建器先验证固定输入、Portable 与当前源码一致，以及真实内置 Node16/Python 的通信，再编译 NSIS。`desktop-build.json` 记录产物 SHA、架构、来源和前检；`installationExecuted: false` 明确表示尚未执行安装。完整统一资格使用 `scripts/verify_release.py`，Standard/AIO 的实际安装、断网、重启和卸载另留回执。
