# DeepSeek Harness Win7

[README.md](README.md) | [AGENTS.md](AGENTS.md)

**DeepSeek Harness Win7** 是针对 Windows 7 及以上系统打造的开源 Agent Harness（智能体框架）Python 实现。

本项目基于 **Python 3.8.10**，忠实复刻了 DeepSeek Harness 原生的 **Cordis（万物皆插件）** 架构。项目的核心目标是：
1. **Windows 7 完美兼容**：无缝运行在 Win7 SP1 / Win10 / Win11 及 Windows Server 环境中。
2. **极简模式与创造模式**：支持原生 DeepSeek Harness 的双关键模式（Minimal & Creative Presets）。
3. **零依赖 Portable Release**：提供脱离 Python 全局环境依赖的开箱即用便携版。

---

## 核心架构 (Cordis Architecture)

本项目遵循 Cordis 的核心设计理念：**“产品的每一部分都是插件”**。

```
                    +-----------------------------+
                    |    Context (ctx Service Container)  |
                    +--------------+--------------+
                                   |
         +-------------------------+-------------------------+
         |                         |                         |
  [ctx.llm]                 [ctx.tools]               [ctx.sessions]
  OpenAI / DeepSeek API      Tool Catalog              Append-only Event Log
         |                         |                         |
  [ctx.fs]                  [ctx.terminal]            [ctx.agent_loop]
  Local Workspace FS        Persistent PowerShell     Turn & Step Loop
```

- **上下文容器 (`Context`)**：服务（Service）统一绑在 `ctx` 上，插件之间通过 Key 进行依赖查找而非强耦合导入。
- **依赖声明 (`inject`)**：插件通过 `inject` 字段声明所需服务，等待服务就绪后触发 `apply(ctx)`。
- **可逆副作用 (`effect`)**：所有的工具注册、事件监听均注册为可撤销 effect，插件卸载/重载时自动清理资源。
- **类型化事件分发**：
  - `emit`：同步/观察者通知
  - `waterfall`：中间件管道（处理修改数据与短路）
  - `parallel`：并发扇出 (`asyncio.gather`)
  - `serial`：顺序串行执行

---

## Agent Presets 模式

### 1. 极简模式 (Minimal Mode)
仅提供固定 Persona 与核心双工具的轻量模式：
- **`str_replace_editor`**：基于字符串精准匹配的文件查看、新建、替换与插入工具。
- **`pwsh` / `cmd`**：持久化 PowerShell / Cmd 命令行执行环境。

### 2. 创造模式 (Creative Mode)
用于自定义 Agent Preset 创作与插件调试：
- 具备标准模式的全部工具与文件能力。
- 引入 **`cordis-manager`** 插件，提供 `cordis_list_plugins`、`cordis_inspect_context`、`cordis_unload_plugin`、`cordis_dump_config` 运行时检视工具。

---

## 快速开始

### 源码运行

1. 克隆仓库并使用 `uv` 或 `python` 创建环境：
   ```powershell
   git clone https://github.com/deepseek-ai/deepseek-harness-win7.git
   cd deepseek-harness-win7

   # 使用 uv (推荐)
   uv venv --python 3.8.10 .venv
   uv pip install -r requirements.txt --python .venv\Scripts\python.exe
   ```

2. 设置 API Key 与 Base URL：
   ```powershell
   $env:DEEPSEEK_API_KEY="your-api-key"
   $env:DEEPSEEK_BASE_URL="https://api.deepseek.com" # 或 OpenAI 兼容 Endpoint
   ```

3. 运行 CLI：
   ```powershell
   # 导出极简模式 Cordis 配置树
   .venv\Scripts\python.exe dsh_cli.py --mode minimal --dump-config

   # 启动交互式 CLI (极简模式)
   .venv\Scripts\python.exe dsh_cli.py --mode minimal

   # 启动交互式 CLI (创造模式)
   .venv\Scripts\python.exe dsh_cli.py --mode creative

   # 单次命令模式
   .venv\Scripts\python.exe dsh_cli.py --mode minimal -p "请用str_replace_editor在当前目录下新建一个test.txt"
   ```

---

## 便携版构建 (Portable Release)

项目支持一键打成无环境依赖的 Windows 7 便携版：

```powershell
.venv\Scripts\python.exe scripts/build_portable.py
```

构建产物将放置在 `dist/dsh-win7-portable/` 中，包含绿色独立的 Python 3.8 环境，双击 `dsh.bat` 即可直接在任何未安装 Python 的 Windows 7 机器上运行。

---

## 单元与集成测试

运行完整测试套件：
```powershell
.venv\Scripts\python.exe -m pytest tests
```

---

## 目录结构

```text
deepseek-harness-win7/
├── dsh/
│   ├── cordis/               # Cordis 核心框架 (Context, EventBus, Plugin, Loader)
│   ├── services/             # 基础服务 (LLM, Tools, FS, Terminal, Session, AgentLoop)
│   ├── plugins/              # 核心插件 (Persona, FsLocal, StrReplaceEditor, Pwsh, CordisManager)
│   ├── presets/              # Preset 描述 YAML (minimal.yaml, creative.yaml)
│   └── harness.py            # Harness 构建器入口
├── scripts/                  # 构建便携版与自动化工具
├── tests/                    # pytest 测试套件
├── dsh_cli.py                # 主 CLI 可执行入口
├── AGENTS.md                 # Agent 协作与开发规范 (英文)
└── README.md                 # 项目说明文档 (中文)
```

---

## 许可证

[MIT](LICENSE)
