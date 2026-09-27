# Cordis 真实消费者闭包

新增 profile 全链路回归：run_profile → 配置 Loader → Session/Tools/SystemPrompt/Agent/AgentLoop/JSONL 产品插件 → 工具调用 → flush → 全树 shutdown → 新 Context 启动 → resume → 模型请求保留原工具结果。仅模型输出 mock，不替换核心服务或持久化。

必要消费者审核发现 agent-presets 缺少上游 invariant companion。补齐动态全局服务泄漏检查与未加入 preset 的 agent 模型请求拒绝；冷读、已加入 agent、空 roster 允许；卸载 companion 后移除其监听。按包子路径注册 Loader 入口，未把 companion 强行加入默认 profile。

专项 tests/test_profile_spine_recovery.py、tests/test_agent_presets_invariant.py 均通过。完整候选验收后另附报告，不以专项替代总体证明。
