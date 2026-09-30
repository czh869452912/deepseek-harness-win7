# Cooperative Timeout 迁移进展

日期：2026-09-30。实施基线为 `8675a271`；固定原版为
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为当前 Windows 与原生
Python 3.8.10；不构成 Win7 实机、整个 Guard 或全项目迁移认证。

## 问题与修复

原版 `packages/guard/timeout-policy/src/index.ts` 使用共享 `deadline`，临时替换
执行信号，等待工具自行停止与清理，再按拥有的超时代码分类，并恢复上游信号。
迁移版原来使用 `asyncio.wait_for(next_fn())`，直接取消下游协程，也没有发送
deadline 信号；工具自己抛出的 `asyncio.TimeoutError` 还会被误判成 Guard 超时。

本轮改为正式的协作式实现：

- 新增 `dsh/core/timeout.py`，对应原版共享超时库的 `TimeoutReason`、
  `clampTimeout`、`deadline`、`timeoutOf` 与 `idleWatchdog`。
- 正数计时范围保持原版上限 2147483647ms；公开 hint 拒绝零、负数与非有限值。
  deadline 内部非正数 sentinel 不设 timer，直接返回上游信号。
- 融合信号保留首次原因；外层不同 code 的超时不会被本层认领。
  timer 释放后，仍被持有的信号继续响应上游；弱引用 relay 避免保留 holder。
- watchdog 只在 iterator demand 未完成时计时，pulse 重置当前 demand，消费端
  思考时间不计入空闲超时；信号身份稳定。释放 timer 不替代提供方终止工作。
- Guard 动态查询调用者可见的工具定义，发送 deadline 信号，等待下游结束，
  在 finally 恢复上游信号并释放 timer。工具自身异常和外层取消保持各自分类。
- 超时结果使用正式 `ToolExecutionResult`。原来的字典结果会被本地工具运行时
  视为普通值，无法保留结构化错误；这项消费端集成偏差一并修复。

这些问题均为迁移版偏差；原版已经有正确实现，本轮没有登记新的原版 bug。
没有新增生产依赖、现代 Windows API、Node Host 或 QuickJS，没有修改浏览器代码。

## 验证

Python 专项：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_timeout_policy.py tests/test_tools_upstream_parity.py tests/test_guard_and_spill.py -q
```

**99 passed**，包含 40 项新增 timeout 用例；除确定性计时之外，还执行真实
event-loop timer 的协作工具测试。覆盖清理等待、先后取消、provider 异常、嵌套
deadline、signal 恢复、卸载、GC 所有权、历史 Event 适配、watchdog 并发 demand、
原生 async iterator 与数值文本边界。

原版原样源测试：

```powershell
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.timeout.config.mts
```

**38 passed / 2 files**。它们建立原版行为基线，不计为 Python parity 用例。

双侧实际观察：

```powershell
.venv\Scripts\python.exe scripts/timeout_policy_oracle.py
```

**10/10 matched**。直接加载固定原版 Cordis、Tools、Guard 与 timeout 源码，比较
Python 对应实现的结构化结果、信号身份、清理等待、首次原因、嵌套分类、watchdog
计时与数值文本；不修改原版测试或产品源码。原始两侧 JSON 和日志保存在
`.goose/out/timeout-policy-paired.*`。runner 校验固定 reference HEAD 和完整观察身份。

另从 canonical `run_profile(web)` 实际创建标准预设会话，在真实 Tools 中注册一个
10ms 的协作式工具，确认工具收到 abort、完成 cleanup，再返回 `TOOL_TIMEOUT`，
并完成正式 shutdown。这是 Host/profile 冒烟，不冒充浏览器 UI 或远程模型验收。

初轮全量为 **3777 passed、2 skipped、1 warning**，305.16 秒，退出码 0，原始
日志与 JUnit 为 `.goose/out/timeout-policy-reviewed.log/xml`。随后补齐了
TimeoutReason 公共构造器的非有限数值文本，并增加三项边界用例。

最终执行：

```powershell
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/timeout-policy-final.xml
```

**3780 passed、2 skipped、1 warning**，304.18 秒，退出码 0。JUnit tests 为 3782，
failures/errors 均为 0；原始日志在 `.goose/out/timeout-policy-final.log`。两项 skip
为 Windows 不适用的 POSIX 语义；warning 为既有 Windows Proactor transport
在事件循环关闭后的析构诊断。仍有 pytest-asyncio fixture loop scope 提示和测试
HTTP 连接中止/重置诊断；没有 Task was destroyed 或未取回 Future 异常诊断，
不宣称零警告通过。

Python 3.8 compileall、git diff --check、migration.py check 通过；ready 退出码 0
且没有就绪任务输出，reference 工作树无修改。迁移记录检查不认证全项目 parity。

## 范围与后续

共享库不负责强杀不协作的工具；该行为与原版一致。Python 的 iterator demand
通过 `await watchdog.next(iterator)` 执行，支持原生 `__anext__` 和适配器 `next`。
历史 asyncio.Event 的 relay 需要 event-loop tick，原生 AbortSignal 同步通知。
本轮没有认证所有 IEEE-754 数字的 ECMAScript 文本等价。

各提供方自有超时与 stream watchdog 消费者仍须逐项对齐，不能因共享库存在即
宣布所有超时消费者完成。Repeat Tool Reminder、Inspect、通用 JS Workflow 与
动态 JS Host、客户端联合旅程以及其他未验收模块继续迁移。

下一项已核实的偏差：Repeat Tool Reminder 当前 `canonicalize({"q": 1})` 与
`canonicalize({"q": 1.0})` 不同，相同调用的第二次观察仍没有触发阈值 2 的提醒。
原版接收 JSON.parse 数值并通过 JSON.stringify 规范化，两者为相同 Number。
本轮仅记录这个待修复项，没有把 Repeat Tool Reminder 宣称为已验收。

发布方向继续遵循 Python 插件交付评估和已有本地交付实现：固定 Python 3.8.10
Portable，本地目录/ZIP 经 profile 与 Loader 安装，后续完成创造模式导出、升级
回退、离线依赖闭包与统一获取。Node/Vitest 仅用于开发比较。本轮未构建或发布
Portable；Win7 实机与目标浏览器验证保留暂缓状态。
