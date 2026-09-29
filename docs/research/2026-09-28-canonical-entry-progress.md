# 正式入口迁移：可运行基线与剩余差距

更新：2026-09-29。固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。本记录不签发 migration acceptance，也不推进 accepted_upstream。每个已验证的独立部分均本地提交，未推送。

## 工作 1：正式入口与默认组合

- `83385bea`：唯一公开执行链为 `dsh.py → apps.cli.main → parse_dsh_args → run_profile`。旧 `--mode/-m/-p/--prompt/--web` 形式退出报错；bat 使用正式 profile 链。内部 legacy harness / ApiProxy 仍有存量，正式 Web 切换后还需清理。
- 已接入 native DeepSeek、pi-ai、headless、jobs、活动 Loader 包清单、SkillRegistry、SessionTitle、Goal、子 Agent、sandbox、PowerShell executor 和 Python code runtime。注册映射本身不作为上游等价证明。
- SDK 已具备真实 stdio JSON-RPC、取消与 EOF/appReady 退出接线。minimal 实测 launcher → RPC → loopback HTTP → 持久 PowerShell 工具 → assistant → JSONL → 正常退出。
- `d516c1b1`：默认 headless 实测 launcher → HTTP → 文件工具 → 后续模型请求 → JSONL → 正常退出。新进程重新装配同一默认 profile，通过公开 Agent resume 恢复会话并继续模型轮次；探针不启动一次性 runner，不表示 CLI 新增 `--resume` 参数。
- `af62f475`：默认 standard、creative 的相同旅程通过。三种 pi-ai 协议也各自经完整默认 headless、真实文件工具和持久 replay 完成两次模型请求；仅配置 loopback 端点、凭据和模型，没有关闭默认业务插件。
- 默认组合暴露并修复了子 Agent 提示上下文、AgentLoop `cwd` 变量、Goal 卸载、压缩误触发/非表面事件边界，以及重复工具提醒未继续 waterfall 的问题。

上述证明了短会话的可运行 CLI 基线，**没有证明默认组合的全部能力已与上游等价**。旧 compaction 仍缺少完整的上游摘要调用、稳定性/收敛检查、事务标记和手动维护闭包；目前不能验收长会话。Web / ACP 不属于已跑通入口。

## 工作 2：原生模型边界

### DeepSeek

已有原生 HTTP/SSE、工具消息、usage、截断拒绝、HTTP 错误分类、可取消连接/读取、消费者关闭、provider retry-policy、每请求模型/配置快照、图片预算、Files API 与过期 file-id 恢复、扩展接受事务和请求归因。

`49c06729` 修复 settings provider 注册时被关闭的问题。schema 合法但 resolver 不可用的配置允许写入，adapter 保持整个 last-good 代次；实际文件测试覆盖保存、回退和卸载。

固定上游 Node / Python **76 个同输入配对观察一致**。`56c8e891` 新增真实 HTTP adapter → retry middleware → Session 场景：服务错误恢复、认证失败拒绝重试、次数耗尽、过长 Retry-After 和 always 策略。此处重试调度循环为探针，不冒充完整 AgentLoop。

### pi-ai

- 原生 replay version 2、签名/响应身份、坏回放逐消息降级、历史和图片上下文、跨模型工具 ID、增量 JSON 与预算已移植。
- 目录事实来自锁定 `@earendil-works/pi-ai@0.84.2`，目录能力上限与显式请求上限分开保存。Node 只在开发 oracle 使用，产品运行不依赖 Node。
- `b309a47c`：正式 provider、动态 settings、路由替换、目录发现、有界 HTTP 模型列表、显式凭据不回退、请求代次与卸载取消。
- `f0cf3305`、`ab3bcfed`：已实际支持三种显式协议：`openai-completions`、`openai-responses`、`anthropic-messages`。包括工具增量、签名保留/回填、usage、终止/截断、HTTP 错误、首包/空闲超时及调用方取消。
- `d51d0d8a`：图片模型能力与附件服务预检查；显式凭据 → 已存储 pi-ai key → credential reference / 环境的优先级。遇到未支持的 stored OAuth grant 明确失败，不回退到另一把环境密钥。
- **322 个配对观察一致**，其中 Completions、Responses、Anthropic 各有 21 个实际 loopback HTTP 场景。比较 JSON 事实和错误码，不比较错误措辞、随机身份和精确时序。

**完整多 provider 等价仍未完成**：OAuth 登录/刷新、云专用协议（如 Bedrock、Vertex、Azure、Codex）和各 provider 专属认证尚有缺口。目录中的模型不意味着其全部协议可用；未实现协议会在正式配置阶段拒绝。Anthropic OAuth token 传输也明确拒绝，没有伪装为普通 API key。

## 其他剩余工作

1. 长会话压缩契约，以及上面的 OAuth / 云专用模型边界；因此用户指定工作 1、2 的“完整上游对齐”不能记为全部完成。
2. 正式 Web controllers、host/client runners、应用与前端消费者；旧 ApiProxy 不可替代新架构验收。
3. 业务 projection schema、完整 sessionQuery / Web replay、缓存失败降级和热替换。
4. 前端重建、便携包隔离启动、浏览器端到端及 Win7 真机认证；未完成前不宣称可发行。

冻结包名缺口并集为 **12**。minimal 为零；headless / standard / creative / sdk 仅剩被 `DSH_TELEMETRY_DISABLED=1` 禁用的 telemetry 包。该开关是上述旅程的显式运行条件。其余缺失包主要为 Web 与 ACP；计数不是工作量或 parity 百分比。

## 验证环境与证据

- 本机 Python 3.8.10 `.venv`，Windows NT 10.0.26200；Node 22.20.0，不是 release gate 指定的 22.22.2。
- 全量 `native-baseline-final.xml`：**3583 passed、11 skipped、1 warning，336.99 秒**，覆盖 `af62f475` 的全部实现；凭据/图片定向 10 passed，默认 profile 与三协议 Agent 旅程 8 passed。
- pi-ai 配对报告：`.goose/out/current-review/pi-three-protocol-paired.json`，322 matched。DeepSeek：`deepseek-retry-paired.json`，76 matched。
- `migration.py check` 通过；此门禁校验记录与固定 inventory，不证明功能等价。
- 仍有既有 Windows asyncio transport 清理 warning 和 HTTP 测试连接关闭 stderr，不记为无警告验收。
- 没有调用收费 API。原始报告在忽略目录 `.goose/out/current-review/`；WinPTY 仅声明 `inferred_idle`，sandbox Windows ACL 仅部分隔离，code runtime 为 `python/process`。没有用当前 Windows 验证替代 Win7 认证。

