# DeepSeek Harness Win7

[README.md](README.md) | [AGENTS.md](AGENTS.md)

**DeepSeek Harness Win7** 是针对 Windows 7 及以上系统打造的开源 Agent Harness（智能体框架）Python 实现，集成了原汁原味的 **Cordis in Browser + React 18 + TSX + CSS Modules** 现代化 Web GUI 与完整 CLI。

本项目基于 **Python 3.8.10**，忠实复刻了 DeepSeek Harness 原生的 **Cordis（万物皆插件）** 架构。项目的核心目标是：
1. **Windows 7 完美兼容**：无缝运行在 Win7 SP1 / Win10 / Win11 及 Windows Server 环境中。
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
- **四象限双流网关 (`ApiProxy`)**：
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

3. 启动 CLI 或 Web GUI：
   ```powershell
   # 启动 Web GUI (在浏览器打开 http://127.0.0.1:8080)
   .venv\Scripts\python.exe dsh.py --web

   # 启动 CLI 交互模式 (标准模式)
   .venv\Scripts\python.exe dsh.py --mode standard

   # 启动 CLI 交互模式 (极简模式)
   .venv\Scripts\python.exe dsh.py --mode minimal

   # 启动 CLI 交互模式 (创造模式)
   .venv\Scripts\python.exe dsh.py --mode creative
   ```

---

## 便携版构建 (Portable Release)

项目支持一键打成无环境依赖的 Windows 7 便携版：

```powershell
.venv\Scripts\python.exe scripts\build_portable.py
```

构建产物将放置在 `dist/dsh-win7-portable/` 并打包为 `dist/dsh-win7-portable-v0.1.0.zip`：
- 双击 **`dsh-web.bat`**：一键启动 Web GUI 并在浏览器中打开。
- 双击 **`dsh.bat`**：一键启动 CLI 控制台交互模式。

---

## 单元与集成测试

运行完整测试套件：
```powershell
.venv\Scripts\python.exe -m pytest tests
```
目前包含 **78 项单元与集成测试（100% 通过）**。

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
