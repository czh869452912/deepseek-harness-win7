# 原版与迁移版的已知差异

本文补充已确认问题及候选差异，不是完整兼容性清单。正式接受的精确 Source 差异仍以 [upstream-bug-exceptions.json](../migration/upstream-bug-exceptions.json) 及其执行判据为准。

## 创造模式运行时边界（2026-11-07）

固定原版 `a4c74a91`。审批重复附着条件已对齐；Client 定义前编译检查已补入，使用随包 Win7 JavaScript 引擎，其完整语法接受集合仍非已认证的 Node 等价实现。以下事项不因配对用例通过而视为被接受：

- **CORDIS-SYNC-TIMEOUT-001，实现已修复，验收范围单列**：每个 Run 的独立进程在初始同步求值超时后终止，真实 Context/Fiber 由主进程拥有，异步 apply 和后续 RPC 不增加该超时。原生计算、Python 循环、晚到副作用及清理有定向回归；原生休眠入口现在由能力门拒绝。可选导出宿主已复用进程边界，其固定 5 秒初始期限另有真实原生阻塞回归。这不认证任意进程代理 ABI、Win7 真机或旧发行包。
- **CORDIS-HOST-CAPABILITY-001，完整 imports/builtins 扩展已撤回**：默认 Host 仅提供计算 builtins、白名单模块与异步协调能力；文件、网络、进程、线程及定时器的普通入口被拒绝并指向 Context。`eval/exec` 保持受限 builtins，`compile` 仅编译；这不表示原版或迁移版承诺恶意代码隔离。
- 多 manager 内置 Inspect provider 共享租约是本机修复；可选导出/发行属于额外设计，默认未挂载。它们不计入原版一一对应。Creative 自带技能资源在启动层按包名/路径定位的耦合仍为设计债。

最新状态见[创造模式后续收尾](research/2026-11-07-creative-closeout.md)；[进程边界修复与闭环复核](research/2026-11-07-creative-host-process-and-parity-audit.md)和[前轮边界分类](research/2026-11-07-creative-win7-runtime-boundaries.md)保留当时输入和未修复状态。本轮不新增已接受例外或变更迁移资格。

当前完整资格绑定干净候选 `e6443396`：19,481 项 Python 通过、6 项既有平台/权限跳过，21 组固定 Source、82 个配对驱动和实际解压 x64 Portable/现代及108浏览器全部通过；见[精确检查记录](research/2026-11-07-creative-closeout-checks.json)。该结果关闭本轮具体实现和资源打包遗漏，不能推广为全部 JavaScript 语法、任意服务 ABI、x86 发行包或 Win7 真机验收。可选导出和共享租约仍单列。

## UPSTREAM-WINDOWS-ACL-001：工作区授权物化

跟踪：[issue #4](https://github.com/czh869452912/deepseek-harness-win7/issues/4)。状态：**问题已确认，master 尚未合入修复；当前候选方案未获接受，另由独立分支/PR 讨论。** 已发布冻结包也不含候选修复。

固定原版为 `dsh-v0.1.5-rc.3 / a4c74a91e06b00fe0b0937bde982170c526cc842`。未加防护的迁移提供端与原版具有相同风险：

| 条件 | 固定原版与未修复迁移版 | 候选处理，尚未合入 |
|---|---|---|
| 用户仅对目录本层有权限，能力 ACE 成为唯一可继承授权 | 新文件可能写成功但关闭后不可读 | 合并前检查普通用户及后代授权，异常时拒绝 |
| 受保护 NULL DACL | 合并可能变成能力独占 DACL，宿主新建失败 | 区分 NULL/EMPTY，修改前停止 |
| 已授权后的 ACL 被外部改变 | 一次性授权缓存不能证明当前仍健康 | 每次重验实际状态 |
| 预检拒绝会连诊断/修复 shell 一并阻断 | 属于新增候选需要解决的可用性问题，不归因于原版 | 候选独立宿主诊断与审批修复仍需重新评估交互、自动化和覆盖范围 |

用户已明确当前候选设计与理想效果不一致。主分支不把“预检拒绝 + 另行审批目录修复”写成最终产品方案，也不将候选通过定向测试等同于问题已解决。最终需兼顾正常读写、Python/API 转换产物、既有受损对象和 agent 的诊断/恢复能力，保护业务 ACL 和沙箱边界。

当前 master 仅登记问题，不新增此项到已接受的机器例外注册表。候选代码、诊断工具、配对驱动、验证摘要及方案文档留在其 PR；原有例外及发行回执保持原身份。

参见[原版已知问题](upstream-known-issues.md)、[机理评估](research/2026-10-21-workspace-acl-mechanism-assessment.md)和[初始现场记录（含复核提示）](research/2026-10-21-acl_issue_analysis.md)。
