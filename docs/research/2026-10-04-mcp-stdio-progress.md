# MCP stdio 与生命周期迁移进展

目标固定为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，本单元起点为 `a8926c52`。本记录报告实现部分，`MIG-MCP-STDIO-007` 保持 running、`CON-MCP-STDIO@1` 保持 specified；整体 accepted_upstream 仍为空。

## 已实现并验证的第一部分

stdio 提供端现在启动真实受控子进程，执行固定 SDK 的 initialize/initialized、实际 tools/list 和 tools/call；缺失程序、断连和协议失败不会生成虚构工具成功。请求关联、错误 data 的缺失与 null 区别、通知、取消、超时、环境清理及 EOF 均有原始进程观察。关闭先收回 stdin、等待或终止进程，再排空请求与读写任务；延迟 spawn 的进程在 connect 取消或同时 dispose 时仍由提供端收回。

插件异步激活等待首次连接和工具发现，命名空间按 Cordis 注册 scope 或 root 保留，卸载释放。supervisor 串行处理同步、保留上一组成功工具、限制重连预算，并在卸载时等待连接/同步工作。新增读取后代际检查防止结束的 generation 再发布工具。上述 supervisor 用例是本地回归，尚未完成完整双侧行为认证。

统一开发预览 `.goose/out/mcp-stdio-diagnostic-preview` 通过：Python 3.8.10 全量 **5172 passed、6 skipped、1 warning、0 failed**，28 条必需 lane、七组 **722** 项原样源码断言、29 个双侧驱动，以及实际解压 Portable 运行通过。MCP 驱动的十一组原始观察精确匹配；包内 embedded Python 确认模块来自解压根目录，实际 ToolsService 执行后工具撤回、子进程退出、pending=0。产物 SHA-256 为 `0d64cf009da438425234fd6fe0df4ac9e50966465e1e518c5a73fdcd046d920b`，完整输入清单 SHA-256 为 `51ef2a03b8700188e1afac26ef03ee1f7bd5d06365caab2b83f2c736f15d50e5`。

预览明确为 `development-preview / publishable=false`，不能签发 verified/integrated 或替代提交后的干净冻结验收。MCP 的提供端、必要回归和包内观察已加入统一 gate；观察器反例拒绝丢失、重复、损坏、假退出与外部模块来源。

## 失败与未完成项

之前 `.goose/out/mcp-stdio-preview` 以两条必需原版浏览器旅程失败结束，5170 通过；失败记录全部保留。后续并发复现发生在启动阶段：同一 loader 的 inspect/inventory 等请求和 HMR SSE 被取消，时间早于后续导航。目前未确定根因；没有忽略 console error、增加重试、修改原版前端或登记原版 bug。观察器增加请求/文档 loader、时间、导航命令、页面 lifecycle 与 HMR 记录，后续成功运行不能证明该偶发问题已经修复。

Proactor `Event loop is closed` warning 及 HTTP 10054 旧诊断仍保留，未归因，不宣称清理完成。原版九类已审阅 bug 和 C58 判据未改；本次发现的迁移差异不进入原版例外索引。

第一部分仍有 SDK schema/config 缺口：logging 数组被误拒、experimental 非对象未拒、annotations 未验证、properties 的数组对象被误拒，以及 tool 未知字段未按 SDK 投影。隔离工作树已形成四个固定 SDK schema 的原始抽取、959 组解析与错误消息观察、176 组配置/重连观察及二十组实际进程观察；278 项针对性回归通过，但这些后续实现尚未纳入本次主版本候选。

下一单元合入上述 schema/config 和工具桥修复，再补齐 supervisor、富内容/图片持久投影与真实消费者证明。HTTP/SSE 仍是待替换占位；ACP mcpServers mounting-before-publish 与 subprocess subagent-acp 尚未实现。B/C/D、fresh uncached bootstrap、Win7 和外部服务验收继续保留各自退出条件；完整 ACP 与全部迁移没有闭环。
