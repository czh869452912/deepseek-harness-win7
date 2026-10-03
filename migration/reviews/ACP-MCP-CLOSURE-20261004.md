# ACP 会话 MCP 有界验收

固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。干净产品候选 `e24fe1dbeaa804553179cdace7bc46703073682e` 完整冻结门禁 passed / publishable=true；`MIG-ACP-MCP-009` 和 `CON-ACP-MCP@1` 按声明的会话 MCP 范围 integrated，整体 accepted_upstream 仍为空。

## 结果与范围

Python 3.8.10 全量回归 **5508 passed、6 skipped、1 warning、0 failed**，JUnit 总耗时 1188.923 秒。62 条必需 lane、七组 722 项原样源码断言、31 个双侧驱动和严格 Cordis 差异门禁通过。源码基线断言不是 Native parity 数量；会话 MCP 的证明来自新鲜双侧原始观察和实际消费者。

58 组声明映射的配置、默认值、错误、环境、header 与选定 URL/名称归一化字段匹配。真实原版 ACP handler、SDK/子进程和 Native canonical factory 的作用域工具消费、双会话隔离、关闭与重新挂载匹配。Native JSONL/SQLite 与 HTTP 消费者、完整声明预验证零 spawn、第二个启动失败回滚第一个子进程，以及调用方/bridge 取消后的迟到初始化拒绝发布均通过。

真实发行 ZIP 解压并运行其自身嵌入 Python，实际 canonical ACP 进程完成八次本地模型请求，执行三个 stdio 子进程的三次工具调用和一次 HTTP 调用；独立进程句柄证明三个子进程退出，HTTP 与 ACP 正常关闭。既有二十组 stdio、十六组 HTTP、十三步 runtime、五步原版浏览器、两进程九步 ACP、六进程权限及 119 个原版 frontend 文件哈希检查通过。无外部模型调用，原版前端没有修改。

## 候选与证据

发行 ZIP SHA256 `302f72437357b63410c5ae4c9341a667f7d4ced57ad9ca280fac077a49fcd9d1`。
冻结输入 manifest SHA256 `380f2c914dc8b8831ce34b12c93a44d5375825674f3c005608a8174a37f520a4`。
证据包 `migration/evidence/artifacts/ACP-MCP-20261004-e24fe1db.zip` SHA256 `47af12513631b1b97c594cba0aa0201d7f1c2280d8a5b54cc6384569030ec926`。

十九份验收记录分别绑定任务原有 acceptance 摘要、合同 revision、精确产品提交及产品输入。归档包含干净门禁、未提交预览、原始 wire/进程观察与相关失败；ZIP、输入、收据及归档中的收据逐项校验。包内第五部分隔离 subagent 原型、取消信号诊断与 browser netlog 属于未来开发观察，不是该产品候选字节，也不由此验收认证。

## 保留限制

阻塞初始化取消的双侧证明使用显式迟到握手释放屏障：原版 Cordis 等 apply 惯性结束后才运行 disposer。没有证明无限无响应 initializer 即时退出，也不将历史十秒 shutdown 超时登记为原版 bug。完整 WHATWG URL/Unicode、其他 HTTP SDK/TLS/redirect/replay、subprocess subagent-acp、B/C/D、fresh uncached bootstrap、外部真实服务与用户延期的 Win7 真机认证保持开放。

先前 browser startup ERR_ABORTED、既有 Proactor warning 与 post-suite HTTP 10054 保留未归因；本次通过不声称这些故障已修复。九类原版 bug 审阅判据不变。下一部分单独提交实际 subprocess ACP 后端及真实模型取消信号修复，再执行全量与解压候选验收。
