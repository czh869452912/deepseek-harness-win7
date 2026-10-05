# 工具 dispatch 启动前缀

前一干净产品 `1f180e40` 已通过存储/并发批次完整验收；本部分不改变该历史签收。新任务 `MIG-TOOL-START-PREFIX-034` 仍 running，完整 Tools/Wire 和全项目未闭环。

## 实际差异与修复

固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc` 的调度器立即执行 dispatch 的同步前缀，再准备后续调用。原生版本仅登记 asyncio task，填池时可能尚未进入 dispatch，因此八组受控观察全部不同：后续 pre-execute 看不到先前前缀，前缀取消后自定义 dispatcher 仍可能多开调用，第二次同步抛错时也可能准备/启动第三次调用。

修复在登记 in-flight task 后等待该 task 设置 admission Event。task 自然运行到首次挂起，随后调度器才继续；不使用 sleep、协程手动推进或任意超时。既有首错保存、已启动工作排空、结果顺序和独占屏障仍由原调度器负责。

## 已执行验证

真实 Source 的 canonical body/custom future × ordinary/abort/reclassify/throw 八组观察与修改前/后原生记录分别在 `.goose/out/acp-a4-work/tool-start-prefix-{source,native-before,native-after}-v1.json`。修改前八组不同，修改后八组完整对象相同；失败对象身份、释放 owned future 前未完成、调用/结果和 prepare 快照均保留。

正式 helper 已接入既有 tool_scheduler 双侧驱动，由22扩大为30项；支持选定产品 root 的 Python observer，新增 helper 输入也进入实际解压回执。41项定向回归通过，日志及 XML 为 `.goose/out/acp-a4-work/tool-start-prefix-focused-v1.*`。新增八条实际原版配对回归均列为 mandatory，下一完整门禁要求452 lane / 十八组1237原样 Source断言 / 54配对。

隔离 `python -I` 检查发现新增 observer helper 的导入路径未显式提供，保留失败预检并补齐开发观察器自身目录；选定产品 root 仍优先，helper 输入与产品模块分别哈希。修正后隔离原生观察通过，正式双侧30项 matched；门禁验证与既有模型/便携消费者592项通过（203.83秒），记录为 `tool-start-prefix-gate-v3.*`。v1选错测试路径、v2导入失败诊断均保留，未计入通过。

干净产品 `6ceef0f9` 现已完整通过：6944 passed、6既有 skips、1既有warning、0 failed；496必需lane、十八组1237原样断言、55实际配对和真实解压/原版浏览器通过。034有界 integrated，三十组scheduler实际Source/native/extracted及四十六份当前任务证据归档于 `migration/evidence/artifacts/TOOLS-HTTP-20261005-6ceef0f9.zip`，见对应review。未增加 Source bug 绕过、跳过或重跑未改候选；任意 task 取消/disposal、所有 Tools/Wire 组合和扩展 ABI 仍独立开放，Win7实机按用户决定延期。
