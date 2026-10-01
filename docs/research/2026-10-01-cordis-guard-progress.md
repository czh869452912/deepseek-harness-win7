# 原生动态 Host 的 Guard 与工具声明迁移

日期：2026-10-01；起始提交 `bb9d54ca`；固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为当前 Windows、Python 3.8.10。
继续 [runner 迁移](2026-10-01-cordis-runner-progress.md)，移除 Python Host 中
defineTool / registerTool 的透传。没有修改原版浏览器，没有添加 JS 引擎。

后续激活期间 stop / undefine / runner 卸载的实际竞态修复与原版 bug 复现见
[终止事务进展](2026-10-01-cordis-retirement-progress.md)。下文为本轮 Guard 验证范围。

## 实现

`dsh/extensions/cordis_guard.py` 由实际 Host evaluator 调用，不是独立演示层：

- 参数声明支持原版直接 ParameterSchemaSpec 和 raw object wrapper。映射 required
  名称，保留根注解；直接 DSL 的嵌套 object 必须显式指定 additionalProperties，
  raw nested object 默认开放。未知词汇、错误 required、oneOf、enum、类型、
  注解及循环结构在声明时失败，使用原版路径与指导错误。
- author schema 编译器把 json 转为无约束 raw schema，编译 object、array、scalar、
  literal、oneOf、注解与 required。经既有共享 assertSupportedJsonSchema 再验证。
  输出 schema 同样按 author DSL 编译，不能把原版 type:json 当 raw JSON Schema。
- lossless JSON 克隆保留各调用点及嵌套路径，拒绝 nonfinite、negative zero、
  undefined、函数、非普通/装饰容器及循环；复制共享引用为独立数据。schema 和
  JSON 的遍历均为显式任务栈，1600 层声明已经双侧验证。
- execute、render、presentationMeta 返回值经克隆；render 必须为带字符串 type
  的 content blocks 数组，允许扩展 tag，不擅自把 union 收窄到固定类型。错误预览
  按 JS UTF-16 的 120 单元截断，包括非 BMP 字符。
- 工具定义保留原版 timeout、finalizer、presentCall/presentResult 和并发分类器。
  execute 严格校验参数，展示与分类器对不适用参数软回退。定义获得进程内身份
  marker；普通 dict 和从定义复制的 dict 都不能通过 registerTool。
- ctx facade 暴露 effect、事件、provide、计时器和工具元数据；服务属性读取要求
  inject，get 是可选读取。timer 调用仍要求 timer 声明。root/fiber/registry/extend
  等内部成员及 facade 写入失败并报告。Python facade 的宿主引用保存在外部弱表，
  不把 _ctx 暴露为普通属性；这不构成恶意 Python 代码安全边界。
- 工具 facade 的 get/schemas 只给名称、说明及参数，不能取得 execute，保持正式
  ToolsService 调度入口。与实际原版相同，调用工具 facade 仍依赖声明 tools 注入；
  未声明时产生原版 cannot get property "tools" without inject。
- 服务成员、同步/异步方法结果以及直接取得的服务值均拒绝 Cordis Context。
  普通服务数据/方法仍转发到实际实例，服务写入转发，facade 自身不可写。
- handler 使用同一克隆与精确路径。Host 求值后以 guarded Plugin 挂载实际 Fiber；
  支持原生 callable plugin 和包含 apply 的 plugin dict。Python callable 的 inject
  等元数据保留，避免丢失原生声明；不是 JS function/VM realm 的等价认证。

## 原版 bug：CORDIS-GUARD-001

原版 guard.ts 的 guardedService 只有 Proxy get trap。读取服务方法后调用能检查
返回值，但服务本身为函数时，直接调用 Proxy 没有 apply trap，因此跳过 denyContext。
这违反同一文件声明的“服务不得把 Cordis Context 交给动态代码”的规则。

真实固定原版 Context 提供 callable 服务，分别同步返回 Context 或异步解析为
Context；真实 guardedPlugin 的 facade 调用 get('callable') 后直接调用。两种
情况下都实际拿到原始 Context，且没有 Guard 报告。普通 callable 返回 ready
同样可用，证明这不是缺失服务/声明错误。

Python GuardedService 的 __call__ 在返回值或 await 结果上执行同一检查，抛出原版
denyContext 指导错误并报告一次。两个 mode 的门禁只接受精确 source escaped:true /
reports:[] 到该精确 error / 单条 reports 的变化；其他 mode、额外字段、缺失报告
及任意不同结果均拒绝。固定原版仍 tracked-clean，没有偷偷修补 source 基线。

真实 native Host 的运行期集成进一步证明：函数服务泄漏被阻止，Guard 和 handler
诊断各通知一次，重复调用不重复通知，Run 仍 running；没有以自动停止替代原版
运行期故障合同。测试在真实 Agent 上观察 steer 边界，不启动远程模型请求。

## 证据与验证

`scripts/cordis_guard_oracle.py` 运行实际原版 sandboxDefineTool、normalizeHandler、
sandboxRegisterTool、guardedPlugin，以及实际 native helper。**119 项观察：117 完全
相等，2 个精确 CORDIS-GUARD-001 例外**。参数 DSL、原始 wrapper、schema 错误、
非 JSON 返回、嵌套路径、UTF-16 预览、软展示、marker、防内部读取、服务 Context
返回、服务写入、普通 callable 和 1600 层结构均有实际对照。

原版 helper 使用实际 Cordis / Timer / ToolRegistry；ctx facade 通过真实 Plugin
挂载取得，不伪造 ctx.fiber.inject。此 probe 不运行任意 JS Host 全局代码，但原版
相关 Guard export 是生产实现。共享 fixture 保存真实 source 观察和源码/驱动哈希，
绑定固定 SHA；门禁拒绝 tracked source 修改、陈旧 fixture 和未登记差异。

专项 **241 passed，17.90 秒**，退出码 0；输出
`.goose/out/cordis-guard-focused-final.log`。本轮新增 124 项：119 个 source 观察、
输入绑定、例外拒绝、引用隔离、真实 Web Host 注册/执行/参数校验/元数据/卸载、
真实运行期 Guard/handler 通知。

此前 runner 15 条旅程、149 动作仍通过；工具门禁 92 matched；Inspect 42 matched
+ 1 精确 INSPECT-001 例外。runner / 工具门禁增加 Guard 模块输入哈希。原版七个
相关测试文件原样 **127 passed，2.77 秒**，仅为 source 基线，不计 Python parity。
报告位于 `.goose/out/cordis-guard-paired-final.json`、cordis-guard-runner-final、
cordis-guard-tools-final、cordis-guard-inspect-gate；四份输入摘要均无漂移。

最终完整回归 `.venv\Scripts\python.exe -m pytest tests`（附 JUnit 输出）为
**4435 passed、2 skipped、1 warning，362.69 秒**，退出码 0。JUnit 共 4437 项，
errors / failures 均为 0；日志与 XML 位于 `.goose/out/cordis-guard-full-final.log`
及 `.goose/out/cordis-guard-full-final.xml`。警告是既有 Windows Proactor transport
在事件循环关闭后的析构诊断；专项另保留 pytest-asyncio 默认 loop scope 提示，
不宣称零警告。最终回归包含服务索引读取与字符串键写入转发修复。

此前索引读取修复前的完整回归为 4434 passed、2 skipped、1 warning，347.65 秒，
保留在 cordis-guard-full.log / .xml；以上最终结果取代它作为本轮最终验证。
七个 Python 文件通过 Python 3.8 AST / compileall；migration check / ready 均
退出码 0。固定 reference 无 tracked 修改，四份门禁输入摘要无漂移，
`git diff --cached --check` 通过。这些结果不认证 Win7 实机或全部上游迁移完成。

## 未完成与交付

这里是原生 Python Guard/API 迁移，不能代替任意原版 JS Host/Workflow、Node VM
内建与全局 traps、cross-realm JS prototype / symbol 行为，或真实 browser Client
Guard / Slot / 主题 / HMR / 恢复旅程。Python 的反射、导入和全局不是恶意代码沙箱。
通用对象/函数的所有 JS Proxy 语义、动态激活中的终止事务、Client 编译预检、完整
inspector/CDP 及其他未验收模块仍须继续实施或验证。accepted_upstream 未建立。

发行保持 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)
方向：Python 3.8.10 Portable；统一 profile/Loader 的 Host 插件，按需预构建 client。
已实现标准库插件本地目录/ZIP 和实验 API 1；持久创造模式导出、升级/回退、离线
锁定依赖闭包与哈希、原生依赖/客户端联合验证及获取来源归一化仍待实施。
本轮未新增生产依赖、QuickJS 或 Node Host，未重建/发布 Portable；Win7 实机与
目标浏览器验证保留用户暂缓状态。
