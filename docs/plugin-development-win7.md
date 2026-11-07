# Win7 创造模式插件开发

创造模式沿用固定原版的动态 Cordis 插件工作流，面向 DSH Win7 使用 Python 3.8.10 编写 Host，浏览器 Client 保持 plain JavaScript。Inspect、版本、审批、运行与清理语义不因语言适配而增加另一套开发模式。

## 默认入口

CLI 从安装目录运行：

```powershell
.\dsh.bat --profile creative "开发一个只读 Python 工具"
```

仓库中使用 `.venv/Scripts/python.exe dsh.py --profile creative`。Web 使用 `dsh.bat --profile web`，选择安装自带 cordis 预设。两个入口均通过已有 filesystem provider 提供同名的 [cordis-plugin-development 技能](../packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/SKILL.md)，系统提示要求开发前加载它，无需额外 Win7 patch 或复制用户 preset。

项目和用户同名技能继续遵循既有优先级；加载后核对内容与资源路径。已有用户 preset 副本中的旧 JS Host 教程不会被自动覆盖，需要用户选择性同步。不要修改运行中的安装自带 preset 来完成插件任务。

## 与原版相同的开发流程

1. cordis_inspect_list 获取当前 Host/Client Provider；按需 query 服务、事件、Builtin、工具、Slots 和主题。
2. 选择 Host、Client 或联合插件。修改已有插件时，先用 cordis_inspect_self 读取确切基版本，保留不需修改的另一半。
3. cordis_define 创建不可变 Package；cordis_run 激活返回的确切 ID。define 不运行插件，也不授予审批。
4. 观察实际运行、依赖等待、审批和浏览器诊断。遇到 awaiting-approval 或 starting 时结束当前工具流程，由系统状态续接，不循环等待审批。
5. 调用实际功能；stop 后验证工具、RPC、监听器和其他副作用撤销。stop 保留历史；undefine 永久删除。

默认七个 Cordis 工具仍为 inspect_list、inspect_query、inspect_self、define、run、stop、undefine。动态定义保存在进程内，重启后消失；挂载页面 overlay 也不改变这一生命周期。

## Python Host 与 Client

将技能目录中的 examples/echo.host.py 完整源码作为 code.host。运行后调用 win7_echo，参数 {"text":"中文 Win7"}；结果应为原文本，非字符串输入应拒绝，stop 后工具应不可再调用。

动态代码声明 callable plugin，通过 plugin.inject 声明硬依赖；工具使用 harness.defineTool 后由 ctx.tools.register 注册，服务使用 ctx.provide。完整原生 Context 的 set_service 不属于动态 facade。参数和输出使用实际动态 DSL，不能把原生完整 JSON Schema 写法直接套入。

技能附带 counter.host.py 的计数与 JSON RPC 示例、lifecycle.host.py 的事件/timer/异步清理示例。它们是参考，不要求所有插件实现计数器或执行专用检查脚本。

Host 的 harness.handle 与 Client 的 host.call 实现 Package 私有 JSON RPC。echo.client.js 使用原版 Run 卡 Slot；页面 overlay 使用其实际 Slot。Client 继续使用 React.createElement，不输入 TS/JSX，不改变原版浏览器源码。

## 必要的平台适配与已知差异

Python Host 采用 3.8 语法、显式 UTF-8、Windows 路径及 Win7 支持的系统 API。按当前 Inspect 查询可用 shell 和服务。Service/Event 的 TS 签名保留协议含义，实际 Python 调用、await 及 None/UNDEFINED 区别见技能参考。

define 在登记 Package 前编译检查 Host 和 Client；Client 以普通函数体内的 async 包装语境解析，再构造与原版一致的 Function 包装，仅编译、不运行源码。随包解析器拒绝固定原版不支持的 using/await using 声明、正则局部修饰符和跨分支重复捕获组名，允许 new.target、普通 using 标识符及动态 import options。用户不需要安装 Node 或 TS 工具链。全部 V8 语法边缘尚未完成等价验收，浏览器运行时仍可能遇到引擎差异。

Python Host 目前开放完整 builtins/imports，这是待单独认可或收窄的能力扩展，不是必要语言适配。普通插件仍应通过 Context 服务及其 effect 管理文件、网络、进程和定时器。临时 Host 的源码、闭包和任务现在由每个 Run 独立拥有的 Python 进程承载，真实 Cordis 服务与 Fiber 仍在主进程；`vmTimeoutMs` 在初始同步求值超时后终止执行进程，不再等待原生阻塞调用返回。后续异步 apply 和 RPC 不增加该超时限制。状态、验证范围及一比一对齐的剩余缺口见[进程边界修复与闭环复核](research/2026-11-07-creative-host-process-and-parity-audit.md)。

## 可选的本机源码发行

已有 [Python 源码发行能力](plugin-distribution-win7.md)可在用户明确要求持久交付时单独使用。它不属于原版默认七工具，也不是开展创造模式开发的前置步骤；默认技能不引导自动 export、安装依赖或修改 composition。

本次收敛及验证见[对齐记录](research/2026-11-06-creative-win7-authoring-alignment.md)。较早的[实施记录](research/2026-11-06-creative-win7-authoring-implementation.md)保留上一方案的观察，其模型评估不能直接作为当前技能的验收结果。
