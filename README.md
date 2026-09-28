# DeepSeek Harness Win7

开发维护：[Goose 多智能体操作指南](.goose/OPERATIONS.zh-CN.md) · [编排工作流参考](.goose/README.md)

[README.md](README.md) | [AGENTS.md](AGENTS.md)

> 当前仍在迁移中，默认 profile 与完整 Web/portable 尚未通过产品验收。详见 [当前状态审查](docs/research/2026-09-28-current-state-mvp-audit.md) 和 [入口切换实施记录](docs/research/2026-09-28-canonical-entry-progress.md)。CLI 已统一到正式 profile 入口，旧 CLI 分流不再保留。

**DeepSeek Harness Win7** 是面向 Windows 7 及以上系统的开源 Agent Harness（智能体框架）Python 迁移工程，目标包含 **Cordis in Browser + React 18 + TSX + CSS Modules** Web GUI 与正式 profile CLI。浏览器协议和默认应用装配仍待完成。

本项目基于 **Python 3.8.10**，忠实复刻了 DeepSeek Harness 原生的 **Cordis（万物皆插件）** 架构。项目的核心目标是：
1. **Windows 7 兼容目标**：使用 Python 3.8.10；当前 Windows 回归不能替代 Win7 真机认证。
2. **极简模式与创造模式**：支持原生 DeepSeek Harness 的双关键模式（Minimal & Creative Presets）。
3. **1:1 官方 Web GUI**：提供基于 Cordis in Browser 微内核与 40 个官方 Client 插件的全功能 Web 界面。
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
- **旧兼容实现 (`ApiProxy`，不是固定上游的正式浏览器协议)**：正式路径需要迁移到 Connection → Gateway → Remote；下列旧路由仍存在于内部兼容代码，不代表 Web profile 已可用。
  - `/api/events/mux`：分发增量 Token 流、问答请求 (`question/requested`)、审批请求 (`approval/requested`)、目标投影 (`session/projection`)。
  - `/api/events/host`：分发会话生命周期、多工作区状态与背景作业。
  - `POST /api/respond`：异步应答唤醒挂起的工具协程。

---

## Web GUI (Cordis in Browser)

Web 端基于官方 **React 18 + TSX + CSS Modules** 架构，使用浏览器端 Cordis 微内核实现动态插件插拔：

- **37 个官方 Client 插件**：`ui-layout`、`ui-sidebar`、`ui-conversation`、`ui-composer`、`ui-user-questions`、`ui-permission-presets`、`ui-goal`、`ui-plan`、`ui-trajectory`、`ui-settings` 等。
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

运行完整测试套件：
```powershell
.venv\Scripts\python.exe -m pytest tests
```
测试数量和结果以当前检出的实际运行日志为准；历史通过记录不证明新默认 profile 或 Web 协议已经完成迁移。

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
