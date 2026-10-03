# 当前浏览器观察器卸载修复

固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，ACP 实现候选 `3f9645d2`。首次 clean candidate prepare 通过，但完整回归 **4865 passed、5 failed、6 skipped、1 既存 warning**。五条必要 browser lane 均在观察器删除专属 profile 目录时遇到 EBUSY，不能签发此候选通过；完整失败日志与 JUnit 保留于 `.goose/out/acp-controls-clean-gate/`。

单独 Host 观察器复现同样的 EBUSY；通过进程表确认同一专属测试 profile 的实际 Edge 及其子进程仍存活。启动器 exitCode 已变化不代表浏览器退出。原先以启动器存活作为发送 Browser.close 的条件，导致漏关。现在根据实际 CDP 连接发送 Browser.close，等待协议断开，再确认启动进程结束；关闭失败仍使报告失败。目录清理失败也保留 JSON 原始诊断，不再在写报告前抛出并丢失所有旅程证据。Portable 同一观察器职责一并修复；不是修改原版浏览器代码，也不是忽略 EBUSY。

四个受控反例覆盖已退出/仍存活启动进程以及实际协议能够/不能断开的组合。真实五条 browser lane 第一次复验为 **18 passed、1 failed**：最后卸载页面的引导操作又触发异步读取，观察器未等其完成即开始下一步。补充引导后的有限请求排空及最终业务断言前的排空，保持原有 console/request 失败断言。第二次专项 **19 passed**，原始失败与修复结果分别见 `.goose/out/acp-next/browser-close-fixed.xml` 和 `browser-close-settled.xml`。

失败测试遗留进程仅按本次失败日志中的精确专属 profile、Temp 父目录、msedge 名称与再次读取的命令行核实后回收；没有全局终止浏览器。该清理不属于产品运行时，也不构成 Win7 认证。

ACP controls、实际解压 Portable 和新候选完整门禁仍待统一验收。旧失败保持失败状态，不增加原版 bug 例外、不重写现有八类精确 predicate。
