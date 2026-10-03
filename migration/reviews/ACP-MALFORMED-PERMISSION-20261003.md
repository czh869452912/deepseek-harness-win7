# ACP malformed permission 的精确原版缺陷审阅

目标 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，源 `reference/packages/acp/acp/src/index.ts` 的一次性 approval/request handler（154 行起）。它先仅检查 outcome.outcome 是否 cancelled，再按 optionId 是否 allow-once 授权。固定 SDK 1.4.0 对返回结果没有响应 schema 验证；response 判别字段 unknown 或缺失时仍可进入授权分支。这违背同一源码注释“unknown client response 不推断 durable grant”的意图，并且不应作为 Python 的合法授权行为复制。

真实原版 Harness / Agent factory / ApprovalService / SDK 字节通道在两种响应上得到 allowed-once：`{"outcome":{"outcome":"unknown","optionId":"allow-once"}}`，以及 `{"outcome":{"optionId":"allow-once"}}`。Python 对这两种响应得到 unavailable，工具不会执行。其余 allow/reject/未知 option/cancel/missing outcome/null/remote error/同 id 外来 Agent/缺失 callId/pre-abort 十种观察必须完全相同。

专用源观察器仅将测试 entropy 固定为一个合法 UUID，方便比较相同输入的实际身份字段；不修改固定源码、协议错误或响应。两侧完整 request/update/response、判别结果、update-before-request 观察及 audit correlation 属性均保留；没有删字段或归一化后比较。实际 canonical Agent→工具→permission→下一模型请求另行验证，源 observer 的单个 it 不是十二个原样上游 assertions。

允许差异唯一执行权威为 `scripts/acp_permissions_oracle.py` 的 `reviewed_malformed_outcome_difference`：仅上述两个具名 mode、固定恶意响应、精确请求身份/选项、完整 committed update、真实顺序、双条 correlated audit，以及 source allowed-once / Python unavailable 才返回 true。缺字段、顺序丢失、其他响应、其他授权结果、审计不同或任何新 mode 均拒绝；原始差异标为 reviewed-original-defect，绝不改名 matched。已有八类 bug 和 C58 predicate 均不修改。

这是实现中已审阅的限定安全修复；仍须通过生产反例、完整 Python 3.8、干净候选与实际 Portable 验收后才能签发 `CON-ACP-PERMISSIONS@1` integrated。完整 MCP / subagent / ACP 不随此审阅完成。
