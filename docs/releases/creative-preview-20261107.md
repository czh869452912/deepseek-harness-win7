# 创造模式预览版 · 2026-11-07

面向 dsh-win7 的 Python 3.8.10 插件开发预览版，包含近期创造模式审查与收尾修复。固定上游仍为 `a4c74a91e06b00fe0b0937bde982170c526cc842`。

这是独立的 **Pre-release**：标签为 `creative-preview-20261107`，指向实际通过统一验收的提交 `e64433966650fa0257af4f243bcf22c2a0f06f7d`。

## 本次更新

- 创造模式技能与工具说明对齐原版工作流，指导开发针对 dsh-win7 的 Python 插件，保留原版浏览器 Client 用法。
- 修复技能相对路径、审批后重复附着，以及 Python 异常调用栈和异常链诊断。
- 定义阶段检查 Host / Client 语法，修复函数体编译语境及已发现的正则语法接受差异。
- 初始同步求值支持强制超时，避免原生阻塞拖住主事件循环；收窄默认 Host 能力，资源操作通过 Context 服务取得。
- 补齐跨进程取消、冻结 JSON、迭代、深层数据和卸载清理，以及随包技能与参考资源。

## 下载与使用

[预发布下载页](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/creative-preview-20261107)

下载 `dsh-win7-portable-creative-preview-20261107-x64.zip`，解压到新目录后运行 `dsh.bat --profile creative`；Web 入口为 `dsh-web.bat`。包内包含 Python 运行时，无须安装 Node 或 TS 工具链。已有用户请先保存工作、退出对应应用并备份 `DSH_HOME`。

**身份说明：** 下载文件是已验收 ZIP 的逐字节副本，仅更改外部文件名。包内版本号仍显示 `0.1.5-rc.3-r2`，与既有 r2 正式发行包不是同一产物；请使用本页标签、提交和 SHA-256 识别本预览。没有修改内部版本后沿用旧验收。

Portable SHA-256：

```text
416cae0b53914daf4c1cb62e10d5ee957f9b4a2c05620510c3f430216ebb5dcb
```

随附 `SHA256SUMS.txt`、`release-manifest.json`、`release-verification.json` 和 `CREATIVE-CLOSEOUT-20261107-E6443396.zip`。后者是验收证据，不是运行所需文件。

## 验收与限制

复用本次精确候选已经完成的单次 `scripts/verify_release.py` 统一门禁：**19,481 passed、6 skipped**，3,939 项必需 lane、21 组固定 Source 配置、82 个配对驱动，以及实际解压 x64 Portable / 现代浏览器 / Chromium 108 均通过；108 的 Minimal、Standard、Creative 均覆盖 fresh / cold。发布时再次核对原始回执、产物哈希与远端资产，未重新构建或拼接多轮局部结果。

本预览仅提供本轮完整验收的 **x64 Portable**；不附带本轮未经完整发行验收的 x86 或 Desktop 安装包。当前候选的 Win7 SP1 真机、任意第三方服务 ABI 和全部 JavaScript 语法仍不属于已认证范围，不能据此宣称所有分支一比一等价。证据包保留 694 份根级报告，21 个嵌套工作目录显式省略；详见其清单和[收尾记录](https://github.com/czh869452912/deepseek-harness-win7/blob/a8ce73e7/docs/research/2026-11-07-creative-closeout.md)。

既有 [r2 正式发行](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/v0.1.5-rc.3-r2)继续保留；本预览不替换正式版或继承其 Win7 / Desktop 资格。
