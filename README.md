# DeepSeek Harness Win7

> **此分支是未接受的 ACL 候选方案。** 包含启动预检和独立宿主恢复工具，供后续重设计评审；预检仍可能拒绝全部 pwsh 请求，无法保证既有受损文件可用。实现、配对例外及测试记录均不表示 master 已修复，见[候选设计](docs/research/2026-10-21-windows-acl-materialization-design.md)与[恢复限制](docs/research/2026-10-21-windows-acl-recovery.md)。

> 2026-10-21 已确认 Windows 工作区 ACL 继承问题：固定原版与未修复迁移版均可能出现新文件写完后不可读。**master 尚未合入修复，已发布版本未修复此项**；当前候选设计未获接受，单独提交 PR 讨论。见 [issue #4](https://github.com/czh869452912/deepseek-harness-win7/issues/4)、[问题分析](docs/research/2026-10-21-workspace-acl-mechanism-assessment.md)、[原版已知问题](docs/upstream-known-issues.md)及[已知差异](docs/known-differences.md)。

开发维护：[Goose 多智能体操作指南](.goose/OPERATIONS.zh-CN.md) · [编排工作流参考](.goose/README.md)

[README.md](README.md) | [AGENTS.md](AGENTS.md)

当前上游目标为 **dsh-v0.1.5-rc.3**（`a4c74a91e06b00fe0b0937bde982170c526cc842`），产品版本 **0.1.5-rc.3**。冻结候选 **`6cbcbf1c`** 完成单次干净当前 Windows x64 发行门禁：Python 19,367 通过/6 跳过、21 组固定 Source、82 个配对驱动及实际解压 Portable/现代和108浏览器验收全部通过。已有明文历史的启动恢复已推广到 canonical CLI/Web 和 Desktop。x86 Portable 另有实际解压及双浏览器三预设 fresh/cold 验证；x86/x64 Standard 全新安装、旧版覆盖升级及 AIO 全新安装共六组管理员旅程全部通过，包含失败回滚、普通用户运行、卸载保留用户文件和独立系统恢复核对。两种架构 CLI 及 x64 包内原版 Desktop 已完成真实 DeepSeek 消息、读文件工具和冷恢复。

下载 [v0.1.5-rc.3 Release](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/v0.1.5-rc.3) 的七份精确产物；此前无法启动的 x64 安装版可用其中 Standard 安装器覆盖修复。详见[发布说明](docs/releases/v0.1.5-rc.3.md)、[正式回执](migration/evidence/RUN-RC3-DESKTOP-COMPLETION-20261018-6CBCBF1C.json)、[完成记录](docs/research/2026-10-18-desktop-completion-validation.md)和[迁移台账](migration/README.md)。原版界面完成120视图/60对控件比较，仍披露原生控件约2 CSS px及既定Win7分发行为差异。2026-10-20 用户确认导入 Win7 测试未观察到问题并授权发布，见[原始反馈](migration/evidence/HANDOFF-WIN7-RELEASE-20261020-6CBCBF1C.json)；未提供的系统补丁/重启、位数和浏览器矩阵不据此扩写。内网真实更新服务器发布待用户设施就绪，本机私有CA/签名/下载及同份安装器安装已验证。既有精确 Source 例外、C58调度差异和任意插件ABI范围不扩张，`accepted_upstream` 保持 null；旧228cfacc资格保留历史身份。

规范 JSONL 默认写 `session.v3.jsonl.zstd`；明文配置写 `session.v3.jsonl`，逻辑导出仍为 `session.jsonl`。历史代际只读时在内存转换，写打开时验证并发布新代际，保留旧文件。已有明文根目录可显式配置 `compression: none`；canonical CLI/Web 和 Desktop 对未显式设置压缩的默认目录沿用已有单一明文编码；自定义目录及显式配置仍须匹配后端。同一根目录不能混用两种压缩格式。升级前停止应用并备份整个 DSH_HOME 及自定义存储根目录；rc.1 不能读取新写的 v3 历史，回退应恢复升级前的完整备份，不能仅换回旧程序。旧私有 SQLite 仍由显式只读 reader 导出。见 [分发与升级说明](docs/distribution.md)。

> 2026-09-29 历史 Web 验收：原版前端与本地模拟模型完成创建工作区、对话、工具执行、恢复、反馈、分支和导出。该记录没有执行 Web 真实模型或 Win7 真机验收；本轮真实 DeepSeek 观察范围为包内 CLI 和 x64 Desktop，见上方最终记录。完整上游 parity 仍受已披露边界约束。见 [Web 验收记录](docs/research/2026-09-29-web-usable-baseline.md)。历史审查见 [当前状态审查](docs/research/2026-09-28-current-state-mvp-audit.md) 和 [入口切换实施记录](docs/research/2026-09-28-canonical-entry-progress.md)。CLI 已统一到正式 profile 入口，旧 CLI 分流不再保留。

**DeepSeek Harness Win7** 是面向 Windows 7 及以上系统的开源 Agent Harness（智能体框架）Python 迁移工程，目标包含 **Cordis in Browser + React 18 + TSX + CSS Modules** Web GUI 与正式 profile CLI。正式 Web 路径采用 Connection / Typert Remote 与 WebSocket 流。

本项目基于 **Python 3.8.10**，忠实复刻了 DeepSeek Harness 原生的 **Cordis（万物皆插件）** 架构。项目的核心目标是：
1. **Windows 7 兼容目标**：使用 Python 3.8.10；当前 Windows 回归不能替代 Win7 真机认证。
2. **极简模式与创造模式**：支持原生 DeepSeek Harness 的双关键模式（Minimal & Creative Presets）。
3. **1:1 官方 Web GUI**：复用固定上游的 Cordis in Browser 前端，Client 插件由实际启用的 Loader 配置派生。
4. **零依赖 Portable Release**：提供脱离 Python 全局环境依赖的开箱即用便携版。

---

## 核心架构 (Cordis Architecture)

本项目遵循 Cordis 的核心设计理念：**“产品的每一部分都是插件”**。

```
                    +------------------------------------+
                    |    Context (ctx Service Container) |
                    +-----------------+------------------+
                                      |
         +----------------------------+----------------------------+
         |                            |                            |
  [ctx.llm]                    [ctx.tools]                  [ctx.sessions]
  OpenAI / DeepSeek API         Tool Catalog                 Append-only Event Log
         |                            |                            |
  [ctx.fs]                     [ctx.terminal]               [ctx.agent_loop]
  Local Workspace FS           Persistent PowerShell        Turn & Step Loop
         |                            |                            |
  [ctx.web_server]             [ctx.client_modules]         [ctx.connection]
  HTTP / WebSocket             Client Bundle Registry       Typert Remote / Fetch
```

- **上下文容器 (`Context`)**：服务（Service）统一绑在 `ctx` 上，插件之间通过 Key 进行依赖查找而非强耦合导入。
- **依赖声明 (`inject`)**：插件通过 `inject` 字段声明所需服务，等待服务就绪后触发 `apply(ctx)`。
- **可逆副作用 (`effect`)**：所有的工具注册、事件监听均注册为可撤销 effect，插件卸载/重载时自动清理资源。
- **正式浏览器协议**：Connection → Typert Gateway → Remote，业务流走 `/api/remote.mux` WebSocket；`/plugins/events` 是客户端 HMR SSE。旧 ApiProxy、双业务 SSE 和 `/api/respond` 已退休。

---

## 启动 Web

配置模型凭据后，在仓库目录运行：

```powershell
.\dsh-web.bat
```

打开终端打印的带一次性 token 的地址。无法操作系统目录选择框时，可使用原版网页目录选择器：

```powershell
.\dsh.bat --profile web --patch examples/web-browse.patch.yml --no-open
```

该补丁只改变插件装配，不修改原版前端。测试演示使用隔离的 DSH_HOME 和本地模拟模型；它不是生产模型配置。

设置中的“插件列表”显示宿主 Loader 条目。原版默认关闭宿主 HMR，Web 的多数模型工具由会话预设按需挂载，因此宿主同名工具显示“已停用”不代表会话缺少工具；浏览器 `client-hmr` 是另一条独立启用的插件。“插件配置”只显示已注册设置且提供原版配置卡片的插件，不是所有插件的配置编辑器。设置目录、模型提供方和预设工具的验证见 [设置专项验收](docs/research/2026-09-30-web-settings-acceptance.md)。更新代码后需要重启 Web 服务再刷新页面。

## Web GUI (Cordis in Browser)

Web 端基于官方 **React 18 + TSX + CSS Modules** 架构，使用浏览器端 Cordis 微内核实现动态插件插拔：

- **官方 Client 插件组合**：`ui-layout`、`ui-sidebar`、`ui-conversation`、`ui-composer`、`ui-user-questions`、`ui-permission-presets`、`ui-goal`、`ui-plan`、`ui-trajectory`、`ui-settings` 等，以固定上游 bundle 和实际启用条目为准。
- **三栏响应式布局 (`AppFrame`)**：侧边栏工作区树、中央对话流、右侧轨迹与性能指标折叠栏。
- **丰富的交互视图**：
  - **ReasoningRow**：DeepSeek R1 / V3 深度思考折叠卡与实时打字机输出。
  - **Tool Cards**：`str_replace_editor` 差异比对卡、PowerShell 终端卡、目录搜索卡。
  - **User Questions**：交互式问答弹窗（单选/多选/自定义输入/分页）。
  - **Permission Approval**：敏感工具执行单次放行 / 拒绝审批流。
  - **Goal CAS Bar**：带乐观锁版本校验的多轮目标看板。

---

## 快速开始

### 获取 reference 参考仓库

本项目通过 Git submodule 固定官方 DeepSeek Harness reference 版本。首次克隆时请初始化 submodule：

```powershell
git clone --recurse-submodules <项目地址>
```

已有工作树可执行：

```powershell
git submodule update --init --recursive
```

不要在 `reference` 目录内自行切换到其他提交；官方参考版本由外层仓库的 submodule 提交锁定。

### 1. 源码运行

1. 克隆仓库并使用 Python 3.8.10 安装依赖：
   ```powershell
   git clone https://github.com/deepseek-ai/deepseek-harness-win7.git
   cd deepseek-harness-win7

   # 创建虚拟环境
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. 设置 API Key 与 Base URL：
   ```powershell
   $env:DEEPSEEK_API_KEY="your-api-key"
   $env:DEEPSEEK_BASE_URL="https://api.deepseek.com" # 或 OpenAI 兼容 Endpoint
   ```

3. 正式入口语法（默认组合的可用性以产品验收为准）：
   ```powershell
   # 查看启动器帮助
   .venv\Scripts\python.exe dsh.py --help

   # Web profile
   .venv\Scripts\python.exe dsh.py --profile web

   # 单次任务：应用读取任务位置参数
   .venv\Scripts\python.exe dsh.py --profile headless "检查当前项目"

   # 查看组合配置，不代表完成实际启动验收
   .venv\Scripts\python.exe dsh.py --profile headless --dump-config
   ```

`--mode`、`-m`、`--prompt`、`-p`、`--web` 和无参数交互回退已移除。
模型、端点等配置由 profile patch、settings 和 credentials 服务提供；启动器不再通过这些参数切换旧运行时。

---

## 便携版构建 (Portable Release)

[v0.1.2 Portable](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/v0.1.2) 对齐 `dsh-v0.1.2-rc.1`，包含文件引用及原子写失败诊断、保守清理保护。解压 ZIP 后运行 `dsh.bat` 或 `dsh-web.bat`。用户已确认包含 ACL 加固的新 Portable 在 Win7 下复验可用；这是用户实际测试反馈，完整自动化发行结果及对应 ZIP 的 SHA-256 以发行页和原始验收回执为准。ACL 明确拒绝的目录仍需维护者修正权限，程序不会自动提权或重置 ACL。

项目支持一键打成无环境依赖的 Windows 7 便携版：

```powershell
.venv\Scripts\python.exe scripts\build_portable.py
```

当前构建产物放置在 `dist/dsh-win7-portable/` 并打包为 `dist/dsh-win7-portable-v0.1.5-rc.3.zip`：
- 双击 **`dsh-web.bat`**：一键启动 Web GUI 并在浏览器中打开。
- **`dsh.bat --profile headless "任务"`**：通过正式入口执行单次任务。

桌面版采用 Electron22.3.27 与内置 Python3.8.10，分别构建 x64/x86 的 Standard 和 AIO 安装包。Standard 不安装系统补丁；AIO 按实际缺失项使用离线微软组件，必要时先重启、再运行同一安装器。独立环境升级 ZIP 和构建命令见 [分发与升级说明](docs/distribution.md)。安装包编译、解包运行和真实管理员安装分别验收。

---

## 单元与集成测试

日常开发默认运行原失败用例、修改模块及直接消费者的定向测试。例如，修改 SDK 等待逻辑时：
```powershell
.venv\Scripts\python.exe -m pytest tests/test_sdk_stdio_wait.py --durations=20
```
定向验证通过后，只有新变更、失败或未覆盖风险才扩测。提交、合并、push 和普通任务收尾本身不要求重跑完整集合或重新打包。文档修改通常只需检查差异和链接。

完整测试安排在稳定迁移批次统一签收、跨模块架构改造整体收尾、Portable 发布候选冻结或用户明确要求时。正式统一验收使用 `scripts/verify_release.py`，它已包含全量 pytest、固定原版配置、配对及实际解压/浏览器验证，不应在它之前重复执行一次 `pytest tests`。

如果任务目标只是独立的完整 Python 回归，可运行 `.venv\Scripts\python.exe -m pytest tests`，但这不等于发行验收。完整门禁失败后先保留材料、集中修复并定向复验，下一稳定候选再安排完整门禁；不在每修一项后自动重跑。

测试数量和结果以当前检出的实际运行日志为准。局部通过不证明全量或发行通过，历史通过记录不证明新默认 profile 或 Web 协议已经完成迁移。节点规划和产物保留规则见 [验证指南](docs/testing.md) 和 [agent 开发指引](AGENTS.md#5-verification--testing)。

---

## 目录结构

```text
deepseek-harness-win7/
├── apps/
│   ├── cli/                  # CLI 入口实现
│   └── web/                  # 官方 React 18 Web 前端 SPA (dist)
├── packages/
│   └── client/               # 原版 Client 模块，按实际 Loader 组合派生
├── dsh/
│   ├── cordis/               # Cordis 核心微内核 (Context, EventBus, Plugin, Loader)
│   ├── core/                 # 核心 Agent 循环、Surface 投影与 Session 存储
│   ├── host/                 # WebServer、Connection、ClientModules、Remote 与 Desktop 载体
│   ├── fs/                   # 文件系统与 str_replace_editor 工具
│   ├── shell/                # pwsh / cmd 持久化终端工具
│   ├── llm/                  # OpenAI / DeepSeek API 驱动与 TokenMeter
│   ├── goal/                 # CAS 目标服务与工具
│   ├── plan/                 # Plan 模式控制器
│   └── boot/                 # canonical profile 解析、组合与启动
├── scripts/                  # 便携版构建与自动化打包脚本
├── tests/                    # pytest 自动化测试套件
├── dsh.py                    # 主 CLI / Web 启动入口
├── dsh.bat                   # 便携版 CLI 批处理启动脚本
├── dsh-web.bat               # 便携版 Web 批处理启动脚本
├── AGENTS.md                 # 开发与架构规范文档
└── README.md                 # 项目说明文档
```

---

## 许可证

[上游 MIT 许可证](reference/LICENSE)；分发内各第三方组件保留各自的许可证与来源记录。
