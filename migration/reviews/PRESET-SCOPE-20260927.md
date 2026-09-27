# Preset scope 提供端与消费者修复

逐项读取官方 mount.spec.ts 发现 Context 祖先与注册 scope 父关系被混用。旧 Python mount 改写 agent_ctx._parent，standing 注册没有独立 scope，导致工具进入全局层。两个新测试在修复前失败，原日志已保存。

现在 standing composition 由 create_scope 拥有，mount/composeFrom 用 bind_scope_parent 绑定，recompose 持有原 binding 的 rebind 权限，Context 父链不变。standing_mount_for 从 scope 父关系读身份；无 scope 的 ctx.extend() 被拒绝。重新组合提交后发送 tools/change，监听器失败不回滚成功的组合。

实际消费者 AgentLoop 同步创建路径此前忽略异步 setup。现 create_agent 为 async，create/resume 都创建并拥有 scope、等待 setup/commit；失败清理 scope，恢复失败撤销 session attachment，新 session 等 setup 完成后发布。模型提示与 schema 使用同一 scope key。所有仓库调用者均使用 await 或通过 AgentRegistry 的 awaitable 适配。

新增真实 Session/AgentRegistry/AgentLoop/Tools/Preset 测试，仅 mock LLM，验证异步 preset setup、模型工具隔离、失败创建的 agent/session 清理。子 scope 保持同代 composition，父 scope 卸载不回收 standing mount。

专项日志与随后完整回归分开保存。本修复不自动完成 mount.spec.ts 全部 50 项语义验收，剩余的逐项对应仍须如实登记。

官方 mount.spec.ts:714 的确定性竞争用例进一步复现了 C58 的实际影响：已完成 standing Future 的 await 不让出执行，旧刷新提前创建第三代。现在仅当进入 await 前 Future 已完成时增加 checkpoint；等待未完成 Future 不额外让出。竞争方的新指针保留，双会话刷新共享新代，子 scope 继承已删除文件对应的父代。修复前/后日志分别保存。
