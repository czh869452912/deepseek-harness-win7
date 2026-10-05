# 完整AgentLoop模型请求

后续冻结候选afd85f4e被完整门禁拒绝：7678通过、1共享checkpoint Git路径失败、6既有skip、1既有warning，1978.05秒。真实复现 `$GIT_DIR too big`，不是完整请求字段断言失败；Source/paired/extracted独立阶段未获准执行，044不签收。精确产物/输入/XML/失败fixture归档于RUNTIME-FULL-REQUEST-REJECTED-20261006-afd85f4e.zip；短执行路径及保存映射的门禁修复通过87相关回归，现1234必需lane。见2026-10-06-release-pytest-path-progress；最新签收仍7f9e87e4。

当前最新完整签收7f9e87e4验证040至043，保留16组后续研究差异：完整模型请求中的助手消息包含Source没有的tool_calls；设置maxTokens/reasoningEffort时又携带max_tokens/reasoning_effort旧别名。037只验证具名runtime-context消息及持久快照，不能据其通过宣称其余请求字段已对齐。基线及原始Source/native/隔离fix保留于.goose/out/acp-a4-work/runtime-full-request-*，已收入上一签收证据档案但明确未签收该研究范围。

实际Source AgentLoop和canonical native LlmRuntime/LLMService执行change/clear/same/empty各四种配置（base/max-tokens/reasoning/both），共16组，比较两次完整GenerateOptions和全部持久上下文消息。仅将不透明message id作全行相关双射；tool/call id与所有其他字段/值保留，未按有利子集过滤。signal观察实际AbortSignal实例、aborted和与首请求同一实例的谓词，不以空JSON对象假定信号正确，也不扩张为完整取消/重入ABI。

隔离修复移除重复助手tool_calls和规范请求中的snake-case参数，同时在Python固定参数调用边界适配canonical maxTokens/reasoningEffort；实际legacy模型消费者收到17/high，未改完整request-object消费者。38项隔离模型/工具/下一请求回归通过。主树fresh正式16完整观察匹配，原始输出runtime-full-request-product-paired-v1；CON-RUNTIME-FULL-REQUEST@1限定上述控制，所有profile/model/任意middleware/取消/恢复竞争及完整B3/C2继续开放。

精确已签收7f9e87e4 Portable以自己的Python3.8.10执行新增16控制，全部复现上述旧别名差异；每个实际导入模块均匹配精确ZIP及未修改目录字节。原始输出/完整差分/来源为runtime-full-request-exact-7f9e87e4-baseline-v1、baseline-comparison-v1及provenance-v1。主树929项回归通过（438.58秒），包含完整请求/拒绝门禁/精确解释器、模型→工具→下一请求、canonical headless/standard/creative本地HTTP、ACP配置输出、JS消费者和实际profile冷恢复。三项固定参数消费者同时通过；原始日志/XML为runtime-full-request-focused-v1。

研究初期误await同步ctx.dispose、遗漏六个bundle metadata、误按asyncio.Event检查实际AbortSignal、在native声明AgentOptions处传dict，均保留失败日志；校正观察器后才得到完整匹配。没有修改Source算法/判据，也没有将观察器错误登记为原版缺陷。当前门禁要求1231必需lane、64双侧驱动、十八组1237原样Source断言及实际解压自有Python3.8.10/原版浏览器；独立提交和新冻结完整验收待执行，044仍running。九项原版缺陷谓词/C58/C59、accepted_upstream为空与Win7延期不变。
