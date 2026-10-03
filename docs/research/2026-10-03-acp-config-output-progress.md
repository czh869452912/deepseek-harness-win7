# ACP 模型配置与输出接入进展

目标固定为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。本部分为 `MIG-ACP-CONFIG-OUTPUT-004` / `CON-ACP-CONFIG-OUTPUT@1`；A1 和 A2 仍待完整干净候选验收，父 ACP 任务仍未完成。

## 实际变更

按原版 model-control/content/updates/session 迁移 provider 分组与完整 route selector、推理选项、缺失目录/路由退化、串行失败恢复、prompt admission 快照、精确 claimed turn pin 和 committed output tail。模型显示出的默认 effort 不写回 Agent-owned selection；输出与恢复不修改浏览器、不使用旧 SSE carrier。

prompt 全量验证 content 后一次性保存 images，晚到取消不能 enqueue user。assistant conversion 错误仅进入其精确 prompt；tool-result supplemental conversion 失败被包含；通知 transport 失败不假冒 conversion 失败。prompt 和 close 都等待 committed output 排空，close 先终止未完成 admission，再 flush/dispose。

真实 canonical 旅程发现两个提供端接入问题，失败日志均保留于 `.goose/out/acp-next/`：恢复 setup 错用 service `get('agent')`，而 canonical factory 用 scoped Context attribute 携带未发布 Agent；AgentLoop 直接准备 stream 而未解析模型默认 controls，LLM 又把未实际 materialize 的默认标记写入 header，导致真实恢复校验拒绝。修复 scoped ownership、prepared controls/header provenance，并只使用已解析的模型 contextWindow。旧 LLM 单测对 false 默认标记的预期按原版 `llm/src/index.ts` 的稀疏 true-only 规则修正，没有登记为原版 bug。

另补 admission 快照先于异步 worker 调度的反例，避免模型变更抢先影响已接受 prompt。完整 prepared-call 单次 dispatch/registration trust 属后续 LLM/Wire 正式合同，不由这里的部分接入推定已完成。

## 验证边界

八个原样源语义观察为 absent、catalog、unlisted、defaults、outage、serialized、pin、updates；比较完整选中字段、raw JSON、message ids、usage/capacity 和 default ownership，独立校验空/缺失/重复/损坏观察。A1 八个 lifecycle 观察仍 matched。

真实 JSONL/SQLite canonical AgentLoop 执行模型→实际 echo 工具→下一请求；首 prompt 两个 step 使用同一 admitted route，后续 prompt 才切换 provider/model/effort。验证 committed message ids/输出顺序、同 id Session impostor、live resume 与新 Context resume 不重播输出。另测初始 option failure 事务回滚、取消 observer、异步 image admission、conversion failure、close output drain。

统一门禁现在包含 26 个配对驱动、5 组原样源测试、5 条原版 browser lane 和 5 条 Portable lane。未实际执行的干净门禁不签发 passed/integrated；此前 A1 clean gate 的五条 browser teardown 失败已保留，并由独立提交 `bd937655` 修复。Win7、真实远程 provider、stdio/MCP/subagent 均未认证，accepted_upstream 保持未建立。

冻结前专项为 201 passed；补充最终 ownership 再验 48 passed，两个正式 paired 驱动各 8 modes matched。迁移记录重复文件读取性能问题已另作修复，28 个工作流校验测试及 check/status 通过；不以这些专项替代全量回归。
