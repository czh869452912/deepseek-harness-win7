# 正式入口切换：实施与未完成边界

日期：2026-09-28。基于 `675520bd` 的未提交工作树；固定上游仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。本记录承接同日审查，不签发新的 migration acceptance，也不推进 accepted_upstream。

**状态：已实施并验证一批基础修复；用户要求的全部迁移尚未完成，当前不是最小可用发行基线。**

## 已实施

- `dsh.py → apps.cli.main → parse_dsh_args → run_profile` 成为唯一公开执行链。移除旧 argparse、交互循环、build_harness 分流；旧 `--mode/-m/-p/--prompt/--web` 启动形式退出报错。profile 后的应用参数仍由应用解析。增加正式 plugin 子命令处理。两个 bat 启动器使用同一链路。
- 新增 native DeepSeek 文本 provider 与 headless runner 的正式插件映射。工具定义和工具往返消息使用真实 HTTP wire 格式；SSE 按事件边界解码，缺少 `[DONE]` 报 STREAM_CLOSED，不再补造成功终止或估算 usage。
- 修复 cli visualizer 的 tools/post-execute 参数契约。持久 shell 工具收到 Context，终端按 Agent 隔离；修复 PowerShell 名称、Git Bash 选择、超时/EOF 重入锁死锁、取消和进程树清理，改为首次执行时启动进程。
- 将 JSON storage backend 与 storageDomain 分开注册；新增 per-record JSON、持久 projection checkpoint，以及不激活冷 Agent 的会话列表。缓存绑定日志生命周期身份，先获取投影截面，再 flush 日志，最后写缓存。损坏和过期缓存记录不影响其他会话。
- 注册已有 WebService 实现到 `@deepseek-ai/dsh-web`；实际装配、无 provider 错误和卸载行为有测试。
- release gate 的 isolated boot 从空 profile 改为真实 headless/Web 组合。默认装配缺失时不允许借空配置通过发行门禁。该检查仍只是装配检查，不等于浏览器端到端验收。

旧 `dsh.harness`、ApiProxy 和相关测试仍作为内部兼容代码存在；公开 CLI 已不走旧 harness。完整旧 Web 实现尚未删除，不能将本次描述为“所有旧实现都已清除”。

## 验证

环境：本机 Python 3.8.10 `.venv`，锁定开发依赖，已初始化固定 reference；Windows NT 10.0.26200.0。没有调用收费模型接口。

| 验证 | 结果与边界 |
|---|---|
| `.venv\Scripts\python.exe -m pytest tests -q --tb=short --junitxml=.goose/out/current-review/canonical-full.xml` | 3245 passed、11 skipped、2 warnings；263.92 秒。覆盖本批主体修改。警告是 Windows asyncio pipe/subprocess transport 清理；不是无警告验收。 |
| 随后的缓存损坏格式修复 | `tests/test_projection_cache_durability.py`：6 passed；包含新增 3 个损坏旧缓存场景。 |
| 随后的 WebService 正式映射 | plugin_registry、web_service_upstream_parity、tool_web_upstream_parity：88 passed。该修改之后未重复整个全量套件。 |
| HTTP headless journey | 真实 launcher、Loader、Agent、编辑器、loopback HTTP SSE、工具结果回传、JSONL；成功完成及截断非零退出均覆盖。配置为定制 core profile，不冒充默认 base 组合。 |
| shell regression | 实际注册工具、同 Agent 状态保持、不同 Agent 隔离、子进程有界超时及 EOF 后重启。 |
| migration check | 通过：记录和 pinned inventory 有效；不是新代码 parity 认证。 |
| git diff --check | 无空白错误。 |

原始本机证据位于忽略目录 `.goose/out/current-review/`，没有伪装为已提交的正式验收证据。Node 当前为 22.20.0，不是 release gate 要求的 22.22.2；本次未运行完整官方 Node oracle 或构建便携包。Win7 真机与浏览器尚未验证。

## 正式 profile 仍失败

最后一次探针使用独立临时 DSH_HOME、关闭遥测、移除模型 key，且 base URL 指向无服务的 loopback 地址。产品都在模型调用前因装配失败退出 1：

| profile | 缺失的唯一 package 名数 |
|---|---:|
| headless | 18 |
| web | 26 |
| minimal | 7 |

证据：`canonical-profile-probes.json`。全部七类 profile 的冻结缺口并集为 36 个 package 名（包含其他 app 和遥测配置），不是 36 个同等工作量模块。`test_plugin_registry.py` 故意验证这些缺失会明确报错；该测试通过不表示应用可启动。

## 剩余工作与完成标准

1. **默认装配**：实现 Typert loader/Gateway、sandbox/terminal、jobs/goal、skill、subagent providers/control、其他 LLM provider、inventory/title/code runtime 等必要 rows；minimal 另需 SDK app/stdio JSON-RPC/terminal 组合。不得以 no-op、别名或删除必需 rows 让启动变绿。
2. **完整模型边界**：当前 native DeepSeek 实现是文本范围；图像附件、完整 settings 校验与 last-good 更新、超时/取消、上游 retry-policy 的精确等价还未闭合。明确拒绝 image 不等于已支持 image。
3. **正式 Web**：Connection 必须接管路由所有权，完成 Gateway/Remote controllers、stream/request/error/cancellation 生命周期、host/client runners 与应用启动；随后切换前端消费者，再删除旧 ApiProxy carrier。当前冷列表是可复用的服务能力，仍通过旧 handler 接入，不能代替 Remote 控制器迁移。
4. **数据消费者**：补齐业务投影的可执行 schema、完整 sessionQuery/历史读取与 Web replay，验证缓存失败降级、服务替换和热重载。当前 storageDomain provider 使用 JSON backend 依赖；其他 backend 组合仍需处理。
5. **发行**：真实默认 headless 完成工具往返、会话落盘与新进程恢复；真实 Web 浏览器完成创建、响应流、工具、取消、冷恢复；固定 Node/前端重建/官方配对观察；便携包隔离启动及上述旅程；最后才是 Win7 真机认证。

优先完成默认 headless 及其必要提供者，再将相同 Agent/Session 核心接入正式 Web。当前已有进展可以继续复用，但不能据本次 pytest 全绿宣布用户要求全部完成。
