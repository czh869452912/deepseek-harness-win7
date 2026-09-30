# Workflow 运行与原生 Ralph 迁移进展

日期：2026-09-30。工作从产品提交 `8d5afcb3` 继续；固定原版为
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为当前 Windows、原生 Python
3.8.10。本记录是实施与验证范围，不是全部 Workflow、全项目或 Win7 认证。

## 已实施

原来的 `workflow_service.py` 未执行脚本却返回 completed，`tool_ralph.py`
直接生成一轮完成文本。本轮删除这两种占位成功，接入真实运行和子代理调用：

- `WorkflowEngine.start(request)` 返回 holder 所有的运行句柄，提供 result、cancel、
  dispose。返回后的执行失败进入 stopReason，不拒绝底层 result Future。
- 验证 meta 全部字段、JSON 输入、路由、并发、总代理和组合器项目上限；meta/args
  脱离调用方容器。未知 JS 脚本在发布 run 和事件之前抛出
  `SCRIPT_RUNTIME_UNAVAILABLE`，工具层显示明确的运行时缺失错误。
- 真实 agent 调度使用捕获的 canonical SubagentRuntime，并区分子代理提供方路由
  与 provider/model 模型覆盖。正常结算计数包括已接受的排队调用；强制终止没有脚本
  结算报告时按原版使用 Host 已开始调用数。并发槽 FIFO 分配。
- 原生编排 hooks 为 agent、parallel、pipeline、phase、log、args。pipeline 无跨阶段
  全局屏障，普通阶段错误仅将该项变为 null；hook/上限/提供方基础设施错误为 fatal。
- 按原版参数数量发送 workflow 事件；agent-start/end 使用配对账本，end 只公开
  stopReason/error/agentsStarted，返回值留给句柄持有者。观察者异常分别容纳。
- 取消首次原因生效，所有未来 hooks 停止；释放事务与每个子代理释放均先登记、后调用
  提供方，以防重入重复释放。共享 signal、迟到的提供方发布、排队调用和 grace 超时
  均有测试。句柄调用者取消 dispose 等待不取消共享释放。
- 运行捕获依赖后，可以继续执行和释放，不因 workflowEngine 的卸载而丢失依赖。

Ralph 采用原版固定编排的 Python 移植。每轮调用 spawn fresh structured child，
只传递不变 objective、共享工作区指引和上一轮有界结构化 handoff；校验 continue、
complete、blocked 报告，并产生 budget-limited 或 round-failed 终态。子代理失败、报告
违规和非 completed 的工作流都是工具错误。完成展示只说 worker reported，不能冒充独立
验收。参数为原版 `objective` / `maxRounds`，默认与部署上限 256，交接及最终文本各
默认 16384 UTF-16 单元。配置、调用上限、提供方能力和无父 Agent 情况均显式校验。

`workflow` 工具已接通原版 schema、注入、提示段、结果及通用卡片展示；不再创建隐藏
fallback Engine，也不再注册 `run_workflow`。顶层调用向实际 Session 写入四种原版
tool-workflow 记录，嵌套调用不重复记录；记录失败只关闭该 run 的记录，不影响执行。
成员监听保持到 dispose 完成，随后写 run-end。

工具包装替换 signal 时，原来的 `_FusedSignal` 只提供 aborted 读取，不能让 Workflow
或子代理订阅 abort。本轮按原版 tools 的 fuseToolSignals 补齐独立 Controller、首次原因、
已取消 wrapper 优先和 dispatch 结束移除 relay。历史 asyncio.Event 输入通过等待适配；
原生 AbortSignal 继续同步通知。这是迁移版偏差修复，不是原版 bug。

## 固定程序与通用脚本的边界

原版 Ralph 的 String.raw 字面量保存在 `dsh/workflow/ralph_script.js`，开发 oracle
用 TypeScript AST 提取并核对固定原版字面量。Ralph 插件可逆注册这个 exact-source
对应的 `execute_ralph` Python 实现；返回后的 run 捕获 callable，不跟随注册卸载而失效。
这是 deployment-owned 内置程序的实验注册扩展，不是 JS 翻译器，也没有把模型任意脚本
改成另一种 DSL。仅原版固定 Ralph 程序可以由这项注册执行。

**通用模型 JS 工作流仍未完成。**本轮不提供 JavaScript parser、Node VM、任意 JS
执行、同步无限循环的进程隔离或 syncTimeoutMs 强制终止。配置字段保留供完整运行时
迁移；当前原生程序只是可信、预先移植的内置 Python 编排，不能将 asyncio 的取消或
grace 视为任意 Python 代码安全沙箱。任意原版 JS 输入继续是全量迁移的必要条件，
不能用当前 native 注册宣布该条件完成。

字符串归一化和限制遵循 ECMAScript trim / UTF-16，报告 JSON 处理配对和孤立
surrogate。原生 fixed-program 调度和原版 worker 的线程消息顺序并非本记录认证的
完整时序等价；一般工作流的 JSON 数字文本、跨 realm 数据、worker 崩溃和强制终止
仍需结合实际 JS 执行后端继续对齐。

## 已执行验证

专项 `.venv\Scripts\python.exe -m pytest tests/test_ralph_and_workflow.py
tests/test_tools_upstream_parity.py -q`：**114 passed**。

覆盖真实两轮 AgentLoop/structured_output：两个实际子会话身份不同，不继承父对话，
第二轮只收到上一轮 report。另在 canonical `run_profile(web)` 中执行工作流，写入
四类真实 Session 记录，关闭后重启通过 sessionQuery 冷读取，事件完整一致。这两类
场景分别使用可控 LLM 或子代理 fixture，不冒充真实远程模型或浏览器 UI 验收。

双侧固定程序 oracle：

```powershell
.venv\Scripts\python.exe scripts/workflow_ralph_oracle.py --output .goose/out/workflow-ralph-oracle.json
```

**18/18 匹配**：调用 prompt/options/schema、阶段、交接、四类终态、缺报告、报告
违规、JS whitespace、孤立/配对 surrogate 与 astral 大小限制。运行实际原版固定脚本，
不是重新实现的 JS 测试替身。比较采用规范 JSON wire 表示，UTF-16 配对与对应 astral
code point 表示为同一数据。此 gate 不认证通用脚本、host 调度或整个 Ralph tool。

原版源测试运行：

```powershell
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.workflow.config.mts
```

**221 passed / 6 files**，包含 Tools runtime、Ralph tool、Workflow tool/invariant、meta 与
realm 原样断言。这建立源行为基线，并不把 221 项计入 Python parity。原始输出保留为
`.goose/out/workflow-official-source.log`。真实 worker 用到源码
tsx，开发环境在被忽略的 `reference/node_modules/tsx` 下链接已有
`scripts/oracles/node_modules/tsx`；配置使用固定 reference/tsconfig.base.json。
最初的五文件基线缺少 tsx 时为 84 passed / 1 failed，补齐开发依赖后 85 passed；追加
本轮涉及的原版 Tools 源测试后为 221 passed，未修改原版源文件。
Node/TypeScript/Vitest/tsx 仅用于开发比较，不进入产品 Host 依赖。

另执行了实际句柄的取消等待冒烟：让子代理释放等待可控事件，取消首个 dispose 等待者，
共享释放保持未取消，放行后另一等待者完成，子代理只释放一次。

最终执行 `.venv\Scripts\python.exe -m pytest tests
--junitxml=.goose/out/workflow-ralph-reviewed.xml`：**3740 passed、2 skipped、1 warning**，
305.87 秒，退出码 0，JUnit failures/errors 均为 0。原始输出与 JUnit 位于
`.goose/out/workflow-ralph-reviewed.log` / `.goose/out/workflow-ralph-reviewed.xml`。
两项 skip 是 Windows 不适用的 POSIX 路径/权限语义；warning 为既有 Windows Proactor
transport 在事件循环关闭后的析构诊断。pytest-asyncio 未设置默认 loop scope 提示和
测试 HTTP 中止/重置诊断保留，不宣称零警告通过。未出现 Task was destroyed 或未取回
Future 异常诊断。
过渡实现两轮全量为 3737 passed、2 skipped、1 warning（308.72 秒），与 3738 passed、
2 skipped、1 warning（302.88 秒），它们不代替包含最后边界修复的最终代码验证。

Python 3.8 compileall、git diff --check、migration.py check 均通过；ready 退出码 0 且
无就绪任务输出，reference 工作树无修改。记录检查不认证本轮或全项目 parity。

## 后续迁移与交付

继续完成通用 JS 运行能力、Workflow 客户端投影联合旅程、动态 JS Host、Inspect/Guard
及其他未验收模块。QuickJS 没有成为正式依赖。本轮未发现可证实的新原版 bug；所修复
占位、信号和生命周期问题属于迁移版。

软件与插件交付继续采用 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)
与 [本地交付实施](2026-09-30-python-plugin-local-delivery.md)：固定 Python 3.8.10 的
Portable 本体，用户 Python 插件经 profile / Loader 安装，目录与 ZIP 已实现；创造模式
源码导出、升级回退、锁定依赖闭包、可选 client 的联合验证，以及 GitHub Release / npm /
PyPI 获取归一化尚须实施。本轮未重建或发布 Portable，Win7 实机与目标浏览器认证保留
用户暂缓状态；当前 Windows 全量通过不能代替它们。
