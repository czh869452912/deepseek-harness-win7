# 正式入口迁移：当前进展与未完成边界

更新：2026-09-29。固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。本记录不签发 migration acceptance，也不推进 accepted_upstream。

**用户指定的剩余工作 1（默认装配）和 2（完整模型边界）仍在推进，尚未全部完成；不能据测试全绿宣布达到最小可用发行基线。** 每个已验证的独立部分均作本地提交，未推送。

## 正式入口与已完成装配

- `83385bea`：`dsh.py → apps.cli.main → parse_dsh_args → run_profile` 成为唯一公开执行链。旧 `--mode/-m/-p/--prompt/--web` 形式退出报错，bat 使用同一链路。内部 legacy harness / ApiProxy 尚有存量代码，正式 Web 切换后仍需清理。
- 正式提供者已补 native DeepSeek、headless、jobs、活动 Loader 包清单、SkillRegistry、SessionTitle、Goal、子 Agent、sandbox、PowerShell executor 与 Python code runtime。对应具体边界见 Git 提交及测试，不将包名映射视为实现证据。
- SDK 已具备真实 stdio JSON-RPC、取消与 EOF/appReady 退出接线。`c695cc25`、`fd778a21`、`9b73a7da`：Windows WinPTY、Job 所有权、Agent 隔离、有界滚屏、持久 PowerShell 工具与内部 preset 依赖。
- `26c31dd5`、`68c27785`：Agent 请求深冻结、作用域事件投递、registry 所有者事件总线与 spine invariants。
- `a859f4aa`：正式 minimal 的 agent spine 组合已可运行。实际默认 minimal 经 launcher / stdio RPC / loopback DeepSeek HTTP / 持久 PowerShell 工具往返 / assistant / JSONL / 正常关闭完成旅程。另有定制 headless 旅程，不能代替默认 headless 验收。
- WinPTY 就绪状态只声明 `inferred_idle`，不声称完整 xterm/前台进程组可验证。当前新 terminal backend 为 Windows 实现；通用 spine 的可选 toolBash 尚未实现，Windows minimal 显式禁用该选项。
- sandbox 使用 restricted token、能力 SID ACL 与启动前 Job 所有权；Windows ACL 是部分隔离。code runtime 声明 `python/process`，不冒充 TypeScript/V8 worker。

## 模型边界与配对证据

### Native DeepSeek

已有原生 HTTP/SSE、工具消息、usage、截断拒绝、HTTP 错误分类、可取消连接/读取、消费者关闭、provider retry-policy、每请求模型与配置快照、图片归一化与预算、Files API 与过期 file-id 恢复、扩展接受事务、匿名/session/compaction 请求归因。

`49c06729` 修复文件 settings provider 在注册时即被错误关闭的问题。schema 合法但 resolver 不可用的设置按固定上游允许写入，adapter 保持整个 last-good 代次；不同于 pi-ai 的 serviceability 写入拒绝规则。实际文件测试覆盖保存、last-good、卸载与写入生命周期。

固定上游 Node 与 Python **71 个同输入配对观察全部一致**，包括文本序列化、流、错误、配置/预算、settings、图片事务与 Files API。真实 loopback HTTP 与模拟附件/上传存储的场景分别标明。仍需完成剩余跨层 retry 观察；这些结果不是所有 provider 的等价认证。

### pi-ai 多 provider

- `6e09fc41`：version 2 原生 replay envelope、签名/响应身份保留、坏回放逐消息降级、流终止/取消/溢出分类。
- `b8e8bdbd`：历史与工具结果转换，图片角色预校验、附件去重、预估及精确两阶段 base64 预算，保持持久历史不变。
- `0db724f2`：从锁定的 `@earendil-works/pi-ai@0.84.2` 提取目录事实；Python 原生配置解析、目录覆盖、兼容字段和 reasoning 能力。目录能力上限与部署显式请求上限分开保存。生成器仅开发使用，产品目录读取不依赖 Node。
- **110 个配对观察全部一致**：覆盖上述边界与全部目录 provider 的模型描述/配置结果。比较 JSON 事实和错误码，不比较错误措辞与时序。

**尚未完成 pi-ai 的真实多协议 HTTP、认证/发现/settings 生命周期和正式 provider 注册。目录、回放与上下文模块已有实现，并不表示这些 provider 已能发起模型调用。** 未借 DeepSeek 别名或空 provider 消除装配缺口。

## 当前缺口

冻结 provider 缺口并集为 **13**：minimal 已为零；headless / standard / creative 仍有 `llm-pi-ai` 与被隐私配置禁用的 `session-telemetry-otel`。其余为正式 Web controllers / runners / app、session-log-export / reference，以及 ACP app。计数是包名数量，不代表等量工作量。

1. **默认装配（本轮范围）**：完成 pi-ai 真实协议与生命周期；验证默认 headless 的工具往返、落盘、新进程恢复及退出。其它默认组合逐项验证，不删必需 rows 以掩盖缺失。
2. **完整模型边界（本轮范围）**：补跨层 retry 等剩余观察，把目录、配置、图片、replay、流和真实 HTTP 连接起来；验证准备请求后 settings 替换不会混用代次。
3. **正式 Web**：已有 Gateway / Remote / Connection 基础，但业务 controllers、host/client runners、正式应用及前端消费者仍未完成。旧 ApiProxy 不可充当新架构验收。
4. **数据消费者**：业务 projection schema、完整 sessionQuery / Web replay、缓存失败降级和热替换仍需闭环。
5. **发行**：真实默认 CLI 与浏览器旅程、前端重建、便携包隔离启动、Win7 真机认证。未完成前不宣称可发行。

## 本机验证

- Python 3.8.10 `.venv`，Windows NT 10.0.26200；Node 22.20.0，尚非 release gate 要求的 22.22.2。
- 最新全量：`.venv\Scripts\python.exe -m pytest tests -q --tb=short --junitxml=.goose/out/current-review/pi-context-full.xml`：**3542 passed、11 skipped、1 warning，327.21 秒**。覆盖 `b8e8bdbd` 产品代码；其后目录/配置与上下文定向 **8 passed**，其中目录新增 3 项。
- pi-ai 配对 110 项通过；native DeepSeek 配对 71 项通过。没有调用收费 API。
- 全量仍有既有 Windows asyncio transport 清理警告，另有测试 HTTP 连接关闭 stderr；不记为无警告验收。
- 原始报告位于忽略目录 `.goose/out/current-review/`。正式验收记录未推进；未完成完整便携包构建、浏览器端到端或 Win7 真机验证。
