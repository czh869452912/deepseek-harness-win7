# 动态 Cordis runner 的审批与激活迁移

日期：2026-10-01；起始提交 `72ce4fa7`。固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为当前 Windows、原生 Python
3.8.10。本轮继续工具提供端的迁移，保留原版浏览器与 canonical Remote 协议；
不认证完整 JS Host VM、Guard、任意 JS Workflow、浏览器旅程或全项目 parity。

后续原生 Host 的 Context facade、工具 DSL、JSON 返回边界及函数服务 Context
泄漏修复见 [Guard 进展](2026-10-01-cordis-guard-progress.md)。下文保留本轮原始范围。

后续启动期间停止/删除及 runner 卸载的原版竞态复现和事务修复见
[终止事务进展](2026-10-01-cordis-retirement-progress.md)。

## 提供端修复

`cordis_runner_state.py` 承担版本、审批、激活、结算及通知；`host_runner.py`
负责 Python Host 求值、实际 Cordis Fiber 挂载和 handler 调用。

- define 只添加不可变 Package，不设置 nextPackageId。定义新版本后，成功的
  current 仍是默认修改基准；next 由激活尝试设置。之前的工具夹具没有证明
  实际 define 的行为，已有相关集成测试也已修正。
- Model run 的 awaiting-approval / starting、request payload、单版本/未来
  版本授权、最新 attempt 校验、页面直接运行与附着按原版迁移。直接页面运行
  只授予当前 Package，不因 flag 自动授予未来版本。
- shared activation 由独立 asyncio task 所有，等待者取消不取消 Host 事务。
  task 完成自行删除 starting 记录并观察异常；没有剩余等待者也不会留下假的
  transition-in-flight。真实异步 apply、阻止重复 run 和服务清理已覆盖。
- Client 成功结算才提交 current、清除 next 和审批字段。失败 update 不自动
  重启旧版本；拒绝保留旧活跃 Run。附着页面失败不错误撤销另一页面的 Host，
  只有确实启动且属于该请求的 Run 才被失败结算撤销。
- request 先 claim 再等待结算；重复/并发答案只有一次 accepted。成功或带
  Run ID 的失败必须匹配实际 active Run，过时答案不消费仍有效的请求。
- 激活/撤销改为原版 cordis/dynamic-package、cordis/dynamic-retract，修复
  旧 advertise/retract 名称与正式 Gateway allowlist 不相符的提供端偏差。
- stop 撤销 Run 和 pending request，保留 Packages、授权及指针；undefine
  删除定义。Model 结算使用 steer，面板动作使用 inject；面板只通知 agents
  registry 中身份仍一致的 Agent。
- Render / Client Guard Remote 使用原版 agent 与 failure 参数并返回 null。
  Render 保留活跃 Run、记录 Slot/abdicated 诊断且只首次通知；Guard/handler
  去重只在当前、已激活 attempt 上通知。
- handler 同名替换后，旧 disposer 不删除新 handler。返回经 lossless JSON
  snapshot 脱离活动对象；完整 Guard 的嵌套路径诊断仍待迁移。

除下面明确原版 bug 外，上述均为迁移版偏差修复。

## 原版 bug：CORDIS-RUNTIME-001

原版 `cordis-host-runner/src/index.ts` 的 steerHostHandlerFailure 使用
`Host + NUL + handler + NUL + method + NUL + message` 去重。方法名只要求非空，
允许 NUL；错误 message 同样可以含 NUL。真实同一个活跃 Package 两条 handler：

| method | message | 原版通知 |
| --- | --- | --- |
| `a\u0000b` | `c` | 第一次通知 |
| `a` | `b\u0000c` | key 碰撞，遗漏通知 |

两次 invoke 返回各自真实 handler-error，但第二次错误没有 steer。Python 改为
`(platform, kind, method, message)` 元组；第二个独立错误通知一次，重复调用
仍去重。固定原版未修改。门禁只允许指定旅程第二次 invoke 多出准确一条通知，
其余 value、inventory、grants、events、inject 等必须完整相等；改写错误信息、
添加重复通知或改动通知文本均有拒绝测试。

## 双侧证据与边界

`scripts/cordis_runner_oracle.py` 运行固定原版实际 runner、原版 setup 的真实
Cordis / Timer / ToolRegistry 树，以及实际 Python runner / Cordis 树。
shared cases 有 **15 条旅程、149 个动作观察**，逐动作比较返回值、完整 inventory、
授权集合、事件、steer/inject 和真实服务。13 条旅程完整相等；1 条为上述精确
bug 差异及 Python Host 指导语；1 条为真实 Host apply 失败的语言栈差异。

Host fixture 是明确成对源码，JS 在原版 VM 运行，Python 在原生 evaluator
运行。没有替换 runner 的 activate、settle、startHostHalf、retract 生产方法。
受控样例覆盖服务提供/移除、依赖 waiting 与后续注入、调用、handler 替换及
disposer、实际 apply 失败、延迟 apply 与 transition guard。其他旅程覆盖权限、
stale 答案、授权保留、拒绝 update、失败归属、面板身份、取消、render/guard
去重及并发 claim。审批由驱动模拟页面，Client 字符串没有在浏览器执行。

明确适配：Host handler 通知的 Plugin inject / undefined 指导改为 Python
plugin.inject / None。原版 JS apply 失败经 lifecycle 包装产生 JS stack，Python
保留自身异常 message，未伪造 JS 栈。源 probe 只把 stack 中工作树位置归一为
`[workspace]`，保留帧和坐标；gate 只允许指定 Host 失败旅程、指定 message、
含真实 startHostHalf 帧的 stack 不在 Python 输出出现，其他字段不因此忽略。

fixture 保存原版输出、固定 SHA 与源码/驱动摘要；门禁拒绝 reference tracked
修改、缺失/重复旅程、陈旧 fixture 和未登记差异。pytest 逐旅程重放 Python，
此前工具门禁增加状态机文件的输入哈希。

## 验证

专项 **166 passed，12.63 秒**，退出码 0，输出
`.goose/out/cordis-runner-focused-final.log`。新增 19 项，含 15 条源观察重放、
输入绑定、精确例外、等待者取消和正式 Web Remote 集成。

正式 Web profile 通过实际 Agent lookup / RemoteDispatcher 调用 runHostHalf、
getClientCode、resolveRequestRun、reportClientGuardFailure、reportRenderFailure、
stopFromPanel、undefineFromPanel；通过已注册 Gateway `$events` 流读取四个
Cordis 事件，完整确认名称、payload、顺序和 approved 结算。这是提供端与载体
验证，不冒充浏览器 UI 验收。

原版七个测试文件原样运行 **127 passed，2.80 秒**；这是原版基线，不计为
Python parity。旧工具门禁 **92 matched**；Inspect **42 matched + 1 精确
INSPECT-001 差异**。三份门禁输入摘要无漂移，报告为 cordis-runner-paired-final、
cordis-runner-tools-gate、cordis-runner-inspect-gate，位于 `.goose/out/`。

完整执行 `.venv\Scripts\python.exe -m pytest tests
--junitxml=.goose/out/cordis-runner-full.xml`：**4311 passed、2 skipped、1 warning，
342.11 秒，退出码 0**。JUnit 4313 项，failures/errors 均为 0。输出保存在
`.goose/out/cordis-runner-full.log` / `.xml`；生产与测试代码在该运行期间保持固定。
skip 保留 Windows 不适用的 POSIX 语义；warning 为既有 Proactor transport
在事件循环关闭后的析构诊断。pytest-asyncio 默认 fixture loop scope 提示及
测试 HTTP 10053 断开诊断保留，不宣称零警告。

8 个新增/修改 Python 文件的 Python 3.8 AST 与 compileall 通过。Migration check
通过、ready 退出码 0 且无就绪任务；reference tracked-clean，git diff --check
通过。这些检查不认证全项目完成，三份 paired 门禁的输入摘要无漂移。

## 剩余迁移与交付

任意原版 JS Host/Workflow 求值、完整 Guard Context facade / defineTool DSL /
嵌套 JSON 路径错误、Client 编译预检、终止期间尚在激活的事务、完整 inspector/CDP、
客户端 manifest/Slot/主题和真实浏览器恢复旅程仍待实施或验收。Python callable
plugin 形态不等于原版对象/function Plugin 的完整合同。全项目 accepted_upstream
未建立，Win7 实机与目标浏览器验证保留用户暂缓状态。

发行继续按 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
固定 Python 3.8.10 Portable；Host 插件经统一描述、profile、Loader 装配，按需
携带预构建 client。标准库插件目录/ZIP 和实验 API 1 已有；创造模式持久导出、
升级/回退、哈希锁定离线传递依赖、原生依赖 Win7 和 client 联合验证，以及
GitHub Release/npm/PyPI 获取来源归一化仍待实施。
本轮无生产依赖、QuickJS、Node Host 或浏览器源码变更，未重建/发布 Portable。
