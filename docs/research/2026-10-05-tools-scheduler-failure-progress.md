# 工具调度失败边界推进

固定原版 cd5ef814 的实际 Context、Agent、Tools 和 AgentLoop 上执行六个观察：pre 抛错、execute wrapper 抛错、pre 拒绝、成功，以及 c3 的准备暂停期间 c1 失败、c2 在准备释放前或后失败。原版两种错误结果都调用捕获的 finalizeContent 并通知 tools/result；失败的并行池记录已开始的三个 tool/call，只派发 c1/c2，排空已开始的调用后保留首个错误，不伪造 tool/result。

原生六项回归在修复前为 4 failed、2 passed；错误路径漏掉 finish/result 通知，准备暂停期间发生调度失败后仍派发 c3，而且后到错误覆盖首个错误。精确失败日志保存在 `.goose/out/acp-a4-work/tool-scheduler-regression-before-v1.log`。调度器现在直接处理 prepare 的 post-result/final-result，按模型顺序分别执行 finalize/finish；准备返回后重新检查失败，所有失败路径保留首个错误并排空已开始的任务。没有新绕过、跳过或时限放宽。

修复后的六项和相邻 Tools/Agent 测试共 68 passed；六组 AgentLoop/消费者文件另有 51 passed。实际原版六观察单独运行通过，保留 source-v1/v2 原始 JSON 和日志；tracked `scripts/oracles/tool_scheduler_failure.probe.spec.ts` 可重复进行新的只读源观察。六项回归进入完整发行门禁必需清单。当前完整门禁仍未签收；这不是整个 B2 工具/批准/取消组合或任意准备与派发同步前缀的签收。

存储候选 a6cf3dcd 的完整 tests 为 6808 passed、1 failed、6 既有平台 skips、1 既有 warning。失败仍是原版浏览器 host 插件升级启动的五个 POST 和 HMR SSE 取消，两条原版 console error 拒绝候选；17 步业务完成不能替代错误判据。精确 ZIP SHA256 `a42207b435f87cb4c555be8b0ce445789acbd288c2cfc449a23a7bf89de0de9a`，输入 SHA256 `affb1d48d1e0ccfafab9d6680a34615ff7351928ae6101961f51dc4636cd9308`，产物、XML、日志、netlog 与拒绝来源保存在 `.goose/out/session-storage-clean-a6cf3dcd/`。Source/配对/解压阶段未执行，启动取消根因尚未证明，不能重跑未改候选或签收。
