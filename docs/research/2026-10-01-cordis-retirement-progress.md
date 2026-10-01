# 动态 Host 激活与终止事务

日期：2026-10-01；起始提交 `9580e78b`；固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。当前环境 Python 3.8.10 / Windows。
继续 [Guard 迁移](2026-10-01-cordis-guard-progress.md)，保持原版浏览器与 Client
代码，不加入 QuickJS 或 Node Host。

## 原版 bug：CORDIS-LIFECYCLE-001

原版 `cordis-host-runner/src/index.ts` 的 startFresh 在 startHost 完成后直接将
局部 run 提交到 plugin.run，广播 dynamic-package 并提交版本。stop / undefine
只处理已提交的 plugin.run 和审批请求，不使 starting 中的 Promise 失效，也不
等待它完成。异步 apply 尚未完成时，stop / undefine 与 startFresh 因而失去
同一 Plugin 的事务所有权。

真实固定原版 Context、ToolRegistry、runner、sandbox、guard 与 Fiber 复现：

| 场景 | 原版终止返回 | 放行 apply 后 |
| --- | --- | --- |
| 首次 Host / update 的删除 | ok:true、wasRunning:false | 定义已从 inventory 删除，服务仍残留；迟到的 dynamic-package 广播和激活成功仍出现。 |
| 首次 Host / update 的停止 | not-running | 未完成的激活继续提交，latestRun 为 running。 |
| 带 Client 的删除 | ok:true、wasRunning:false | 定义已删除，Host 服务仍残留；Host half 仍返回成功。 |
| 带 Client 的停止 | ok:true，并取消审批请求 | 随后重新变为 client-pending，Host half 仍返回成功。 |

apply 在服务注册后等待一个实际 Promise，终止调用穿过事件循环 checkpoint，
再释放 Promise。观察通过公开 inventory、服务读取、事件和返回值，而不是仅以
源码关键词推断。修复前 native 的六种观察与原版完全相等；其历史输出保留在
`.goose/out/cordis-retirement-native-before.json`。原版 checkout 未修改。

## 迁移版修复

- shared activation 增加 runner 所有的 transition；结束操作立即使其失效，并
  将对应 attempt 标为 cancelled。Caller 的 await 仍通过 shield，取消 Caller
  不取消 shared activation / retirement。
- stop 接受实际 starting 中的 Run；undefine 与 stop 共用按 Plugin 的结束任务。
  并发删除可以将已有停止升级为删除，共享一次资源排空。
- apply 返回后、替换旧 Run 排空后，重新检查 transition、Plugin 身份及宿主
  Fiber 是否仍有效。失效的局部 Run 先撤销 handlers，再 awaited dispose Fiber；
  不提交版本、不发布 dynamic-package、不把终止状态覆盖为 Host load failure。
- 已提交 Run 的 retract 继续保留原版事件与版本/授权规则。局部未发布 Run 的
  discard 不发布不存在的 retract。stop 保留 Packages 和已有 currentPackageId，
  更新失败保留 nextPackageId；删除在排空后移除定义。
- close 拒绝新定义/激活，使所有 transition 失效，取消 pending requests，等待
  每个 Plugin 的结束任务及 dynamic group disposal。多次 close 共享任务，取消
  一个等待者不丢弃 cleanup。真实 runner Fiber 卸载也检查宿主失效，阻止迟到
  发布。

终止不强行中断可信 Python apply：它等待 apply 及 disposer 自然完成，然后撤销
其注册。如果第三方 apply / disposer 永不结束，本方案仍可能等待；未认证任意
恶意代码、强制抢占、JS Promise / VM realm 或所有回调重入组合。

## 实际验证

`scripts/cordis_retirement_oracle.py` 分别运行真实原版与 native probe。八种旅程：
六种精确 **CORDIS-LIFECYCLE-001** 修正，两个已激活 Host 的 stop / undefine
控制旅程完全一致。门禁绑定 target SHA、源码/驱动与 fixture；六个 source 完整
观察分别绑定固定 SHA-256，只允许逐字段定义的取消、排空、版本与事件修正。
任意额外字段、不同 source、缺少清理或改变控制旅程都拒绝，不允许仅凭 mode
名称放过差异。

新增 **19 项** pytest：八种双侧旅程及 fixture/例外校验，取消 stop / undefine /
close 等待者、并发停止升级删除及重新定义，真实 runner Fiber 卸载，canonical
Web Remote undefineFromPanel，实际工具注册与异步 disposer 排空，以及 pending
browser request 关闭/迟到答复和旧版本 cleanup 中停止更新。

联合专项 **260 passed，20.06 秒**，退出码 0；原版七个相关测试文件原样执行
**127 passed，2.81 秒**。原版测试只作为 source 基线，不计 native parity。
保留 pytest-asyncio 默认 fixture loop scope 提示。

门禁：runner 15 旅程 / 149 动作保留既有精确适配；Guard 117 matched + 两个
CORDIS-GUARD-001；工具 92 matched；Inspect 42 matched + INSPECT-001。
工具 callback 探针手工创建 runner，需要增加新增生命周期字段；该 fixture
初始化已修复，生产实现没有为测试省略 ending 检查。

最终完整回归 `.venv\Scripts\python.exe -m pytest tests`（附 JUnit）为
**4454 passed、2 skipped、1 warning，390.73 秒**，退出码 0。JUnit 共 4456 项，
errors / failures 均为 0；输出为 `.goose/out/cordis-retirement-full.log` 和
`.goose/out/cordis-retirement-full.xml`。本轮代码在完整回归期间没有再修改。
保留既有 Windows Proactor transport 在 loop 关闭后的析构 warning，以及测试
HTTP 连接中止诊断，不宣称无警告通过。

六个 Python 文件通过实际 Python 3.8 AST / 编译检查；migration check / ready
均退出码 0。五份门禁 passed，所有记录的输入 SHA-256 无漂移；固定 reference
HEAD 为目标 SHA 且无 tracked 修改。`git diff --cached --check` 通过。新增十九项
测试与 fixture 随生产实现一起提交；用户既有未跟踪评估文件没有修改或纳入提交。

## 未完成与发布方向

本轮证明上述原生激活/终止竞争，不证明任意原版 JS Host / Workflow、Node VM
内建、一般 Proxy/跨 realm 行为、真实 Client 主题/Slot/HMR/重连旅程或完整 CDP。
其他未验收模块、精确当前候选的完整发行验收仍需继续；accepted_upstream 仍
未建立。Win7 真机及目标浏览器验证保持用户暂缓状态。

发行沿用 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
软件本体为固定 Python 3.8.10 的单目录 Portable；第三方插件统一走 profile /
Loader，本地目录与 ZIP 已有开发预览实现。持久创造模式源码导出、公开版本、
升级回退、锁定依赖闭包与哈希、原生依赖/预编译 client 联合验证，以及
GitHub/npm/PyPI 多来源获取归一化仍待实施。本轮没有重建或发布 Portable。
