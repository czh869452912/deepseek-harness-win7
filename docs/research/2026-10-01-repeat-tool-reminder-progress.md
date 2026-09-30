# Repeat Tool Reminder 迁移进展与原版缺陷

日期：2026-10-01；工作从 2026-09-30 的产品提交 `278bfd68` 继续。
固定上游为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为当前 Windows 与
原生 Python 3.8.10；本记录不认证整个 Guard、全项目或 Win7。

## 已修复的迁移版偏差

- 参数规范化使用已有 Cordis ECMAScript 数值与键枚举 helpers，输出紧凑 JSON。
  `1`、`1.0`、`1e0` 具有同一个重复键；大整数按 JS Number 的精度处理。
- 深层非索引键按 UTF-16 排序；索引键按 ECMAScript 数字顺序枚举。
  字符串归一化配对 surrogate，并转义孤立 surrogate。
- 详细提醒按 UTF-16 单元截断，保留原版省略数量和切开 surrogate 的行为；检测
  仍使用完整参数，不使用被截断的预览。原来的 JSON 空格和 code-point 计数均已修复。
- wildcard 保持其余元字符字面匹配、严格首尾锚定与 JS dot 的行终止符规则。
  include/exclude 保持未追踪调用既不计数也不重置的语义。
- 增加原版 Config schema；拒绝错误的数组/元素类型，接受整数形式的浮点数配置，
  对 threshold 排序并拒绝重复。继续使用 Agent 对象的私有弱引用 chain。
- 保留后续策略的 accept/value 或 block/feedback；按原版 block 分支只保留正式
  字段，前置提醒并保留其余上下文。后续失败仍推进 chain，不注册额外假 service。
- 真实 AgentLoop 回归发现字符串 `Agent.followup()` 适配没有在 pre-step 前携带
  用户来源，导致新用户提示无法重置 chain。字符串入口现在通过 `create_user_message`
  构造带身份、来源和正式 content blocks 的消息；已构造的消息继续沿用原输入。

最初新增专项为 1 failed / 44 passed，失败是真实多轮 user reset；修复入口后，包含
Agent、AgentLoop、团队与子代理相关回归的专项为 **68 passed**。其中本轮新增
`tests/test_repeat_tool_reminder.py` 为 44 项。

## 原版缺陷 UPSTREAM-REPEAT-001

定位：原版 `packages/guard/repeat-tool-reminder/src/index.ts:89` 的 `sortJsonValue`。
第 93 行创建普通对象 `{}`，第 95 行通过 `sorted[key] = ...` 复制键。
当 key 为 `__proto__` 时，这会调用普通对象的 prototype setter，未创建同名 own
property。因此 JSON.stringify 丢掉这个参数键。

实际复现输入：

```json
{"__proto__":{"q":1},"ok":true}
{"__proto__":{"q":2},"ok":true}
```

配置 `thresholds: [2]`，同一 Agent 连续调用 `probe`。两次工具都实际接收到完整的
不同参数，但原版 Guard 将它们归一为 `{"ok":true}`，错误发送 identical-arguments
提醒，并把该提醒传入第三次模型请求。

迁移版排序使用 Python 字典保留 `__proto__` 为普通数据键；两次不同参数不触发
提醒，随后再次调用第二组相同参数仍正常触发提醒。此差异是明确的原版 bug 修正，
不是把数据丢失当成兼容要求。原版源码未修改；源端可用 null-prototype 容器或
明确创建 own data property 修复，不需要将合法 JSON 键排除。

双侧探针分别断言实际工具收到上述两组原始参数，排除传输/工具运行时先丢键。
`repeat_tool_oracle.py` 只允许这个固定上游、exact-case 输入、完整提醒与模型请求
差异；工具结果及其他观察仍必须相同。原版修正后同一案例可以直接匹配。修改目标、
threshold、工具结果或增加意外字段均不能使用这项 allowance。

## 验证

```powershell
.venv\Scripts\python.exe -m pytest tests/test_repeat_tool_reminder.py tests/test_guard_and_spill.py tests/test_reference_core_agent_specs.py tests/test_reference_core_agent_loop_specs.py tests/test_agent_team_collaboration.py tests/test_agent_team_full_specs.py tests/test_session_checkpoints_and_subagent_parity.py -q
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.repeat-tool.config.mts
.venv\Scripts\python.exe scripts/repeat_tool_oracle.py
```

结果分别为 **68 passed**、**20 passed / 1 source file**、**13 matched + 1 reviewed
upstream bug**，均退出码 0。原样源测试建立源行为基线，不计为 Python parity。

双侧使用真实 AgentLoop、Tools、Guard 与可控 LLM，而非只调用 detector helper。
比较 Session notice 的全文/来源、每次模型请求实际收到的提醒，以及工具最终结果。
覆盖深层顺序、数值形式、索引/UTF-16 键顺序、surrogate 预览、透明排除、变化重置、
默认/自定义阈值、用户重置、拒绝调用、后续 block/value 替换及原版丢键案例。
原始输入、两侧 JSON 与日志位于 `scripts/oracles/repeat-tool-cases.json` 和
`.goose/out/repeat-tool-paired.*`；开发 Node 不进入生产 Host 依赖。

全量执行：

```powershell
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/repeat-tool-final.xml
```

**3824 passed、2 skipped、1 warning**，304.75 秒，退出码 0。JUnit tests 为 3826，
failures/errors 均为 0；原始输出在 `.goose/out/repeat-tool-final.log`。skip 为
Windows 不适用的 POSIX 语义；warning 为既有 Windows Proactor transport 的
事件循环关闭后析构诊断。pytest-asyncio fixture loop scope 提示与测试 HTTP
连接中止/重置诊断仍存在；没有 Task was destroyed 或未取回 Future 异常诊断。

另通过 canonical `run_profile(web)` 创建标准预设会话，经正式 Tools 连续执行
参数 `q=1`、`q=1.0`、`q=1`，additional contexts 数量为 `[0, 0, 1]`，第三次
带正确的 repeat-tool-reminder 来源，随后正式关闭 profile。此验证确认实际 Loader
配置及预设监听有效，不冒充浏览器 UI、远程模型或 Web notice 的冷恢复验收。

Python 3.8 compileall、git diff --check、migration.py check 通过；ready 退出码 0
且没有就绪任务输出。reference 无修改，记录检查不认证全项目 parity。

## 剩余边界

原版定义 parsed JSON / malformed raw string 为参数域；本轮没有实现通用 JS
执行或 JS 对象/函数序列化。已有 Cordis 数值 helper 的使用与所列案例通过，不能
当作所有 IEEE-754 数值格式的穷尽认证。当前证据未覆盖恶意自定义 Python Agent
相等性、所有并发事件交错、浏览器显示或真实远程模型。

全量迁移继续包含其他 Guard/Inspect、各提供方超时消费者、通用 JS Workflow 与
动态 JS Host、客户端联合旅程和 Portable。第三方插件发布继续遵循 Python 插件
交付评估：profile/Loader 管理 Python 插件，本地目录/ZIP 已实现，创造模式导出、
升级回退、离线依赖闭包和统一获取仍待实施。本轮未新增生产依赖，未修改原版
浏览器代码，未重建或发布 Portable；Win7 实机与目标浏览器验证保持暂缓。
