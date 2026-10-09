# DeepSeek Harness Win7

开发维护：[Goose 多智能体操作指南](.goose/OPERATIONS.zh-CN.md) · [编排工作流参考](.goose/README.md)

[README.md](README.md) | [AGENTS.md](AGENTS.md)

当前迁移验收：最新完整签收仍为干净产品 `83026446` 的65个有界范围。后续16项尚待统一闭环；干净 `fd2c3a9b` 第十二轮完整 Python **10488 passed、1失败、6既有skip**，原生文件替换1175使发行拒绝，后续Source/配对/解压未执行，原失败文件及精确证据已封存。完整回归改在仓库外执行，严格映射清理与原子保留已定向验证，生产替换语义不改，下一稳定候选另作同包完整验收。可重建测试副本及时清理，真实观察、失败与正式证据保留。详见 [迁移台账](migration/README.md) 和 [最新接续记录](docs/research/2026-10-10-external-regression-workspace-progress.md)。

规范 JSONL 与原版一致，默认写 `session.jsonl.zstd`，逻辑导出仍为 `session.jsonl`。已有 plaintext 根目录须显式配置 `compression: none`，或为默认压缩选择单独的 root；两种物理格式不能混用同一个 root，也不会静默转换已有日志。新提供端的完整发布验收仍在执行，见 [推进记录](docs/research/2026-10-05-jsonl-provider-progress.md)。

> Web 核心链路已通过原版前端与本地模拟模型验收（创建工作区、对话、工具执行、恢复、反馈、分支、导出）；完整上游 parity、真实模型和 Win7 真机验收仍未完成。见 [Web 验收记录](docs/research/2026-09-29-web-usable-baseline.md)。历史审查见 [当前状态审查](docs/research/2026-09-28-current-state-mvp-audit.md) 和 [入口切换实施记录](docs/research/2026-09-28-canonical-entry-progress.md)。CLI 已统一到正式 profile 入口，旧 CLI 分流不再保留。

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
  [ctx.web_server]             [ctx.client_modules]         [ctx.apiproxy]
  HTTP / SSE Gateway           CJS Bundle Registry          Dual Streams + RPC
```

- **上下文容器 (`Context`)**：服务（Service）统一绑在 `ctx` 上，插件之间通过 Key 进行依赖查找而非强耦合导入。
- **依赖声明 (`inject`)**：插件通过 `inject` 字段声明所需服务，等待服务就绪后触发 `apply(ctx)`。
- **可逆副作用 (`effect`)**：所有的工具注册、事件监听均注册为可撤销 effect，插件卸载/重载时自动清理资源。
- **旧兼容实现 (`ApiProxy`，不是固定上游的正式浏览器协议)**：正式路径需要迁移到 Connection → Gateway → Remote；下列旧路由仅存在于内部兼容代码；正式 Web profile 不使用它们。
  - `/api/events/mux`：分发增量 Token 流、问答请求 (`question/requested`)、审批请求 (`approval/requested`)、目标投影 (`session/projection`)。
  - `/api/events/host`：分发会话生命周期、多工作区状态与背景作业。
  - `POST /api/respond`：异步应答唤醒挂起的工具协程。

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

项目支持一键打成无环境依赖的 Windows 7 便携版：

```powershell
.venv\Scripts\python.exe scripts\build_portable.py
```

构建产物将放置在 `dist/dsh-win7-portable/` 并打包为 `dist/dsh-win7-portable-v0.1.0.zip`：
- 双击 **`dsh-web.bat`**：一键启动 Web GUI 并在浏览器中打开。
- **`dsh.bat --profile headless "任务"`**：通过正式入口执行单次任务。

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
│   └── client/               # 40 个官方 Client 模块与 CJS 动态 bundle
├── dsh/
│   ├── cordis/               # Cordis 核心微内核 (Context, EventBus, Plugin, Loader)
│   ├── core/                 # 核心 Agent 循环、Surface 投影与 Session 存储
│   ├── host/                 # Host 网关服务 (WebServer, ClientModules, ApiProxy, FrontendStatic)
│   ├── fs/                   # 文件系统与 str_replace_editor 工具
│   ├── shell/                # pwsh / cmd 持久化终端工具
│   ├── llm/                  # OpenAI / DeepSeek API 驱动与 TokenMeter
│   ├── goal/                 # CAS 目标服务与工具
│   ├── plan/                 # Plan 模式控制器
│   ├── presets/              # 预设配置 (minimal.yaml, standard.yaml, creative.yaml)
│   └── harness.py            # Harness 装配与启动器
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

[MIT](LICENSE)
