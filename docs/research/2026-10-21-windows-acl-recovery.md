# Windows ACL 检查失败后的诊断与授权恢复

> **候选恢复交互，未接受。** 用户反馈整体设计与理想效果不同，本实现仅保留于独立分支/PR。预检仍可能阻断全部 pwsh 请求，既有受损文件也不保证恢复；独立工具依赖宿主权限与审批，不能视为 agent 已恢复正常工作。跟踪 [issue #4](https://github.com/czh869452912/deepseek-harness-win7/issues/4)，尚未合入 master 或发布。

日期：2026-10-21。本文接续[授权物化实施记录](2026-10-21-windows-acl-materialization-implementation.md)。用户指出：工作区继承异常时，命令启动前的拒绝也会阻止 agent 运行诊断和修复命令，导致在该工作区无法自救。本轮按用户授权补齐独立恢复入口，没有修改用户真实 E 盘目录，也没有生成新发行包。

## 当前行为

Windows 本地沙箱提供端配合普通 pwsh 或持久 PowerShell 工具时，额外注册模型工具 `workspace_acl`。持久 PowerShell 是当前预设的实际执行路径，不能仅修改单次 shell consumer。注册使用服务依赖注入和工具所属作用域，卸载时撤销；不改原版前端和既有工具参数。这个新增工具也是迁移版的有意差异，Minimal 在该组合下会额外拥有恢复工具。

普通命令仍执行原来的 ACL 预检。失败提示引导调用以下独立入口，它们不启动 PowerShell、不先物化工作区能力授权，也不通过取消限制重试普通命令：

1. `workspace_acl {"action":"inspect"}`：宿主只读查询工作区及最多 16 层祖先的 SDDL、DACL 分类、保护标志和预检原因。可用 `path` 指定相关目录，不扫描整树。没有审批服务也可诊断；读取 ACL 被系统拒绝时，返回该目录的错误而不是把它记为空 DACL。
2. `workspace_acl {"action":"plan","path":"E:\\projects\\my-workspace"}`：默认只选择工作区根目录；父目录必须明确指定。生成当前宿主账户 SID 的 `(OI)(CI) Modify` 追加方案，包含选定路径、原 SDDL、继承影响及是否越出工作区。只在内存评估修复后的授权，没有修改工程 ACL。
3. `workspace_acl {"action":"repair","planId":"前一步返回的标识"}`：通过既有 `approval.request` 展示具体路径、账户、增量和传播范围，仅 `allowed-once` 执行。拒绝、取消、审批不可用或只读模式均不写 ACL；不自动切换会话权限，不运行任意 shell 命令。
4. 通过后返回实际描述符、目标目录备份路径及 `workspaceReady`。工作区根目录检查恢复正常后，agent 正常重试原 pwsh 请求；不自动重放原命令，避免重复转换或覆盖。已验证不必重启 Host。

方案为提供端内存中的随机 ID，最多保留 16 份、10 分钟过期，绑定会话、工作区、宿主账户、目标与祖先身份链、原安全描述符。批准等待结束后重新解析会话策略；写入前重新比较身份和 ACL。换目录、改 ACL、过期、跨会话和切回只读均需停止，不能照旧方案修复。

## 修复边界

首版只修复明确选定的**目录**，追加当前宿主账户的正常可继承 Modify；不会给任意 SID 授权，不改 owner/group、Deny、保护开关或 SACL。已有 ACE 按原相对顺序保留，在继承 ACE 之前加入新的显式 Allow。原生测试发现，对同一 SID 使用 `SetEntriesInAclW(GRANT_ACCESS)` 可能移除原 Deny，故此恢复路径不采用该合并方法；候选与实际结果均重新做原生访问评估。

恢复使用 `NtOpenFile` 请求 READ_CONTROL/WRITE_DAC，以及 FileInternalInformation/卷序列查询绑定身份。原因是在能力独占 DACL 下，owner 的命名 ACL 查询和最小安全元数据访问可成功，而 `CreateFileW` 和 Python stat 的稳定身份查询可能失败。没有启用备份/还原特权、接管所有权或请求 UAC 提权。宿主自身无权读取/修改 ACL 时，工具明确失败，需要具备权限的用户处理。

写前在工程外的系统 TEMP 创建并同步保存选定目录的 owner/group/DACL 描述符及 SDDL、身份和方案，路径返回给用户。备份失败则不应用修复。修复失败或写后检查失败保留备份并说明可能已变化，不自动回滚。此备份不是 SACL 或整个目录树的完整备份。

**父目录修复有实际传播范围。** `SetSecurityInfo` 可能将可继承授权传播到已有、未关闭继承的后代，因此审批说明包含下面其他工作区可能受影响，不能把它说成只改一个孤立对象。未递归 reset、删除旧 ACE 或强制修改 protected 后代。父目录修复后，工作区若仍受保护且异常，返回 `workspaceReady: false`，需要为该工作区另生成并批准方案。工具不遍历并认证全部现有文件。

其他限制：

- 缺失/NULL/EMPTY DACL、无法评估的 ACE、保留 Deny 后仍无法通过检查等情况，仅诊断，不能自动追加后谎报恢复；应交有权限的维护者复核。
- 拒绝修复盘符/共享根目录、无关目录、含重解析组件的目标及覆盖宿主 TEMP 的范围。为跨多个工程修复，应明确选择专用工程上级目录。
- 现有 protected 文件和子目录不保证恢复。读取、写入和原子编辑工具仍受实际目标 ACL 约束，本轮没有为每个文件读写入口增加通用修复器。
- 审批缺失时仍能诊断、生成方案，但不承诺 agent 能独立执行修复。默认流程也不会绕过公司管控、外部进程或 Windows 拒绝。
- 路径锁只协调 DSH；核验不是外部写入者的原子比较交换。目录通过预检也不代表所有后代今后永远可访问。

相关实现：[恢复服务](../../dsh/sandbox/windows_acl_recovery.py)、[元数据句柄](../../dsh/sandbox/windows_acl_metadata.py)、[工具与审批](../../dsh/shell/workspace_acl_tool.py)、[持久 PowerShell 接入](../../dsh/terminal/persistent_pwsh.py)。

## 验证记录

本轮选择原生恢复、审批消费者、普通/持久 pwsh、既有 ACL 授权及 runner、文件原子写和公共 sandbox 回归；另验证实际 canonical Web profile 的 Minimal/Standard 作用域内可调用诊断。仅使用自有夹具，不请求真实模型或 MinerU 服务。

结果和最终命令见[结构化检查记录](../../migration/candidates/rc3/windows-acl-recovery-checks.json)。首次失败及后续记录保留在 `.goose/out/acl-recovery-20261021-*.xml`；原始失败不能由后续通过回填。

最终 x64 定向 **132 passed / 1 skipped，46.38 秒**；唯一跳过仍是 Windows 不适用的既有 POSIX 组件语义用例。x86 原生恢复和审批消费者 **25 passed / 2 deselected，2.20 秒**，两项排除为已在 x64 执行的实际 PTY 和 Web 旅程。两次均退出 0。实际固定 Source 的两种原始缺陷配对复验仍通过，接受判据未扩展。存在既有 pytest-asyncio loop scope 配置弃用提示。

最后补查保持能力 SID 的原始路径大小写算法：Windows 文件路径比较可以忽略大小写，现有 SID 哈希却不能随之改用小写键。恢复评估按提供端的原始工作区路径生成同一 SID，含针对该 SID 的 Deny 时不会用另一个 SID 误判通过；对应原生回归在 x86/x64 均通过。

当前仍是现代 Windows 上的 Python 3.8.10 定向源码验证。Win7 SP1 + PS 5.1、真实 LDAP/域账户、外部管控和新版 Portable/Desktop 发行资格尚待现场或稳定候选验收。旧发布包不包含本轮改动。

## 独立分支提交前验证

提交前隔离验证（2026-10-21）：从远端主分支文档提交 `682a2d46` 创建独立分支，仅复制本候选代码和记录，未带入原工作区其他模块改动。使用原工作区 Python 3.8.10 x64 环境，执行以下定向集合，**134 passed / 1 skipped，58.20 秒，退出 0**：

```powershell
python -m pytest tests/test_windows_acl_recovery.py tests/test_workspace_acl_tool.py tests/test_windows_acl_materialization.py tests/test_windows_acl_runner.py tests/test_local_sandbox_provider.py tests/test_pwsh_executor.py tests/test_canonical_pwsh_tool.py tests/test_canonical_persistent_pwsh.py tests/test_fs_atomic_write_diagnostics.py tests/test_upstream_exception_registry.py tests/1to1/sandbox -q --tb=short --junitxml=.goose/out/acl-publication-20261021/pr-targeted.xml
```

实际 XML 保留在原工作区 `.goose/out/acl-publication-20261021/pr-targeted.xml`；命令中的解释器实际为该工作区 `.venv/Scripts/python.exe`，执行目录为独立检出。比上轮 132 项增加例外注册表的两项验证，既有平台跳过与 asyncio 提示相同。本次仅证明候选可独立通过所列定向用例，不表示方案符合最终需求，也不是全量、发行或 Win7 验收。

## 原生 API 依据

- [SetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo)：句柄绑定的安全设置及对已有后代的继承传播。
- [NtOpenFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntopenfile)：指定所需访问权的元数据句柄；本轮在 x86/x64 校验实际调用，不代替 Win7 现场验收。
- [FILE_INTERNAL_INFORMATION](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_internal_information)：无需文件数据读取权的文件系统身份查询。
