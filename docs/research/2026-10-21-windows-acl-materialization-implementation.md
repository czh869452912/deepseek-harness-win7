# Windows ACL 授权物化实施与定向验证

> **未接受的独立候选实现。** 用户要求将本实现与主分支问题记录分开提交，当前方案仍需重新设计。下文保留实施与测试的历史身份，不能据此宣称 master 或已发布包已修复。跟踪 [issue #4](https://github.com/czh869452912/deepseek-harness-win7/issues/4)，PR 不自动关闭该问题。

日期：2026-10-21。用户授权实施[设计](2026-10-21-windows-acl-materialization-design.md)，并要求登记为原版与迁移版的已知差异及原版已知问题。固定 Source 为 `dsh-v0.1.5-rc.3 / a4c74a91e06b00fe0b0937bde982170c526cc842`。保留用户既有其他模块修改；未修改 reference、真实工程 ACL、已发布包或旧资格回执。

后续更新：本文以下保留初次启动防护及其验证身份。用户随后指出预检也阻断诊断和修复 shell 的可用性问题，已授权并实现独立 `workspace_acl` 宿主诊断、快照方案与审批恢复；当前行为及新增验证见[恢复流程记录](2026-10-21-windows-acl-recovery.md)。以下“尚未提供独立诊断”等为初次实现状态。

## 实现行为

- [windows_acl_checks.py](../../dsh/sandbox/windows_acl_checks.py)用命名查询区分缺失/NULL/EMPTY/真实 DACL，使用原生 `CreatePrivateObjectSecurityEx` 和 `AccessCheck` 评估真实宿主/受限令牌。仅支持普通 Allow/Deny ACE，保留组、CREATOR_OWNER、继承标志及 Deny 语义；不支持的评估布局明确失败。
- 根目录、两代子目录和其新文件均检查读写/遍历、关闭重开所需授权，以及文件/目录 DELETE 或父目录 DELETE_CHILD 的替代路径。默认不往工程里创建探针。
- [windows_acl.py](../../dsh/sandbox/windows_acl.py)的正向 grant 统一进入防护；原精确能力 ACE 命中不再绕过检查。通过后以目录句柄合并能力 ACE、校验对象身份并重读实际描述符，确认 owner/group 和保护状态，必要时重评实际结果。
- [local.py](../../dsh/sandbox/local.py)移除一次性成功集合，每次调用重新验证；健康普通授权下可重建缺失能力 ACE，用户继承退化则拒绝。正确修复后无需为清除该集合重启 Host。
- [windows_runner.py](../../dsh/sandbox/windows_runner.py)无预供 SID 时使用同一 grant；有预供 SID 时仍只读核验根和 temp 的实际 ACL。失败保持 `windows-acl-run:` 与退出 127，不执行 payload，不降级为无限制进程。
- 私有 temp 保留目录身份；复用或清理前发现路径被替换/成为重解析点则拒绝，不删除替换对象。创建失败后的清理错误单独报告，不覆盖原错误。工作区能力仍常驻，不在卸载时撤销。

公共 sandbox code/name、模式、SID 算法、受限令牌标志和 read/write 工具协议不变。异常工程仍需按维护流程修复用户/组继承，已有 protected 文件单独核对；程序不自动补全用户权限。

## 与设计的明确取舍

当前每次都完整评估，没有分析结果缓存，减少令牌指纹、缓存失效和过期结果的额外状态。内部返回快照并在异常对象上保留 before/after 信息，尚未提供独立公开诊断命令或自动持久化 SDDL 的产品接口。

命名查询到首次句柄绑定之间，以及核验后 payload 实际访问之间仍存在外部竞争窗口；路径锁不约束其他进程。检测到的变化直接失败，不无界重试，也不将父目录快照恢复称作整树事务回滚。不会自动扫描并修复全部既有后代，或认证 SACL/MIC、管控驱动和硬链接等完整边界。

## 定向验证

选择原生授权/runner/Host、pwsh、宿主原子写及公共 sandbox 消费者，是因为本修复同时改变授权副作用和命令启动前的拒绝时点；没有仅按新文件名选择测试，也没有启动全量回归或 Portable 构建。

最终命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_windows_acl_materialization.py tests/test_windows_acl_runner.py tests/test_local_sandbox_provider.py tests/test_pwsh_executor.py tests/test_fs_atomic_write_diagnostics.py tests/1to1/sandbox -q --tb=short --junitxml=.goose/out/acl-materialization-20261021-final-targeted.xml
```

结果：**100 passed / 1 skipped，20.93 秒，退出 0**。skip 是固定上游在 win32 跳过的 POSIX 组件语义/符号链接用例；pytest-asyncio 报既有 fixture loop scope 未配置的弃用提示。

原生场景覆盖：本层授权、NULL/EMPTY、显式 Deny、NO_PROPAGATE、已有能力 ACE 危险布局、普通 Modify/FullControl、CREATOR_OWNER、Authenticated Users、两层创建/关闭重读/修改/删除；同 Host 修复恢复与能力重建、预供 SID 失效、temp ACL 变化及路径替换、两个独立提供端并发、查询/应用/核验/竞争/不支持评估失败。

实际集成旅程为 PowerShell 调用 Python，经本地 HTTP API 响应生成 Markdown，关闭重读，再由 FsService 原子编辑并删除。没有调用真实 MinerU 或付费 API，不把 API 内容转换正确性作为 ACL 修复证据。

Python 3.8.10 x86 使用现有 `.goose/tools/python-3.8.10-win32/python.exe`，在当前进程临时加入仓库和 pytest 的纯 Python 依赖路径，不改动该运行时：同一新测试文件选择 `dangerous or native_prediction`，**9 passed / 15 deselected，1.65 秒，退出 0**；XML 为 `.goose/out/acl-materialization-20261021-x86-final.xml`。这覆盖 x86 ctypes 对齐、分类和正常实际受限创建，不是 x86 全量回归。

初期失败的 XML `...-initial.xml`、`...-native.xml`、`...-owner.xml`、`...-calibrated.xml` 及短 pytest 工作区诊断保留。主要校准点是：空 DACL 或显式读取拒绝时，直接 `CreateFileW` 可能失败，而 owner 的命名安全查询可成功；分类因此先走 `GetNamedSecurityInfoW`，之后才绑定句柄。最初 x86 pytest 启动因隔离运行时未包含仓库搜索路径而失败，补充本次进程路径后通过；不改写失败历史。

## 实际 Source 配对与登记

[windows_acl_oracle.py](../../scripts/windows_acl_oracle.py)在独立自有系统 TEMP 夹具中运行固定 reference 的真实 TS grant，再与 Python 正向 grant 比较。驱动校验固定 HEAD、无 tracked 修改、完整 SID 一致及观察字段；只接受两种精确签名，不把任何失败都当成已知差异。

```powershell
.venv\Scripts\python.exe scripts/windows_acl_oracle.py --output .goose/out/acl-materialization-20261021-paired-final/observations.json
.goose\tools\python-3.8.10-win32\python.exe scripts/windows_acl_oracle.py --output .goose/out/acl-materialization-20261021-paired-x86-final/observations.json
```

两次退出均为 0，两场景均为 `reviewed-upstream-bug/UPSTREAM-WINDOWS-ACL-001`，夹具恢复后删除。Source Node 为 v22.20.0；第二次只把 Python 提供端换成 x86，不据此宣称原版 Desktop 或 Node 也是 x86。原始根描述符、错误、命令及哈希保留于各自观察文件；完整精确语义与原始载体 SHA-256 另存于[结构化检查记录](../../migration/candidates/rc3/windows-acl-current-checks.json)，不是发行资格回执。

已登记：[原版已知问题](../upstream-known-issues.md)、[迁移已知差异](../known-differences.md)、[统一发现索引](../../migration/upstream-bug-exceptions.json)。保留既有八项精确上游判据，新增本项的两场景；不更改旧观察、不扩大 `accepted_upstream`。已有统一发行 paired-driver 列表未扩展，本驱动需在本修复或更换 pin 的资格检查中显式运行，不能声称旧 82 驱动已包含它。

## 剩余范围

实际内网 E 盘路径、LDAP/域账户令牌与 ACL 前后快照，以及 Win7 SP1 + PS 5.1 的实机复验仍待现场完成。当前系统是现代 Windows build 26200，不因 Python 的 `Windows-10` 字符串将其认作 Win7。独立诊断命令属于后续产品能力，不是启动防护的前置条件。

当前只报告有界实现与定向完成；未执行新候选全量回归、Portable/安装器重建或发行资格，现有下载包仍是之前冻结版本，不含这次修复。需要新包时，按[验证指南](../testing.md)为稳定候选安排完整门禁。
