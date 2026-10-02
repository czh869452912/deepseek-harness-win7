# ACP prompt 归属闭包推进：2026-10-03

固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；对照 `packages/acp/acp/src/index.ts` 的 ownedRecord/ownsSession 和 `session.ts` 的 messageId/turn/endReason 结算。此项是迁移版 bug，不能登记为原版例外。

## 已修复的有界范围

- Session 精确对象与 Agent 精确对象校验；相同 ID 冒充对象不拥有记录。
- inbox claim 只关联该 ACP 消息 ID；turn/end 只更新同一已认领 turn，忽略邻居、旧 turn 和未认领事件。
- prompt 先建立本地身份，结算等待 Agent idle，取消标记优先于迟到 completed；durable turn error 和 interval error 返回失败而不是假 end_turn。
- enqueue / idle / turn / interval 异常均在 finally 清理该身份的槽位，避免下一次 prompt 被遗留的 in-flight 状态锁死。
- `run_profile` → Loader → 实际 AgentRegistry / AgentLoop → inbox claim → turn/end → 关闭的集成测试通过；仅 LLM 替换为测试 adapter。

## 验证与限制

- 四个原始探针修复前 **4 failed**，修复后 **4 passed**；日志 `.goose/out/acp-work/before.log` / `after.log`。
- ACP 专项 **27 passed**，无新增 warning；JUnit `.goose/out/acp-work/ownership.xml`。
- 固定原版 **11 个测试文件、139 passed**，日志 `.goose/out/acp-work/official-acp-url.log`。观察器安装目标版本 ACP SDK 1.4.0 / MCP SDK 1.29.0 / Zod 4.4.3 于 ignored 临时目录，通过独立 resolver 让原样 stdio fixture 找到 SDK；没有修改 reference。早期 SDK 路径失败日志保留，不能误报成原版业务 bug。
- 139 项是上游源码基线，不等于 139 个已迁移 Python ACP 用例。本任务 `CON-ACP-PROMPT-OWNERSHIP@1` 只覆盖上述 handler/Agent 生命周期范围。
- 根因修复后的冻结完整预览 **4800 passed、6 skipped、1 个既存 warning**；四组原样测试、24 个双侧驱动和实际解压 Portable/browser 门禁通过，见 `.goose/out/p0-acp-final-preview/`。预览始终不可发行；按用户授权独立提交后还须 clean candidate 验收，任务保持 running。

后续已完成独立实现提交 `b85e03f8`，并在干净产品候选 `623a615a34d6e81a0d6fc9230c836a12017ba65c` 通过完整统一门禁 **4800 passed、6 skipped、1 个既存 warning**。有界任务已 integrated；`RUN-CURRENT-20261003-ACP-PROMPT-OWNERSHIP-001` 绑定候选、acceptance 摘要、范围输入及版本化证据包。上段 preview/running 为历史阶段，不能替代本段候选验收。完整协议后续单列 `MIG-ACP-TRANSPORT-002`，不把归属修复扩张成协议全量完成。

完整 ACP 仍未完成：stdio JSON-RPC 注册、initialize 的标准协议版本/能力、输出排序与排空、SDK 请求 signal、session list/resume/close/config、MCP 和权限请求，以及 ACP subagent 消费者需要独立闭包。既有 additionalDirectories 拒绝与 authenticate 空行为原版也存在，不误报为缺陷；不以 codec 或此处归属修复冒充全协议迁移完成。
