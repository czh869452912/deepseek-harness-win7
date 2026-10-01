# Agent 维护任务、取消与压缩关闭进展

日期：2026-10-01。产品基线 `8ea5f902`，固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。验证环境为当前 Windows / 原生
Python 3.8.10。本文记录实施与限定验证范围，不认证整个 AgentLoop 或全项目完成。

## 源行为与迁移修复

原版 ReactLoopAgent 的维护 phase 对外显示 idle，但 `activityDone` / `whenIdle`
仍等待实际维护任务结束，并跟随之后启动的 driver。原版 factory 的 dispose 先以
disposed 原因取消，再等待 whenIdle，最后释放 scope 并退出注册表。原迁移版只
检查对外 status，维护仍在摘要或 flush 时就可能通过 when_idle，提前释放服务。

本轮 `run_maintenance` / `runMaintenance` 在调用时同步占用维护 phase，返回可
await 的结果观察者；Agent 自己持有执行 Task。when_idle 等待独立的完成 Future，
然后继续检查维护后的 driver。取消结果或 idle 观察者不会取消 Agent 所有的任务。
异步 Python job 从已调度 Task 开始执行，返回的 Python coroutine 观察者支持既有
create_task 调用；不宣称其每个微任务顺序与 JS async 函数相同。

维护取消使用原生 AbortController，保留首次原因和同步通知。AbortSignal 保留旧
Python 插件的 Event 风格 wait / is_set 读取接口。维护结束清除残留取消状态和
唤醒 latch；无唤醒的注入保持停放，已移除的唤醒不会在下一次维护后重放。disposed
原因的活动不登记新唤醒。真正 idle 时取消可以清空队列，但不会预先取消未来任务。

BasicCompactionEngine 的取消分类按原版检查维护 signal 是否 aborted，以及融合
signal 的 reason 是否是维护 reason。原来的“哪个来源先通知”分类在 caller 与 Agent
使用同一个原因对象时不符合原版。另修复原生非异常取消原因经 Task / shield 丢失
的问题：原生非异常原因用 ThrownValueError 携带原始 `.value` / `.reason`，Exception
原因直接传播；共享 error_chain 对这个 Python 载体透明地读取原始值，保留空文本
和延迟读取行为。显式旧 asyncio.Event 的直接区域调用仍保留 CancelledError 适配。
Python 不能像 JS 一样 throw 普通对象，双侧比较对应原因身份与完整诊断文本，不
认证异常类型相同。AbortController 既有无原因/None 默认值的平台适配没有在本轮
重定义；本轮不认证所有平台默认 AbortError 的一致性。

## 双侧观察

```powershell
.venv\Scripts\python.exe scripts/maintenance_oracle.py --output .goose/out/maintenance-cancel-text-reviewed.json
```

22 / 22 matched，逐行严格比较，没有差异白名单。11 组实际 Agent 场景包含同步
占用和 busy、成功和失败身份、维护等待、首次取消、保留或移除排队唤醒、取消后
唤醒、disposed 不重放及 idle 取消。唤醒场景进入真实 driver，在真实 pre-step
扩展点等待再 reject，观察 whenIdle 是否继续等待新 driver 和 turn start/end；
没有替换 driver，也没有将“没有调用模型”伪装成完整模型旅程。

另 11 组使用原版 BasicCompactionEngine 和 Python 实际 engine、Session、TokenMeter、
factory dispose，比较摘要/flush 时的服务保留与注册身份、取消分类与原因归属、
flush 次数、compaction 生命周期记录、失败 close 的完整 error 文本、返回诊断、
surface generation 与最终 scope 释放。额外普通值覆盖空字符串、零、false、数组、
own message 与空 message，保留原因对象身份；不会因 Python 包装而添加固定提示。
使用可控 summarize hook，无付费模型或浏览器操作。

扩展首轮为 14 matched / 2 different，差异是 shared-cause 分类和 caller-first
原因身份。原始结果保留为 `.goose/out/maintenance-expanded.json`；修复后重跑得到
16 matched，没有改写首轮结果，也没有降低比较要求。之后加入完整返回诊断和
失败 close 文本比较，旧 16 组有 5 组出现文本差异，结果保留在
`.goose/out/maintenance-cancel-text-before.json`。修复载体并增加普通值边界后得到
最终 22 matched；最初较窄的 16 组成功不代替这项更强比较。

既有压缩 paired gate 重跑 155 组通过：153 matched + 已审核 POLICY-001、SUMMARY-001
两个精确原版 bug 签名，最终输出 `.goose/out/maintenance-compaction-final.json`。
本轮未新增原版 bug；上述问题是迁移版偏差。

共享 factory 的既有创建、准备、取消和卸载双侧门禁重跑 9 / 9 matched，输出为
`.goose/out/maintenance-factory-recheck.json`，未扩大其原先的限定验收范围。

原版源测试：

```powershell
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.maintenance.config.mts
```

161 passed / 4 files，3.74 秒，覆盖 loop、cancel、scope-lifecycle 和 manual-compaction。
输出 `.goose/out/maintenance-source.log`；源基线不等于 161 个 Python parity 场景。

Python 专项最终 189 passed，23.20 秒，输出
`.goose/out/maintenance-focused-final.log`。包含双侧观察的本地断言、取消结果与
idle 观察者、同步失败和返回 Future、真实 factory 关闭摘要/flush 的 scope 保留，
以及既有 Agent、压缩命令、调度、错误图与完整核心集成回归。

## 完整回归与后续

首轮全量在约 91% 的测试清理阶段停滞。读取实际运行进程的线程栈，主线程为
`pytest_asyncio._provide_clean_event_loop` → 创建 Windows Proactor 事件循环 →
Python 3.8 标准库 `socketpair` → `socket.accept`；不是观察超时推断进程已停止，
也没有重启一个尚未查明状态的进程。该进程仍存活，唯一 TCP 监听为自己的本机
socketpair 端口；未通过额外连接改变这对 socket 的关系或制造通过结果。
保存线程栈后，按 PID、父 PID 与完整测试参数核对身份并终止自己的停滞进程，
其统一执行句柄返回退出码 1。原日志 `.goose/out/maintenance-final.log` 与实际
线程栈 `.goose/out/maintenance-stalled-stack.log` 保留；此次没有完整 JUnit 结果。
标准库连接停滞的具体根因尚未确认，不登记为 DeepSeek 原版 bug。

附近的子代理文件单独诊断为 6 passed，0.32 秒，输出
`.goose/out/maintenance-subagent-diagnostic.log`。用 [py-spy](https://github.com/benfred/py-spy)
读取线程栈时只在 uv 的隔离工具缓存获取诊断程序，没有安装到产品 `.venv`、更改
应用依赖或修改运行中的测试。随后对相同生产代码和断言完整复跑，4090 passed、
2 skipped、1 warning，391.36 秒，退出码 0；JUnit 共 4092 项，failures/errors 均为 0。
日志及 JUnit 为 `.goose/out/maintenance-reviewed.log` / `.goose/out/maintenance-reviewed.xml`。
这是新增普通取消值完整诊断修复之前的过渡验证，不代替最终版本的完整回归。
最终版本执行：

```powershell
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/maintenance-complete.xml
```

4097 passed、2 skipped、1 warning，402.93 秒，退出码 0。JUnit 共 4099 项，
failures/errors 均为 0；日志和 JUnit 为 `.goose/out/maintenance-complete.log` /
`.goose/out/maintenance-complete.xml`。warning 为既有 Windows Proactor transport
在关闭事件循环后的析构诊断，pytest-asyncio 默认 fixture loop scope 提示与本机
HTTP 连接重置诊断保留，不宣称零警告通过，也不宣称修复了首轮标准库停滞的根因。

Python 3.8 compileall 与 9 个变更/新增 Python 文件的 3.8 AST 解析通过，固定
reference 无修改。migration check 通过，ready 退出码 0 且无就绪任务输出，
git diff --check 通过；迁移记录检查不认证全项目完成。

本轮不认证全部 driver 微任务顺序、任意第三方不合作 stream 的强制关闭、所有
生命周期扩展点、client 历史展示或真实浏览器联合旅程。通用原版 JS Workflow、
动态 JS Host、Inspect、其他未验收模块及最终发行验证仍在完整目标内。

交付继续遵循 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
Python 3.8.10 Portable、profile / Loader 管理的 Python 插件、按需预构建 client。
本地目录 / ZIP 安装已有实验实现，创造模式持久导出、升级回退、锁定离线依赖闭包
及 client 联合验证、多来源获取归一化仍须实施。本轮没有生产依赖、QuickJS、Node
Host 或浏览器源码变更，未重建或发布 Portable；Win7 实机及目标浏览器验证保留
用户暂缓状态。
