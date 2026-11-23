# DeepSeek Harness Win7

**DeepSeek Harness Win7（DSH Win7）** 是 DeepSeek Harness 的非官方 Python 3.8.10 移植，面向 Windows 7 SP1 及更新的 Windows。它是可在项目目录中读取和编辑文件、运行 Shell 命令、保存会话的 AI 编程助手，提供桌面应用、Web GUI 和 CLI。项目以 Cordis 组织插件，Web 界面复用固定版本的上游前端。[DeepSeek Harness 上游项目](https://github.com/deepseek-ai/deepseek-harness)

**DeepSeek Harness Win7 (DSH Win7)** is an unofficial Python port of DeepSeek Harness for Windows 7 SP1 and newer. It includes a desktop app, a browser-based Web GUI, and a command-line interface. See the [English quick start](#english-quick-start).

[**下载正式版**](https://github.com/czh869452912/deepseek-harness-win7/releases/latest) · [试用 0.2.2 预览版](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/rc022-preview-20261123-r2-b0756568) · [源码运行](#源码运行) · [问题反馈](https://github.com/czh869452912/deepseek-harness-win7/issues)

## 下载和启动

首次使用可从 GitHub 标记的正式版下载。0.2.2 预览版适合试用新版桌面界面和迁移功能。每个发布页都列出了对应安装包、`SHA256SUMS.txt` 和验收范围。正式版 v0.1.5-rc.3-r3 的附件沿用了包含 `creative-preview` 的构建文件名。[正式版](https://github.com/czh869452912/deepseek-harness-win7/releases/latest) · [0.2.2 预览版](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/rc022-preview-20261123-r2-b0756568)

| 选择 | 下载后怎么用 |
| --- | --- |
| **Desktop Standard** | 已装齐系统前置组件时，下载对应架构的 `dsh-desktop-standard-setup-*.exe` 并启动应用。 |
| **Desktop AIO** | Win7 缺少前置组件时，下载 `dsh-desktop-aio-setup-*.exe` 离线补齐。遇到重启提示，重启后再运行同一个安装器。 |
| **Portable ZIP** | 下载 `dsh-win7-portable-*.zip` 并解压。包内自带 Python，运行 `dsh-web.bat` 打开 Web GUI，或在终端中运行 `dsh.bat`。 |

64 位系统通常选 **x64**，32 位系统选 **x86**。Windows 7 的安装前置条件及验证覆盖以所选发布页为准。[安装包与系统组件说明](docs/distribution.md#安装包选择)

### 配置模型并开始

在桌面或 Web 设置中配置模型提供商和 API Key，选择一个工作区即可开始。用户可使用 DeepSeek API，也可按提供商设置配置 OpenAI 兼容端点。通过终端启动时，可以在当前 PowerShell 会话中设置 DeepSeek 凭据。

```powershell
$env:DEEPSEEK_API_KEY = "your-api-key"
.\dsh-web.bat
```

浏览器未自动打开时，使用终端打印的本地地址。下面的 CLI 命令会执行一次任务。

```powershell
.\dsh.bat --profile headless "检查当前项目"
```

### 升级与已知问题

升级前退出 Desktop（包括托盘）、Web 和 CLI，备份整个 `DSH_HOME`（默认是用户目录下的 `.dsh`）及自定义会话目录。会话升级、压缩格式和回退步骤见[会话升级与恢复指南](docs/session-upgrade-recovery.md)。

Windows 工作区 ACL 继承问题可能使新建文件在关闭后无法读取。复现条件与进展见 [Issue #4](https://github.com/czh869452912/deepseek-harness-win7/issues/4)。0.2.2 预览版的剩余桌面交互和 Win7 验收项见 [Issue #11](https://github.com/czh869452912/deepseek-harness-win7/issues/11)。[已知差异](docs/known-differences.md) · [上游已知问题](docs/upstream-known-issues.md)

## 使用方式

- **Desktop / Web GUI** 提供工作区和会话管理、工具执行卡片、交互提问、权限确认以及计划和目标视图。
- **极简模式（Minimal）** 提供编辑器和持久 Shell。**标准模式（Standard）** 提供文件、搜索、Shell、技能、规划和子智能体等工程工具。
- **创造模式（Creative）** 支持创建和运行 Python 3.8.10 Host 插件与 JavaScript Client 插件。该模式的七个 Cordis 工具由本项目的 Creative profile 提供。[创造模式插件开发指南](docs/plugin-development-win7.md)

## English quick start

1. Open the latest full release and choose the x64 or x86 Desktop installer or Portable ZIP. Use Desktop Standard when prerequisites are installed. On Windows 7 SP1, Desktop AIO can install missing prerequisites offline. [Latest release](https://github.com/czh869452912/deepseek-harness-win7/releases/latest)
2. Open the Desktop app or extract the Portable ZIP and run `dsh-web.bat`. Configure a DeepSeek or OpenAI-compatible model provider, then open a workspace. For the CLI, set `DEEPSEEK_API_KEY` and run `dsh.bat --profile headless "Inspect this project"`.
3. Before upgrading, close all app instances and back up `DSH_HOME` and any custom session directories. Check the release notes for Windows 7 compatibility and verification details. [Release history](https://github.com/czh869452912/deepseek-harness-win7/releases) · [Known differences (中文)](docs/known-differences.md)

## 源码运行

使用 **Python 3.8.10**，并通过 Git submodule 检出固定的上游参考版本。已有工作树可在项目根目录执行 `git submodule update --init --recursive`。

```powershell
git clone --recurse-submodules https://github.com/czh869452912/deepseek-harness-win7.git
cd deepseek-harness-win7
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

设置模型凭据后，可在仓库根目录运行以下命令。

```powershell
.\.venv\Scripts\python.exe dsh.py --help
.\.venv\Scripts\python.exe dsh.py --profile web
.\.venv\Scripts\python.exe dsh.py --profile headless "检查当前项目"
```

用 `--patch <path>` 添加 profile 补丁，用 `--dump-config` 查看合成配置。需要在网页里选择目录时，可运行 `.\dsh.bat --profile web --patch examples/web-browse.patch.yml --no-open`，再用终端打印的地址打开 Web 界面。

## 架构与开发

Python Host、模型、工具、会话和 Web 载体均以插件挂载到 Cordis `Context`。插件通过 `inject` 声明服务依赖，通过 `effect` 注册卸载时的清理。Web 使用固定上游的 React 18 前端，客户端插件由实际启用的 Loader 条目决定。业务流使用 Connection / Typert Remote 与 `/api/remote.mux` WebSocket，`/plugins/events` 用于客户端热更新。

| 路径 | 内容 |
| --- | --- |
| `apps/` | CLI、Web 前端资源和 Desktop 应用 |
| `dsh/` | Python Host、Cordis、工具、会话和 profile 启动 |
| `packages/` | Cordis 插件、应用与预设组合 |
| `reference/` | 固定的 DeepSeek Harness 上游提交 |
| `scripts/`、`tests/` | 打包、发行验收和回归测试 |

源码环境可用 `.\.venv\Scripts\python.exe scripts\build_portable.py` 构建 Portable。桌面打包、x86 嵌入式运行时与离线组件输入见[分发与升级说明](docs/distribution.md#维护者构建)。

日常开发按改动范围选择定向测试。发行候选的完整门禁由 `scripts/verify_release.py` 执行，覆盖 Python 回归、固定上游、配对契约和实际分发包。临时工作区与日志使用独立的忽略目录，历史证据按发布资产索引按需核验。[开发指引](AGENTS.md) · [验证与证据管理](docs/testing.md) · [迁移记录](migration/README.md) · [Goose 多智能体操作指南](.goose/OPERATIONS.zh-CN.md) · [编排工作流](.goose/README.md)

## 许可证

上游采用 MIT 许可证，分发包中各第三方组件保留各自的许可证及来源记录。[上游许可证](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/LICENSE)
