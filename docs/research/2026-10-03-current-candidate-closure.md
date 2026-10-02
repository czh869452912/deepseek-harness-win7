# 当前候选闭包与未完成项

本记录对应本机实际执行日期 2026-10-03；目标原版保持 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，未修改 reference 或上游前端。

## 分部分提交

用户授权每完成一部分提交一次；未推送、发布、新建分支或启用多智能体。

| 部分 | 提交 | 完成范围 |
| --- | --- | --- |
| 当前发行门禁初版 | `134a6fd6` | 无凭据原版 onboarding、必需 lane 防跳过、选定双侧门禁、实际 ZIP 解压验收、严格回执上传 |
| HTTP/观察器根因修复 | `b15aff84` | 一次请求后关闭的 socket 必须声明 close；去除冲突头；等待新文档而非旧 DOM，完整错误断言保留 |
| ACP prompt 归属修复 | `b85e03f8` | 精确 Session/Agent/message/turn，取消与迟到结果，异常槽位 finally 清理，实际 profile/AgentLoop 回归 |
| 八类原版 bug 索引 | `623a615a` | 统一索引既有精确谓词及审阅记录；不是新跳过列表，C58 独立语言适配 |

**干净产品候选：`623a615a34d6e81a0d6fc9230c836a12017ba65c`。** 后续台账提交只归档证据与计划，不冒充此运行的冻结输入，也不重建已经验收的 ZIP。

## 实际验收

```powershell
.venv\Scripts\python.exe scripts/verify_release.py --browser "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --output-dir .goose/out/p0-acp-clean-gate
```

- 回执 **passed / publishable=true / worktree_dirty=false**，源输入、产品 HEAD 和 reference 末尾检查一致；开发 Node **22.22.2**、Python **3.8.10**、当前 Windows/Edge。
- 全量 **4800 passed、6 skipped、1 warning，1042.57 秒**；五条原版浏览器和五个构建 Portable profile 用例全部执行。六个跳过为四项符号链接权限与两项 POSIX 语义，必需 lane 无跳过。
- 四组原版 Vitest：80 + 100 + 197 + 100 = **477 passed**。源码断言数不等于 Python parity 数。
- **24 个双侧驱动通过**现有精确门禁；Cordis raw 保留 **66 matched + C58 different**，精确语言适配 acceptance 通过。未过滤、放宽或新增原版例外。
- 实际中文/空格路径解压：内置 Python **3.8.10**、**13 步** runtime 旅程、**5 步**原版 browser 旅程、**119 个**前端文件校验；runtime/Host/browser 错误字段为空。
- 产物 `dist/dsh-win7-portable-v0.1.0.zip`，SHA256 **`b6fe79ebf2cf427669976d36988a1feb3002062408cc4f353cf36f02ce61c889`**；没有对外发布。

同代码的前一冻结 preview 同为 **4800 passed**，但始终 publishable=false。首次 clean gate 的 **4774 passed / 1 failed** 保留，不覆盖成成功；HTTP 关闭语义探针修复前 **4 failed**，ACP 原始归属探针修复前 **4 failed**，均有修复后验证。源码原版 ACP **139 passed** 为另外的基线，不包含在 477 中，不当作 139 项迁移证书。

## 证据与台账

版本化证据包 `migration/evidence/artifacts/CURRENT-GATE-20261003-623a615a.zip`，SHA256 `88eaa2d9014502cbbb30b8bb54cb96f085f69e85164d9ca523a190b3311a2a6e`。包内保存完整输入清单、JUnit、原始两侧观察、477 项 source 日志、当前 clean/preview 和历史失败，以及 ACP 基线/根因探针；不包含 Portable ZIP 本体。

十二份 `RUN-CURRENT-20261003-*.json` 绑定候选、任务 acceptance 摘要、contract revision、范围输入及证据包哈希：

- 当前 release/HTTP 与 ACP prompt 两个有界任务 integrated。
- Core、Agent factory/config、Session cold/live/prepared/storage/projection、Spine、Portable 十个既有合同在同一候选重验；不是把 historical/stale 记录改成 current，旧记录原样保留。
- 范围外历史任务仍显示 historical integration，不以全量 pass 自动重签未执行的独立合同。
- profile 后续任务改依赖当前 canonical 门禁，不再依赖已变更实现的历史 REPRO 安装合同；完整业务合同依然 draft，不冒充 ready。
- 全项目 `accepted_upstream` 仍为空；任务数量、manifest 数和测试数都不能作为迁移百分比。

运行后台账校验：`migration.py check` 有效；后补变更仅在 docs/migration，产品/测试/观察器/资产没有变更，27 份门禁回执、Portable 和证据包哈希保持一致。校验产物 `migration/evidence/artifacts/CURRENT-GATE-20261003-post-record-check.json`；台账/精确例外/当前门禁辅助测试另跑 **60 passed**。生成的 status 保留真实剩余 draft 与历史失效范围，不根据通过数自动解除全部业务阻塞。

## 仍未完成与推进顺序

| 顺序 | 未完成项 | 退出条件 |
| --- | --- | --- |
| P1-A | 正式 profile 模型→真实工具→下一请求，question/approval UI、取消、关闭与新进程恢复，standard/creative/PTC 共存 | 源 fixture、本地反例、HTTP/WS/browser 和解压包同旅程，非只有启停/dump |
| P1-B | 完整 ACP stdio、整数协议版本/能力、ordered updates/drain、请求 signal、持久 list/resume/close/config、MCP/权限和 subagent 消费者 | `MIG-ACP-TRANSPORT-002` 先明确共享合同；真实进程双 Session、断开/迟到/取消/恢复和提供端→消费者验收 |
| P1-C | 完整业务 projection/cache/FTS/instructions、存储与长期历史边界 | 补近期实现正式 contract/revision，损坏尾部、重载、取消重放与规模数据双侧观察；registry 合同不冒充全 domain |
| P2-A | OAuth/刷新、专属云协议、通用 JS runtime 方案、SDK/插件治理及未验收外围模块 | 各范围独立源合同、必要消费者和反例；真实付费模型需独立授权，不继承宿主凭据 |
| P2-B | 插件来源信任、公共获取、native/wheel/ABI/版本范围、升级资产保留/回退、公开发布 | 离线干净环境与失败注入，零依赖/Loader 生命周期闭包；不自动推送/发布 |
| 平台 | Win7 SP1、目标浏览器、PowerShell fallback、DLL/TLS/ACL 等 | 用户恢复先前暂缓的 Win7 真机验证后取得平台证据；当前 Windows 不替代 |

另外，完整 pytest 的既存 Proactor `Event loop is closed` warning 与结束后的 HTTP 测试线程连接重置诊断未清零，仍需精确归属；它们不是原版 bug，也不说明解压 Host 的错误字段非空。Node 式持久 HTTP/pipelining 的性能未实现，此次修复只确保现有单请求 carrier 合法关闭。

**本批次有界闭包已完成，但全迁移尚未完成。** 远程 Actions、真实远程模型、公开发布和暂缓 Win7 没有被冒充为本地验收成果；后续按上述共享契约逐部分实现、验证和提交。
