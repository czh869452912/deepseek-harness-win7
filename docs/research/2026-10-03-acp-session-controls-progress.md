# ACP 持久 Session 管理进展

目标原版仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；前置产品 `5a3347d1ee98e828de0bbcce90c7b63880fe7532`。完整遗留项计划已提交 `7e558aff`，见 `2026-10-03-full-migration-closure-plan.md`。

## 本单元实现

- new 使用实际 Agent/Persistence/Session 服务，UUID 身份与 owned handle 校验、空历史 materialization、激活失败或迟到 closed 的清理；不再无 Agent 假成功。
- initialize 使用固定 SDK 1.4.0 的稳定 **整数 1**，只增加已经实现的 close/list/resume 能力；MCP 尚不宣告可用。
- list 仅暴露非活动、非 activating、非 subagent/child 的持久记录；newest-first、UTF-8 id tie-break、严格 canonical base64url keyset、正 safe-integer page limit、物理/词法 cwd 对照。
- resume 在 await 前保留 admission，拒绝活动/未知/子 Session/错误 cwd；失败释放保留槽、late closed 不发布，实际 factory 接收组合的请求/bridge signal。
- close 共享 memoized 操作，禁止新的 prompt；取消先于 idle/后代/flush/dispose，任何阶段失败仍继续所有清理；观察者取消不能提前释放 record。Bridge unload 先取消全部 owner，再汇总清理错误，不再吞掉诊断。
- JSONL/SQLite 的 canonical `run_profile`、AgentLoop、LLM 测试 adapter、关闭后 list/resume 和新 Context 恢复已经执行。原版也添加的单个 end-seed 恢复标记按类型/seq/data 校验，不删除或归一化历史差异。

## 当前实测

- 同一个反例脚本对 Git 前置 `server.py`：**4 failed**；当前实现：**4 passed**。覆盖整数版本、缺 provider 假成功、空 Session 持久化和 close/list/resume。原始前置文件 SHA256 `665fdaa71b3c5fb818b00deaa2c2626a351a30bb5b25d434d4edb963de8d5de0`；位于 `.goose/out/acp-controls-before/`，不是原版 bug。
- 主要专项 **126 passed**，含前置 prompt ownership、strict observer、发行 helper；`.goose/out/acp-controls-targeted-final.xml`。另有 approval/MCP 既有单测专项通过，但它们不证明 ACP MCP 挂载完成。
- **8 个双侧观察 matched**：empty、pagination、filter、cursors、resume-refusals、reservation、shared-close、close-failure；`.goose/out/acp-controls-paired.json`。raw list/cursor 精确比较；随机新 ID 在每侧验证同一 owner，未知 error-envelope/config/output/MCP 不冒充全字段 wire parity。
- **11 文件 / 139 个原版 ACP 测试通过**；`.goose/out/acp-controls-source.log`。正式加入 pinned 开发依赖 ACP SDK 1.4.0 / MCP SDK 1.29.0 和独立 resolver，原版代码不修改；全部属于开发观察器，不添加 Portable Node/SDK 依赖。
- 配对最初暴露 reservation 观察错误：SDK 会将普通 factory 异常转换为 generic internal error；先前误用客户端 message 判断是否到达 factory。现在记录实际调用数与拒绝事实，且 strict observer 不接受 false/缺项；没有更改源行为或添加例外。
- 初次开发依赖安装的相对 prefix 失败属于安装环境，不是原版业务 bug；固定以对应 lock workspace 为 cwd 运行 npm ci，并有拒绝缺包管理器与工作目录回归。

冻结统一 gate 现在包括 **25 个双侧驱动**和 **5 组 / 616 项原版源测试**。首次 prepare 在 Python 3.8 自带 pip 21.1.1 的 TLS `check_hostname requires server_hostname` 处失败，日志保留 `.goose/out/acp-controls-preview/installer.log`。使用 uv 将本项目 venv 的 pip 升至同一既定 pin 25.0.1，未禁用 TLS 或修改全局代理；第二次 prepare 已通过。此环境引导仍需 D2 的无缓存安装验收，不能据此宣告干净开发机安装完成。

第二次预览在约 51% 的 Python 回归时被用户中断，没有 summary 或完整 JUnit，不能作为通过证据。按新的继续指令先提交专项验证过的实现作为候选，再冻结干净候选执行完整门禁。正式证据之前 `MIG-ACP-SESSION-CONTROLS-003` 保持 running；候选提交不等于本单元已经验收。

## 明确未完成

该单元不等于完整 ACP。模型配置/turn pin、ordered committed updates/输出排空、真正 acp-app stdio/EOF/request signal、MCP/一次性权限和 subagent-acp 必要消费者仍依计划 A2/A3/A4 推进。list 的持久 provider await 尚不是整个 wire request 的即时取消认证。Win7/真实远程模型/远程 Actions/发布均没有在本机被认证。

总体 accepted_upstream 不设置；后续必须继续完整 profile 组合、长历史/业务状态、Wire/Tools 正式合同、JS/OAuth/SDK/插件治理和目标平台的具名退出条件。
