# 当前状态与最小可用基线审查（2026-09-28）

审查 HEAD：`675520bd`；最近产品候选：`7720cf03`；合并基线：`449396c0`（merge: consolidate legacy main into verified migration baseline）；固定上游：`cd5ef8148158c3a752a658978873241fdf8e2bbc`。基线之后共 55 个提交。本次不修改产品实现、任务状态或 accepted_upstream。

结论：Cordis/Agent/Session 已形成有边界、有回归与配对观察的架构基线，值得继续复用。但默认产品入口还没有形成可用基线。不能把“基础契约验收”“便携包可构建”“真实默认 profile 可完成任务”合成一个完成标记。当前最高优先级是装配与真实协议闭包，随后才是完整 Web 对齐。

**本次实际验证与环境**

- 初始工作树干净，无项目 `.venv`，reference 子模块未初始化。
- 机器已有 Python 3.8.10；本次用它创建 `.venv`，以 `uv pip install --python .venv/Scripts/python.exe -r requirements-dev.lock` 安装全部 15 个锁定依赖。原始 pip 安装遇到代理 TLS 的 `check_hostname requires server_hostname`，未修改全局代理，改用 uv 安装成功。
- 初始化 reference 到仓库固定 SHA，没有推进上游版本。
- `scripts/migration.py check` 成功：记录、固定 inventory 合法，不代表全项目 parity。`ready` 成功且无输出：当前没有可直接领取的 ready 任务，后续产品任务仍为 draft。
- 本机为 Windows NT 10.0.26200.0；Node v22.20.0 不等于发行门禁要求的 v22.22.2。本次没有运行完整 Node 官方 oracle/发行门禁、重建 portable 或访问真实模型服务。仓库记录的 3235 passed / 2 skipped 是上次环境的证据，不能冒充本次结果。
- 全量 pytest 已执行，但 WebServer 测试在关闭服务器后重新连接时无限等待；排除该项后在 persistent Bash 测试中触发终端死锁；排除两项后推进到约 95%，另一个 shell 用例再次触发同一死锁。均保存诊断，再补跑迁移核心专项与测试尾部。最终结果见本文件末尾。
- 探针仅使用独立临时 DSH_HOME、临时文件和 loopback HTTP，假 API Key。原始观察保存在 `.goose/out/current-review/`；该目录为忽略的本机审查产物，不是新签发的 migration acceptance。

**已经建立的基础**

| 层 | 后续提交形成的能力 | 仍需遵守的验收边界 |
|---|---|---|
| Cordis | effect/调用者所有权、异步事件边界、Fiber disposal、Include/HMR、必要消费者 | Core@10 的枚举场景与消费者闭包；C58 有精确语言适配，不是任意插件的通用正确性证明 |
| Agent | 未发布 create/resume 事务、preparation、取消与迟到结果释放；configured identity/startup/reload | 工厂与配置生命周期，不包含完整 AgentLoop 设置、模型 wire、所有默认 profile |
| Session 存储 | JSONL 冷恢复、write-behind、drain/HMR adoption、共享 preparation、公开读写游标 | 本地 JSONL/SQLite 的已定义契约；不等于原生上游 SQLite、压缩 JSONL、任意断电/多进程认证 |
| 投影注册器 | 精确弱 Session 身份、共享注册所有权、prefix catch-up、checkpoint/restore/hydrate | registry 已闭合；业务定义、持久化缓存、冷读消费者仍未闭合 |
| 纵向测试 | 实际 run_profile + Loader + 工具 + JSONL + 新 Context 恢复 | 定制 spine 配置和 mock LLM，不能代替真实默认入口及 provider |
| 发行基础 | 锁定依赖、固定前端字节、隔离 Python、受控 gate | 旧包证据不替代新机器复验；默认 profile dump 不等于运行任务；Win7 尚未认证 |

这些变化主要落在 Cordis、Agent、Session 及其必要消费者。`dsh/llm` 和 `dsh/core/tools.py` 不在这 55 个提交的产品改动中；插件注册表仅新增了一项。这解释了基础显著改善、产品入口仍有较大缺口的并存状态。以下问题是“当前遗留缺口”，本审查不将它们归因于某个 Astra 提交引入的回归。

**P1：默认五个 profile 都无法完成插件装配**

在新临时 DSH_HOME 中，通过 `.venv/Scripts/python.exe dsh.py --profile <name>` 启动；headless/standard/creative 额外传入 `review probe`。全部退出码 1，失败发生在发起模型请求之前。

| profile | 无法解析的不同 package 名数 | 典型缺失 |
|---|---:|---|
| minimal | 8 | sdk-app、sdk-jsonrpc-server、llm-deepseek、agent-spine-demo、terminal、sandbox-local |
| headless | 24 | headless runner、llm-deepseek、storage-domain、session-projection-cache、sandbox-local |
| standard | 24 | 与 headless 相同的当前默认装配缺口 |
| creative | 24 | 与 headless 相同的当前默认装配缺口 |
| web | 31 | api-gateway、Remote controllers、web-app、client/host runners，以及 base 缺口 |

这里计数是错误日志中的唯一未解析 package 名，不是待实现模块数，也不是工作量。部分能力已有 Python 类但没有对应插件入口/正确装配；部分能力实际未迁移。不能仅加名字别名宣称功能完成，也不能用 no-op 或静默忽略必需插件让 boot 变绿。

源码位置：`dsh/boot/profile.py:42` 的模板、`dsh/boot/plugin_registry.py:59` 的 Python 映射、`packages/bundle/*/cordis.patch.yml` 的实际 rows。证据：`profile-probes.json`。

**P1：CLI 双路径仍存在，旧路径的工具后处理契约已脱节**

`apps/cli/main.py:197` 对无 legacy flag 的调用走 run_profile；`--mode`、`--prompt` 等仍走 `main_async → build_harness`（第 108、217 行）。因此“legacy flags 全部转入同一 canonical profile”的描述不符合当前实现。`--mode minimal/standard/creative` 可以启动并接受 exit，不代表 `--profile` 同样可用。

更关键的是，在真实 CLI 子进程与 loopback HTTP server 之间执行一轮 editor view：CLI 注册了两件工具、进行了两次 HTTP 请求、最终退出 0，但第二次请求中的工具结果为：

```text
Error: on_tool_post_execute() takes from 2 to 3 positional arguments but 4 were given
```

`dsh/core/tools.py:1526` 派发 `(exec_input, result, next)`；默认启用的 `dsh/extensions/cli_visualizer.py:69` 仍接收 `(payload, next_fn)`。`finalize` 会把这类 observer 错误变成工具失败，成功执行的操作也可能失去正确结果。`tests/test_cli_visualizer.py` 手工派发的仍是旧参数形状，所以该单测可以通过而实际集成失败。

退出 0 和最后一段固定 mock 文本不能用于证明工具成功。证据：`legacy-probes.json`、`legacy_http_probe.py`、`legacy-http-probe.json`。

**P1：真实模型请求仍未完成消息/工具序列化，截断流会误报成功**

在上述 HTTP 捕获中，本地请求工具为 `{name, description, parameters}`，工具结果仍处于内部 `role:user/content:tool-result` 结构；而固定上游 `reference/packages/llm/llm-deepseek/src/serialize.ts:347` 将工具转换为 `{type:'function', function:{...}}`，并逐种翻译内部消息。

本地 `dsh/llm/llm_service.py:813` 直接复制 messages，第 824 行直接放入 tools。这不是单纯“缺少 parity 证据”，而是已观察到 wire 结构差异。严格按目标协议处理的服务不能据此假定能接受请求。本轮没有访问远程 API，不能声称已观察到真实 DeepSeek 的特定 HTTP 错误码。

同一探针传入 `--model review-model`，启动输出显示该模型，实际两次 HTTP 请求却为 `deepseek-chat`；minimal 的 wire system 也不是其配置的 software-engineer persona。`agent_loop.py:726` 的模型默认值与 provider 的 static_model 没有在真实装配中闭合。后续必须测“终端显示/配置 → Agent options → wire 请求”的一致性。

另一独立真实 HTTP 探针只发送一段 `partial` 文本，然后关闭响应，不发送 finish_reason 或 `[DONE]`。本地仍产生 block-end、估算 usage 和 `finish.reason.kind=stop`。固定上游 `sse.ts:39` 对这种情况抛出 `STREAM_CLOSED`。必须补终止标记、SSE framing、错误/重试和取消的真实 wire 验收。

证据：`behavior_probes.py`、`behavior-probes.json` 和 `legacy-http-probe.json`。宽松 mock 能完成对话并不能证明它接受的是正确协议。

**P1：持久 shell 的派发、后端选择和异常恢复均有缺口**

`dsh/shell/tool_pwsh_persistent.py:102` 注册的 execute 丢弃 `_exec`，调用 handle_pwsh 时没有提供 ctx；后者只从 ctx 获取 terminal service。已挂载真实 ToolsPlugin 和持久 shell 插件、并预先提供 terminal 替身后，调用注册工具仍返回 `Error: Terminal service unavailable`，terminal 实际调用次数为 0（`pwsh-dispatch.json`）。这比终端恢复问题更早阻断默认 shell 工具。

同文件第 76 行给 PowerShell 传入 `shell_type='pwsh'`，但 `PersistentTerminal._start_process()` 只识别 `'powershell'` 与 `'cmd'`，其余均启动 Bash，`TerminalService` 没有归一化该名称。这是静态确认的装配差异；本轮没有执行真正的 PowerShell 命令并据此推断其全部行为。

`dsh/shell/terminal.py:57` 创建 `threading.Lock()`；`execute()` 持有该锁时，在 stdin 写失败、EOF 或超时路径调用 `reset()`，而 `reset():104` 又获取同一锁，导致调用无法返回。单纯增加 execute 的 timeout 不会解除这个锁等待。

本次回归在 `test_shell_1to1_parity.py:63` 触发，堆栈明确停在 `execute:184 → reset:104`。本机 `bash` 解析到 Windows system32 的入口；即使这是环境触发条件，也不能把产品无限等待归结为“安装 Git Bash 就好了”。额外使用无实际进程的 EOF 替身，执行线程在 2 秒后仍存活且持锁，独立证实逻辑死锁。相同 reset 路径也供 PowerShell 使用。

证据：`pytest-remainder.log` 的 faulthandler 堆栈和 `shell-deadlock.json`。需要在工具最小闭包中一并修复，并验证 EOF、超时、broken pipe 均有界结束。

**P1（Web 基线）：业务投影与冷启动列表尚未连通**

创建并落盘一个完整 turn，销毁 Context，再以相同存储根创建新 Context：`sessionPersistence.list()` 返回 1 个会话，但 `SessionsDomainHandler.list_sessions()` 返回 `{"items":[]}`。本地 `dsh/host/apiproxy/api/sessions.py:52` 只遍历 `sessions_svc._sessions`；冷历史不进入该列表。结果是用户重启后看不到已保存会话，不是磁盘数据丢失。

`dsh/session/projections.py:78` 明确保留 legacy adapter：忽略描述性 schema，使用 identity parser，并把 `init(header)` 转成无参 init。todo、plan、permissions、stats 等仍通过这条兼容接口注册。registry 的 restore/hydrate 已实现，但没有本地 `sessionProjectionCache` 消费者将其串成 durable cold-read 路径。

正确顺序：可执行 domain definitions → storageDomain 必要契约 → projection-cache durable checkpoints → preparation/restore/hydrate → 冷列表与历史。这不是要求窄 CLI MVP 必须先实现所有缓存；若 CLI 通过完整日志恢复，可以先明确支持该路径。面向目标 Web 的缓存/冷读契约则不能跳过。

**P1（目标 Web）：传输栈与固定上游仍不同**

本地 `ConnectionService` 主要提供 trust/auth；路由仍由集中式 ApiProxy 接管，`api_proxy.py:561` 使用 SSE mux/host。固定上游通过 Connection 注册 RPC/fetch，Gateway 使用 `/api/remote.mux` WebSocket，再到 Typert Remote controllers。认证部分已有实现，不能说整个 Web 从零开始；但协议、取消、事件关联、重连、controller 和 browser 的共同闭包仍未完成。

预编译前端字节一致、静态资源可服务和 snapshot 文件存在，均不能认证当前目标前端与本地后端端到端等价。需要完成 host contracts 后从固定目标重建前端，再执行浏览器流程。

**P2：发行门禁对产品入口的证明过弱，文档仍过度承诺**

`scripts/verify_release.py:91` 的隔离 boot 创建无 bundle 的自定义 gate profile；`tests/test_portable_smoke.py:80` 对五个默认 profile 只做 `--dump-config`；`tests/test_profile_spine_recovery.py:12` 使用定制 spine rows。这些检查各有价值，但缺少“发行包真正使用默认入口做一次用户任务”的断言，因而与五个默认 profile 全部启动失败并不矛盾。

README 的“Windows 7 完美兼容”“1:1 全功能 Web GUI”“78 项测试 100% 通过”与 migration 的明确边界不一致。应该按运行面、目标版本和实测平台描述支持范围。当前测试多不意味着全项目迁移百分比高；272 manifests 和上游字面测试声明数都不能作分母。

**距 MVP 的距离与建议退出条件**

以下是工作拆分，不是工期承诺；尚未完成的 provider/consumer 契约不能按缺失名字数量估算人日。

| 阶段 | 必须交付 | 退出条件 |
|---|---|---|
| 1：一个正式入口 | 明确窄 minimal/headless 支持范围；统一命令路由、装配、模型/persona 配置；补齐必需 provider/runner；可选能力显式裁剪 | 新 DSH_HOME、真实默认命令、无临时 patch，插件全部激活；错误配置明确失败 |
| 2：可用的文本与两工具回路 | 正确 DeepSeek wire、SSE 结束/错误/取消、editor 与持久 PowerShell 的真实执行、所有 post-execute 消费者 | 严格 mock HTTP 校验请求；一次读文件、一次写临时文件、一次 shell；正确结果进入下一模型请求；取消后无活动资源；再单列真实 API smoke |
| 3：可恢复与可发行 | 同一正式入口的 JSONL 关闭/恢复、下一请求重建；源码与 portable 跑同一旅程；新机回归与明确支持说明 | 结束进程后新进程恢复并继续；损坏尾部/中断 turn 不静默成功；portable 使用自带 Python；受控测试无挂起 |

因此“窄 CLI MVP”仍需这 3 个跨模块闭包，不能称只剩打包，也无需先完成所有 201 个 runtime manifest。CLI 可用后再扩展 standard/creative 的完整工具策略与所有默认 profile journeys。

若 MVP 定义必须包含当前官方 Web，再增加至少 3 个交付块：①业务投影/存储缓存/冷读，②Connection → Gateway → controllers 的协议闭包，③固定目标前端构建与真实浏览器旅程。最后还要独立验证 Win7 运行时、PowerShell 与目标浏览器；Windows 11/Python 3.8 通过不能替代 Win7。

强模型下一轮适合负责上述跨层契约闭包，尤其启动装配、Wire、Tools 的提供端与必要消费者。建议现在就把“默认入口最小旅程”建成失败门禁，作为每次闭包的共同消费者；完整功能旅程仍可按依赖逐步开放。不要继续只扩 Core 测试，再等所有 Web/业务模块完成后才第一次尝试默认入口。

**本次回归最终结果**

全量收集 **3237 项**。三次全量范围的运行均因挂起未正常完成，没有取得全量通过的 JUnit 或发行门禁结论：

1. `pytest.log`：约 7%，`test_webserver_contract.py::test_serves_registered_routes_index_taps_and_the_fallback_seat_semantics`。独立 `webserver-probe.log` 定位在第 321 行的关闭后连接。该环境表现尚不能直接证明生产 HTTP 服务失效，但无超时的测试必须修正。
2. `pytest-remainder.log`：排除上述一项，约 91%，`test_shell_1to1_parity.py::test_persistent_terminal_bash_subshell_persistence`。堆栈确认持锁 reset 死锁。
3. `pytest-bounded.log`：排除上述两项，约 95%，`test_tools.py::test_pwsh_persistent_plugin`。同一死锁，通过 handler → TerminalService → execute → reset 触发。这些挂起进程已停止，未将挂起算作通过或 skip。

随后对 **22 个测试文件**补跑最近迁移核心和尾部：**246 passed、1 failed、1 deselected**（10.99 秒）。范围包含 Agent factory/config、projection registry、Session storage/live/preparations/write-behind、profile spine 以及 `test_tools.py` 起的测试尾部；deselected 为已诊断的 shell 死锁用例。这是专项结果，不能当作 3237 项全量结果。文件清单为 `final-test-paths.txt`；日志/JUnit 为 `final-scoped.log` / `final-scoped.xml`。

唯一失败为 `tests/test_cli.py:44`：期望 mock 最终文本，实际返回空串；独立重跑也是 **1 failed**（`cli-isolated.log`）。该测试只替换同步 chat_completion，AgentLoop 优先走 streaming，不能视为已经隔离了新机器上的 provider/凭据依赖。应在后续实现中修正真实失败行为与测试替身边界，不以宿主 API Key 或网络状态换取绿灯。

综合判断：最近的核心契约专项在本机通过；全量发行回归目前不可认证，默认 profile、模型 wire、工具执行和冷 Web 列表存在本轮独立复现的产品问题。保留现有架构闭包，新增面向正式用户入口的验收门禁，是距离 MVP 最近的推进方式。
