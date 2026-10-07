# 官方构建与公共 Schema 的旧消费者收敛

干净提交 46c8d4e1 的完整门禁收集 10007 项，在早期出现旧测试失败。协调器主动停止已核验的专属进程树，未生成完整 pytest XML 或正常门禁结果，不能计为全量通过。冻结输入、原始日志、精确候选 ZIP 和旧测试字节保存在 `migration/evidence/artifacts/OFFICIAL-FRONTEND-INTERRUPTED-20261007-46C8D4E1.zip`，SHA256 `38f94b795dde27baa6bdfa70089166332827975c7fe1381120c6d9b08fbf9258`。候选 ZIP SHA256 `401dd2f203a51133c02e7f3d389a57884166ac039432a4fd55081ad92adf3ce5`。未结束工作区保留，不进入自动过期清理。

独立旧消费者基线 107 项得到 103 passed、4 failed。两处仍把未构建文档的 DSH Local Build 标题要求应用于官方构建；固定原版 Vite 的 clientDocumentTitle 转换实际产生 DeepSeek Harness。另两处仍按整数索引公共 Schema refs，违背 JavaScript 对象的字符串键。修正消费者预期，保留源文档本地标题、整数 uid 与节点关系要求，不修改原版浏览器代码或放宽严格 JSON 编码器。

291 项 apps_web、设置、Schema、进阶 Cordis 和真实认证 HTTP 回归通过。四处消费者均纳入完整门禁必需项；32 项控制从完整正例开始，分别验证省略、跳过、重复和失败不能签收。11 文件工作树资格归档为 `migration/evidence/artifacts/OFFICIAL-FRONTEND-CONSUMERS-20261007-46C8D4E1.zip`，SHA256 `afdbaaa1d5d9fb936a4d9637eb2577eadc7b38c90fa819fc53bd76b9a511dd99`。

本部分只关闭旧测试预期与已有提供端修复之间的冲突。最新完整签收仍为 83026446 的 65 个有界合同。后续以新干净提交重新执行正常预算完整门禁、全部配对、原样 Source、真实解压及原版浏览器，七个父范围与用户延期的 Win7/目标浏览器认证不自动关闭。自动维护继续使用完成记录、归属及双散列判据，不清理未知、变更、活跃或真实证据。
