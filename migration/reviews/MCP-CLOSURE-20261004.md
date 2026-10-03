# MCP stdio / HTTP 有界验收

固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。产品候选 `8a17485d0f43bb7318700053fd0d2d7149c96c95` 干净冻结门禁 passed / publishable=true；`CON-MCP-STDIO@1`、`CON-MCP-HTTP@1` 只按各自有界提供端合同 integrated。整体 accepted_upstream 仍为空。

## 结果与真实性

完整 Python 3.8.10 回归 **5408 passed、6 skipped、1 warning、0 failed**，1154.06 秒。51 条必需 lane、30 个当前配对驱动、七组 722 项原样源码断言全部通过。原版断言数量 80/100/197/100/139/3/103 只证明该源码基线已运行；Native parity 使用单独的真实双侧观察与消费者证明，不按测试数量推定。

MCP stdio 二十组真实原版 factory/SDK 1.29.0 与 Native 进程观察匹配；四个选定 SDK schema 的 962 组原始 parse/error、176 组 config/reconnect、38 组工具桥以及九组 supervisor 和真实 SDK 工厂失败 close barrier 回归通过。实际 ToolsService、durable image 存储及冷读模型请求消费者通过，没有外部模型调用。上述 schema 是四个选定导出，不是全部 SDK schema；source supervisor MockClient 观察与真实 SDK close barrier 证明分别记录，不能相互替代。

HTTP 十六组真实原版 transport factory/SDK 与 Native 原始请求/响应、错误和取消字段匹配，有界 literal specification 及反例检查通过。GET admission 与 cancel notification admission 是声明的受控观察输入，未声称并发网络请求自然有固定到达顺序。实际 close 回收所有客户端 task/writer/pending；explicit terminate_session 与 close 是否 DELETE 按原版区分。

真实发行 ZIP 解压运行 Python 3.8.10，二十组 stdio 和十六组 HTTP 原始观察、两条实际工具注册/执行/撤销/关闭消费者通过，子进程已退出，HTTP writer/task/pending 为零。既有 runtime 十三步、原版浏览器五步、ACP 两进程九步、权限六进程及 119 个 frontend 输入通过，原版 browser 文件未改。

## 收据与归档

发行 ZIP SHA256 `655fc9fd03b165259c15b44138baf3dfe2759541f386e20cd5c19489941b862b`。
冻结输入 manifest SHA256 `2bc029df3c42cf02147917e5676a7a12245337241be17592829ddce7b976c898`。
证据包 `migration/evidence/artifacts/MCP-20261004-8a17485d.zip` SHA256 `8d615bcc422d10dfe959181a38477be4de1116ea5022943feb4fc63b26cc3ac9`，包含干净完整门禁、原始双侧输出、所有 prior previews 与相关诊断失败。收据、实际 ZIP、输入 snapshot 和 archive 内收据逐一哈希验证，18 份证据只重签各任务的原有有界合同。

归档也含隔离 ACP MCP 开发观察，明确不属于本产品候选；本验收没有 ACP mounting 或新 ACP capability 的产品字节。后续 ACP 部分需独立提交和新的完整/实际解压验收，不能引用此包将原型认证为 integrated。

## 遗留限制

先前 dirty preview 一次 5407 passed/1 browser failed，以及较早两次 browser startup 取消，均保留。六个启动 HTTP/SSE 请求在文档 load 附近 ERR_ABORTED，早于下一受控导航；根因未确定。本次干净门禁通过不证明故障修复，不忽略 consoleErrors、不增加重试，也未登记为原版 bug。既有 Proactor event-loop-closed warning 和 post-suite HTTP 10054 仍保留未归因。

HTTP TLS、redirect、compression/WHATWG URL、resumable SSE/replay 与重试耗尽、supervisor late-fetch/dispose 与 factory-rejection/dispose 等未覆盖边缘保持独立开放。当前源码后继移植不可扩大这两个合同的范围。ACP mount-before-publication、subprocess subagent-acp、B/C/D、fresh uncached bootstrap、外部真实服务/remote Actions 和用户延期的 Win7 真机/目标浏览器仍未认证。九类原版 bug 审阅判据不变。
