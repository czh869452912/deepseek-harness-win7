# 创造模式：运行时行为修复与边界分类

日期：2026-11-07。对照本地固定原版 `a4c74a91e06b00fe0b0937bde982170c526cc842`。本记录不认定“除必要移植差异外完全等价”，也不变更发行候选或已接受上游例外。

后续实施已将临时 Host 的完整 Run 寿命迁到独立进程，替代下文的 trace 边界，见[进程边界修复与闭环复核](2026-11-07-creative-host-process-and-parity-audit.md)。本记录的失败、xfail 和开放状态保留原输入身份，不重标为后续修复的回执。

## 本轮代码修复

### 审批后重复附着

[runHostHalf](../../dsh/extensions/cordis_runner_state.py) 之前把原版 `!pending.requiresApproval` 翻译成了 `pending.requiresApproval`，误拒绝待 Client 激活的重复附着。现按原版布尔表达式逐项翻译。原版条件在需要审批时允许的状态集合较宽，本轮保持原条件，不将其另改成推测的“正确条件”。

新增 `approval-repeat-attach` [共享旅程](../../scripts/oracles/cordis-runner-cases.json)：同一审批请求启动 Host 后再附着，复用相同 Run，返回 `startedHere: false`；请求完成后旧请求拒绝；后续已获批准版本的重复附着同样成功。真实原版 Runner 与 Python Runner 各自执行整个旅程，对返回、事件、审批授权及 inventory 完整比较；原版观察夹具按新旅程重新捕获，不修改 reference。

### Client 定义前预检

[define](../../dsh/extensions/host_runner.py) 在 mint ID、创建 Plugin/Package 前编译 Client；语法失败保留旧 inventory 和 ID，已有插件版本也不会被污染。复用 [JavaScript parser](../../dsh/javascript/runtime.py) 的随包私有 Win7 引擎编译模式，抽出无服务状态的编译 helper；原有 jsRuntime.parse 继续检查服务存活并调用同一 helper。编译不会执行无限循环、throw 或注册副作用，前端源码未改，不新增 Node/TS 安装要求。

回归将九种有效/无效 JS body 的接受结果，与原版使用的 `new Function` 包装门比较，覆盖 Client-only/双半插件，验证新建和追加版本的失败原子性。这是有限语法样本与 gate 行为验证；QuickJS 与 Node/V8 的完整语法接受集合及极端输入性能仍未认证为完全等价。当前 Client 诊断给出解析错误消息及 plain-JS 提示，尚没有原版的源码行/caret 上下文和按出错行选择的教学提示；不能将预检接入等同于诊断文字逐项对齐。

## 仍开放的同步超时：CORDIS-SYNC-TIMEOUT-001

状态：**未关闭，功能偏离，尚未接受**。`sys.settrace` 仅在 Python 跟踪事件检查期限。初始顶层执行 `time.sleep(0.08)` 时，5ms 期限无法强制结束原生调用；原生调用返回后才会抛 TimeoutError，期间主事件循环阻塞。普通超时错误存在不代表同步边界得到保持。

[回归](../../tests/test_cordis_runtime_boundaries.py) 保留要求同步调用在阻塞结束前中断的 `xfail(strict=True)` 用例，输出真实 elapsed/result；此项预期失败不计入通过数。将来边界实现通过后，XPASS 会要求同步更新此记录。另保存 Node VM 的 Atomics.wait 机制探针；它仅验证原版所用 VM 机制，不冒充完整浏览器或原版 Runner 的端到端旅程。

不能用另一个 Python 线程加 wait_for/trace 实现强制中止：计时到期后原生调用仍继续，副作用与闭包也仍存活。不能以强杀线程替代 Cordis effect 清理。可执行的改进方向是让动态 Host 的完整寿命落在可终止的子进程，而非只预跑源码：Python 函数闭包无法作为现有对象直接搬回主进程，需要同时定义 Context 服务代理、事件/工具/JSON RPC、effect disposer、异常与取消、更新撤销及依赖重新激活合同；只预跑后在主进程再 exec 还会重复顶层副作用。

因此本轮不加入表面上的 timeout wrapper，不声称该缺口已关闭。若继续追求原版边界，后续应以子进程方案单独实施并验证原生阻塞、晚到副作用、存量 Run 保留、停止/更新/关闭清理。若保留同进程实现，则需用户明确接受这一功能限制；当前没有这项接受记录。

## 分类与决策状态

| 分类 | 当前事项 | 状态／后续方向 |
| --- | --- | --- |
| 必要移植调整 | Python 3.8 Host 语法与 callable/apply(ctx) 入口、Win7 路径/API/编码；Client 仍为 JS；随包 JS 引擎替代 Node 编译门 | 保持移植目标；不据此认证全部引擎或平台行为等价。 |
| 未接受的功能偏离 | 原生阻塞调用的初始同步超时 | CORDIS-SYNC-TIMEOUT-001，未关闭；上述进程寿命方案或明确接受限制。 |
| 主动能力扩展 | 完整 Python builtins、open、__import__ 及任意 imports | CORDIS-HOST-CAPABILITY-001，待认可或收窄；“受信进程”不是必要性或已接受证明。 |
| 本机附加设计 | 多 manager 内置 provider 共享租约；显式启用的源码导出/打包 | 与原版分列；共享租约维持公共重复注册拒绝，导出不进入默认七工具。 |
| 已登记上游缺陷例外 | Guard 的 CORDIS-GUARD-001 两个精确观察；Runner 的 CORDIS-RUNTIME-001 NUL 键碰撞 | 仅沿用既有精确例外与判据，不把新差异归入这些例外。正式身份见上游例外注册表。 |
| 设计债 | Creative 资源由启动层识别包名及特定路径 | 已维持用户相对路径合同；后续将产品资源定位合同放回 bundle/provider 一侧，独立验证覆盖优先级与迁移配置。 |

能力收窄的具体方向是保留常规语言 builtins 和纯计算入口，对直接文件/网络/进程/定时器入口提供指向 ctx.fs、ctx.web、shell、Cordis timer 的协作式报错，并验证 imports 不能成为默认旁路。要同时核对已有示例和插件迁移，明确纯计算模块范围及所有权清理；它不是恶意代码安全沙箱的承诺。本轮没有静默取消既有 imports，也没有将扩展登记为已接受。

## 验证与限制

本轮输出：`.goose/out/creative-win7-runtime-gaps-20261107-004800/`。`verification.json` 记录命令、退出状态、输入摘要、日志/XML、原始 Source/Python 观察及未完成项。选择状态机/guard/诊断/工具直接消费者、Client 编译 helper 的原有消费者及新 gate 回归；不重跑历史归档全量哈希、完整回归或发行门禁。

原生阻塞实际观察见 `timeout-observation.log/xml`：用 `--runxfail` 显示要求未满足的真实失败，5ms 配置约 94ms 后才报超时。Node VM 机制探针见 `source-vm-timeout.json`，本次约 17ms 结束；两者是本机观察，不承诺固定调度耗时。正常测试仍明确保留 1 项 strict xfail，不计为通过。

| 当前输入的检查 | 结果 |
| --- | --- |
| 最终运行时定向 pytest：Client gate、Python 诊断、Runner 及七工具消费者 | **55 passed、1 xfailed**，124.58 秒；`runtime-final.log/xml`。xfail 是未关闭的同步超时，不是通过。 |
| 新鲜 Source/Python Runner | **16 旅程、162 步**；14 matched、1 项既有 NUL 碰撞例外、1 项明确 Python traceback 投影；`runner-final.json` 及双侧原始观察。 |
| 新鲜 Source/Python 七工具 | **92 matched、0 different**；`tools-final.json` 及双侧原始观察。 |
| 最终源码、文档及回执检查 | Python 3.8 语法、相对链接、diff check、配对输入摘要、reference 干净状态；`final-checks.json`。 |

首批 `targeted.log/xml`、`runner-guard.log/xml` 及中间 `boundaries-*.log/xml` 均保留原退出状态：新增 Node 探针命令行经过本机 shim 时失败；测试最初缺少 Tools 依赖的 SystemPrompt；Client 错误消息类别断言也有不匹配。审批旅程最初没有携带完成请求所需的 pluginRunId，导致后续分支未真正进入预期状态；已修正旅程并重新捕获原版夹具，不能将首次配对通过当作这两个审批分支均被覆盖。没有覆盖首轮失败或将初始误标的 xfail 当作原生阻塞证据。

本轮没有浏览器多页面旅程、Portable 重建或 Win7 真机验收。此前 175 项回执属于旧输入；本轮记录不将旧通过数量与当前结果拼接，不以任何测试数量替代剩余缺口和能力边界决策。

后续复审发现上述 Client 编译入口的全局脚本语境误拒 new.target，并额外接受 using 声明；模型可见说明也未同步。这些已由[Client 函数语境修复](2026-11-07-creative-client-function-precheck.md)处理，本记录及其旧回执保留历史输入身份。同步原生阻塞超时与完整 imports/builtins 的待决状态没有改变。
