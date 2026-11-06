# Windows ACL 授权物化流程设计

> **候选方案，未接受。** 用户反馈当前设计与理想效果不一致，要求将实现单独保留在 PR，暂不合入 master。本文的“实施”“完成”只表示曾实现及定向验证，不代表方案签收或发行。跟踪 [issue #4](https://github.com/czh869452912/deepseek-harness-win7/issues/4)；主分支仅登记问题分析。

日期：2026-10-21。状态：已按后续授权实施并完成当前 Windows 定向验证，真实 Win7/发行验收待完成。背景与现场边界见[机理评估](2026-10-21-workspace-acl-mechanism-assessment.md)，实施与设计取舍见[实施记录](2026-10-21-windows-acl-materialization-implementation.md)。下文保留设计要求；第 10 节说明实际落地范围，没有修改真实工程目录或发行包。

## 1. 目标与约束

授权物化是将工作区能力 SID 的写授权落到 NTFS DACL，使受限进程能在既定工作区内写入。目标是避免这一动作将原本依赖令牌默认 DACL 的目录变成“新文件只有能力 ACE”，并避免把 NULL DACL 静默转换为能力独占 DACL。

约束如下：

- 保留 Python 3.8.10、Win7 SP1、PowerShell 5.1 兼容性，不增加现代系统专用 API 或外部运行依赖。
- 保留 `LUA_TOKEN | DISABLE_MAX_PRIVILEGE | WRITE_RESTRICTED`、模式词汇、能力 SID 算法及受限失败后不运行 payload 的契约。
- 不自动追加用户 FullControl、接管所有权、删除合法 Deny、关闭继承或改动工作区上级目录。
- 保留原子覆盖的目标 DACL 继承策略；不分别改 pwsh、Python、read/write 工具来绕过底层权限。
- 根入口检查不认证整棵树，也不是完整沙箱边界；受保护后代、显式安全描述符、硬链接、外部 ACL 改写和文件系统过滤器仍须按实际操作处理。
- 自动物化只增加既有产品约定的能力授权；修改用户/业务组授权是另一项需明确范围、预览、备份与恢复的维护操作。

## 2. 当前入口与需要修复的缺口

| 位置 | 当前行为 | 设计落点 |
|---|---|---|
| [local.py](../../dsh/sandbox/local.py) `confine/materialize` | 有 sessionId 时由 Host 授权，`workspaces` 集合使根目录仅处理一次 | 每次准备受限执行前重新读取根状态，缓存只复用分析结果 |
| [windows_runner.py](../../dsh/sandbox/windows_runner.py) | 无预供 SID 时自行授权；有 SID 时只验证路径派生值后使用 | 两种分支共用同一安全检查，预供 SID 不等于 ACL 有效 |
| [windows_acl.py](../../dsh/sandbox/windows_acl.py) `grant` | 路径锁内读 DACL、精确 ACE 短路、合并写入 | 精确 ACE 检查之前先分类和检查，写前评估候选、写后重读 |
| 同文件 `restricted_token` | 创建受限令牌并补默认 DACL | 复用真实令牌配置作检查输入，不为绕过检查修改其权限 |
| [fs_local.py](../../dsh/fs/fs_local.py) | 宿主执行原子写，覆盖时保留目标 DACL | 保留行为与已有阶段诊断；不在每次写入偷偷修 ACL |

因此，仅在 Host 的 `materialize()` 增加一次检查不够；独立 runner 和已缓存工作区都必须覆盖。read-only 不新增工作区写授权，也不为只读调用修改磁盘 ACL。

## 3. 责任划分与内部接口

初期继续由现有 `sandbox` 服务拥有授权生命周期，不新增插件间硬编码调用或前端协议。Win32 读取、分类、候选构造和访问评估留在 `windows_acl.py`；复杂度确有必要时再拆同包内部模块。

拟定内部接口职责，名称可随实现调整：

| 职责 | 输入/输出 | 允许的副作用 |
|---|---|---|
| `inspect_directory` | 路径 -> 身份、owner/group、DACL 状态、control flags、ACE、指纹 | 只读；失败返回明确 Win32 错误 |
| `assess_materialization` | 快照、候选能力 ACE、宿主/受限令牌 -> 结论及依据 | 仅内存中的描述符和令牌操作 |
| `ensure_workspace_grant` | 工作区、派生 SID -> 本次已核验的 receipt | 路径锁内仅合并既定能力 ACE |
| `validate_workspace_grant` | 工作区、SID -> 当前检查结果 | 只读；用于 runner 的预供 SID 分支 |
| 临时目录 grant/revoke | 本提供端创建的目录与 SID | 独立生命周期，不套用工作区常驻清理规则 |

receipt 是内部记录，不是跨进程授权凭证，也不把“上次通过”变成永久可信。所有原生缓冲区、句柄和临时令牌均有确定释放路径；不把 descriptor 中的指针保留到其缓冲区释放之后。

## 4. 授权物化状态流程

顺序为：验证输入与对象身份 -> 获取路径锁 -> 读取快照 -> 分类 -> 评估当前/候选状态 -> 必要时合并写入 -> 重读核验 -> 发布 receipt -> 启动受限 payload。

### 4.1 路径与快照

核对路径是存在的目录，沿用上层允许的工作区边界，记录实际目录身份、规范路径、owner/group、DACL present/defaulted、NULL 指针、ACE 数、protection/auto-inheritance flags。查询错误、结构无效和零 ACE 是三种结果，不允许相互降级。

路径、锁键、缓存键和 SID 派生必须一致；复用现有 [roots.py](../../dsh/sandbox/roots.py) 的规范化约定，但不在本修复中静默重算所有历史路径的 SID。先用大小写、末尾分隔符、别名/重解析点等样本核对现有调用链；确需改变派生输入时，应另列兼容策略，保留旧 ACE，不批量迁移。

变更前后核对目录身份，发现目录被替换或解析结果改变时失败，不把缓存应用到同名新对象。优先评估句柄绑定的安全描述符读写；若保留按路径 API，必须披露竞争窗口，不能宣称路径锁阻止了外部进程或重解析点替换。

### 4.2 硬性拒绝条件

以下情况不调用 `SetEntriesInAclW/SetNamedSecurityInfoW`，不启动受限 payload：

- 缺少 DACL 或 DACL 指针为 NULL，分别记录原因；不能通过一次合并将允许全部变成能力独占。
- 真实 EMPTY DACL、无效描述符、读取/解析失败，或本次调用身份不足以完成所需检查。
- 已确定加入/使用能力 ACE 后，新对象缺少正常用户授权，或根目录/新子目录不满足本工作区写流程的基础要求。
- 当前 ACL 含本实现无法可靠评估、且影响本次授权结论的结构；输出 `assessment-unsupported`，不能按“没看懂所以允许”处理。不是看到任意未知 SID 就拒绝。

已有精确能力 ACE 也必须经过检查：危险布局可能已存在，不能让 `exact_grant()` 提前短路。protected 本身不是拒绝条件；具备正确显式可继承用户授权的 protected 根目录可以正常工作。

### 4.3 新对象授权评估

不能简单要求存在一条 `当前用户 + OI/CI + FullControl`，也不能把 Allow mask 求并集当作 Windows 访问检查。正常组、CREATOR_OWNER、继承专用 ACE、NO_PROPAGATE、显式 Deny、管理员 deny-only 和限制 SID 都会改变结果。

设计采用 Windows 原生描述符继承及访问检查作候选方案：在内存中构造能力 ACE 合并后的父描述符，分别预测宿主和真实受限令牌创建普通文件、子目录、子目录内文件的权限；比较现有与候选布局。使用实际 owner/group 和文件对象 generic mapping，覆盖读取数据、写入、目录创建/遍历，以及对象 DELETE 或父目录 FILE_DELETE_CHILD 的替代路径；不要求普通读写任务具有 WRITE_OWNER 或全权。

[CreatePrivateObjectSecurityEx](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createprivateobjectsecurityex)提供描述符继承机制，但其参数、令牌默认 DACL 和 NTFS 实际新建行为必须先通过第 8 节实测校准。它不是不经验证就可代替文件系统创建的证明。

[AccessCheck](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck)要求 impersonation token、已映射的访问位和含 owner/group 的描述符。需从实际宿主及同配置受限令牌派生检查令牌，区分 API 调用失败与访问检查拒绝，并验证 WRITE_RESTRICTED 的读写差异。不使用手工删除管理员组的伪令牌来代替真实行为。

首个技术验证若不能可靠对齐预测与真实创建，先交付 NULL/EMPTY 防护及可证明的单一能力继承缺口识别；对影响结论的复杂布局明确报不支持，不能用未经校准的完整预测放行。增加对复杂布局的支持需补相应对照，不以错误允许来扩大兼容范围。

默认检查不在真实工程写探针文件。实际创建、关闭、重读及清理用来验证实现，放在自有夹具中；如后续提供现场主动探测，应作为用户选择的独立诊断操作。

### 4.4 合并、重读与失败

通过检查后，若能力 ACE 已有效存在则不写；缺失时使用当前读到的 DACL 合并能力授权，保留既有 owner、业务 ACE、Deny 和继承保护语义。不为规避候选评估改变 GRANT_MASK，也不顺带移植最新上游的 Low label/额外 Deny；这些属于独立兼容与边界变更。

实际写前重新核对身份及快照；如发现变化，最多重读重评一次，再次变化则报 `acl-changed`，避免无界重试。DSH 路径锁仅协调遵循同一协议的参与者，不能提供跨外部写入者的原子比较交换。

写后重新读取实际 DACL，确认能力授权、普通访问条件及无意外 owner/protection 变化。自动继承可能使 ACE 表示或排序变化，因此不能只按 SDDL 字符串相等判断。失败不发布成功缓存，不启动 payload，记录 `apply` 或 `verify` 阶段及是否已经写入。

**这不是文件系统事务。** 父目录 ACL 写入可能传播到既有后代；恢复父目录旧 DACL 不保证精确恢复子对象原状态，撤销最后继承 ACE 还可能留下 EMPTY DACL。写后发现异常时不盲目覆盖整份旧快照，也不笼统撤销能力 ACE。保留本次前后根描述符和错误供维护者处理，受影响后代仍需独立调查；不能声称自动回滚完成。

## 5. 缓存、两条入口和生命周期

将 `workspaces: set` 改为有界的核验记录：路径/对象身份、owner/group 与 DACL/control 指纹、检查令牌身份/组状态指纹、评估器版本及结果。每次 Host 准备受限执行仍读取根快照，指纹一致才复用较贵的评估；只用 mtime、时间 TTL 或路径字符串不足以判断 ACL 未变。身份指纹不包含凭据。

当外部移除能力 ACE 时，Host 在完整检查通过后可以重新物化同一既定授权；用户有意禁用工作区写入应通过模式控制，而不是依赖手工删除常驻 ACE。若用户授权也已失效，则失败并清除缓存，不能仅把能力 ACE 补回。正确修复目录后下次调用自动重评，不要求为了丢弃旧集合而重启整个 Desktop。

独立 runner 的无 SID 分支使用同一 `ensure_workspace_grant`。有预供 SID 的分支在 SID 与实际路径匹配后，仍执行只读验证；能力缺失或布局已变坏则退出 127，不能信任传入参数跳过检查。下一次 Host 调用再决定是否重新物化，runner 不在这一分支偷偷扩大修复范围。

每次 runner 验证后到 payload 打开文件仍有外部竞争窗口；预检查通过不等于后续访问永远成功。现有 OS 拒绝、runner 错误前缀、退出码和工具阶段错误仍须保留。暂不自动重试用户命令，避免重复转换、覆盖或其他副作用。

私有 temp 同样检查真实 ACL，不能假定系统 TEMP 总是健康。失败只清理本提供端新建且确认身份的目录；清理错误单独报告，不覆盖主错误、不递归删除未知内容。工作区能力 ACE 继续按现有常驻契约，不在插件卸载时撤销。新注册的诊断服务或事件通过 Cordis effect 释放。

## 6. 错误与维护修复的界面

内部结构化失败建议包含：`stage`、`reason`、目标路径、实际用户 SID、能力 SID、DACL 类型/protection、缺失的操作条件、Win32 code、是否已修改。SDDL 和组清单只进入本地有范围的诊断输出，不自动发送遥测；不要把查询失败格式化成“空 ACL”或“管控污染”。

建议原因集为 `null-dacl`、`empty-dacl`、`normal-access-missing`、`inheritance-gap`、`assessment-unsupported`、`acl-changed`、`query-failed`、`apply-failed`、`verify-failed`。保留既有 `SandboxUnavailableError` 的公共 code/name；先将精确原因放入其 detail 和 runner 的 `windows-acl-run:` 错误，不改动原版 Web GUI 协议。若新增公开结构化字段，再补完整消费合同，不在本设计中假称已有。

给用户的建议指向已确认的工程或专用上级：备份 ACL，核对实际用户/业务组，按预期范围合并 OI/CI Modify，单独处理 protected 后代。诊断不直接执行修复，不自动启动提权窗口，也不把公共错误里已有的 danger-full-access 提示当成本问题首选解决方案。

## 7. 分阶段实施计划

| 阶段 | 具体交付 | 完成判据 |
|---|---|---|
| A：原生技术验证 | 只读分类、快照结构和内存候选；预测与真实创建对照 | 正常、仅本层授权、NULL、EMPTY、CREATOR_OWNER、管理员过滤均有原始证据；明确可支持边界 |
| B：最小安全防护 | grant 前分类和确定性继承缺口检查，精确 ACE 不跳过，写后核验 | 两条 grant 入口在失败前不修改危险根 ACL、不执行 payload；正常根仍可用 |
| C：生命周期闭合 | 取代一次性集合、预供 SID runner 核验、外部变化与 temp 失败处理 | 同 Host 修复后可恢复、移除能力可按策略重建、权限退化拒绝、并发有界 |
| D：现场诊断与验收 | 有范围的只读报告、维护修复说明、Win7/MinerU 重现旅程 | 真实账户/ACL 前后证据和 Win7 结果齐备；不把现代系统夹具代替现场结论 |

A 阶段结果决定 B 阶段评估器支持哪些布局；不能跳过技术验证直接上线“完整继承预测”。B 的有限保护可以独立评审，但对外须明确其覆盖边界。C 完成前不能声称同一 Host 已可靠处理 ACL 外部变化。

## 8. 验证范围与验收矩阵

设计阶段仅做文档检查；后续实施已运行定向测试，详见第 10 节。原失败机制、两条授权入口及直接消费者为定向范围：

- [test_windows_acl_runner.py](../../tests/test_windows_acl_runner.py)：实际受限进程、独立/预供 SID 分支、payload 不执行、私有 temp、read-only 与外部路径写拒绝、子进程链路和退出码。
- [test_local_sandbox_provider.py](../../tests/test_local_sandbox_provider.py)：同 Host 缓存重验、跨 session temp 隔离、修复后恢复、外部能力删除、卸载与清理失败。
- [test_fs_atomic_write_diagnostics.py](../../tests/test_fs_atomic_write_diagnostics.py)、[test_pwsh_executor.py](../../tests/test_pwsh_executor.py)及 sandbox vocabulary 消费者：宿主原子写、pwsh 失败传播、公共错误/模式与现有启动默认 DACL 回归。
- 新增安全描述符检查定向用例，至少涵盖下表；全部只修改新建自有夹具，失败前后保留原始 ACL 和错误，不在仓库或真实上级目录做递归 ACL 实验。

| 布局/操作 | 必须证明的行为 |
|---|---|
| 当前用户或有效组 OI/CI Modify | 正常物化；宿主与受限子进程新建、关闭、重读、替换、删除；二级子目录正常 |
| 只有用户本层权限，能力将成为唯一可继承 Allow | 写前拒绝；根 ACL 不变；无 payload 和探针残留 |
| 已有能力 ACE，但缺少普通用户授权 | 不走精确 ACE 放行；给出继承/正常访问原因 |
| protected NULL、非 protected NULL、真实 EMPTY | 正确区分；不把 NULL 变成能力独占，不把查询错误当空 |
| protected 根且用户可正确继承；CREATOR_OWNER、业务组、INHERIT_ONLY/NO_PROPAGATE | 有原生对照才放行相应支持布局，不能仅按 protected 或 SID 是否可解析拒绝 |
| 仅 Administrators Allow、显式 Deny、owner 有 WRITE_DAC 却无数据权限 | 真实 LUA 对照；不以宿主提升或 owner 身份替代读写验证 |
| ACL 变化、同路径目录替换、并发两个 Host | 重新核验、有界失败；不覆盖别人的 ACL，不声称消除所有外部竞争 |
| 写入成功但重读失败；temp 授权/撤销失败 | 不启动 payload、不发布成功缓存，主错误与清理错误分开，无全树盲目回滚 |
| 普通复制到新名字与源文件带异样 ACL | 记录目的继承及导入前后快照，不把复制件与全工作区异常混同 |
| pwsh -> Python -> API 结果写 Markdown | 关闭重开、编辑替换、删除可用；用本地 API 响应夹具验证，不把付费 MinerU 调用列为普通自动回归依赖 |

保留命令、候选身份、架构、系统版本、SDDL、令牌组属性、错误码、时间和退出状态。现代 Windows 上先做真实 Win32 对照；面向 Win7 的最终现场验收需 Win7 SP1 + PS 5.1，覆盖实际域/LDAP 登录账户与提升/非提升组合，并在 x86/x64 目标上验证 ctypes 对齐和资源释放。

定向通过只报告定向完成；跨模块批次稳定或准备新发行时，再按[验证指南](../testing.md)安排单次完整门禁。当前迁移 pin、上游资格与旧发行回执不因本设计提升，不复用既有发行包的验收来认证未来实现。

## 9. 实施前仍需获得的现场证据

实际 E 盘路径、完整用户 SID/组属性、是否提升、上级/工作区/异常文件的 SDDL、复制和首次 DSH 操作三个时点，以及 MinerU 脚本创建文件的方法仍是现场验证输入。缺少这些信息不妨碍先完成自有夹具防护，但不能据此直接对真实工程执行修复或认定根因已经唯一确定。

本设计针对当前固定上游之外的防护扩展；实现后需记录与固定上游的有意差异。最新官方诊断技能和 Low label 等变化不自动纳入本批，后续迁移另作范围与验证决定。

## 10. 本次落地与取舍

后续迭代已补充独立于沙箱授权的宿主诊断、方案和单次审批恢复，见[恢复设计与实施](2026-10-21-windows-acl-recovery.md)。下文保留首次落地取舍；“独立诊断未完成”是当时状态。恢复不再要求先运行受限 PowerShell，父目录修复必须明确选定且披露继承传播，不能以永久完全访问模式弥补启动拒绝。

原生检查及两条入口已落地，包含普通 Allow/Deny、CREATOR_OWNER、有效组、两层子目录和关闭重开。其他影响评估的 ACE 类型明确拒绝，不按未知 SID 前缀推断管控。NULL/EMPTY 等先由命名安全查询分类，安全评估通过后再以目录句柄绑定身份并进行合并、核验。

缓存方案选择更保守的**不缓存成功授权结论**：移除 `workspaces` 集合，每次重读和完整评估；没有维护 TTL 或 token 指纹缓存，也没有新增持久 receipt 存储。发现竞争立即失败，不自动重试用户命令或覆盖旧快照。私有 temp 记录目录身份，发现同名替换则不使用、不撤销其 ACL、不递归清理替换对象。

A/B/C 的上述范围已经定向验证；D 完成了本地错误报告、维护说明、实际 PowerShell/Python/API 响应夹具旅程。独立用户可调用的诊断命令、真实 E 盘前后取证、Win7 域账户和新发行包资格仍未完成，不将这些剩余项写成已交付。结果、精确上游差异和原始失败诊断见[实施记录](2026-10-21-windows-acl-materialization-implementation.md)。
