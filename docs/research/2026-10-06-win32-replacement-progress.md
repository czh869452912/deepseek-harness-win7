# Windows 替换错误与011验收拒绝

干净产品 `011c3a9509c838370cbd9e7d39f5da775ad045da` 的完整8537项回归正常结束：8530 passed、1 failed、6既有平台skip、1既有Proactor warning，2675.50秒。失败是 `test_write_text_guards_versions_and_returns_normalized_diff_basis` 的受版本保护覆盖，`ReplaceFileW` 返回1175；目标仍为外部更新后的 `external change`。本轮拒绝，051未签收，最新完整签收仍为2a67ae84的60个有界范围。

精确候选ZIP SHA256为 `fe67c5d4ff3cae0839a746e0ce023a465e16a90d087877d37bfb9280ca56b49c`，完整冻结输入为 `d442541892bdf7ce6258554cb7b93f9d352e9f1bbd617feeda9b1959e8a6235a`。完整XML、日志、原始冻结输入和ZIP在主拒绝归档 `migration/evidence/artifacts/LLM-PREPARED-REJECTED-20261006-011c3a95.zip`，SHA256 `c7131176f2abdf48563ea56606322092f2b7d2a6552203c0b36952dba4d7fca3`。补充归档 `WIN32-REPLACEMENT-DIAGNOSTICS-20261006-011c3a95.zip` 保留失败目标、自动清理审计、原版与原生受控观察、实际导入来源及定向回归。

原版 `fs-local/src/win32.ts` 也直接调用ReplaceFileW并传播错误。[Microsoft的ReplaceFileW文档](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew)说明1175时被替换文件无法删除，两侧文件保留原名。当前证据没有识别这次失败的持有者，也没有证明1175来自特定扫描程序或本实现泄漏。

实际原版与原生的受控句柄观察覆盖两种共享方式：只共享读写的句柄使两侧拒绝并返回32，目标保持旧内容；共享读写删除则替换成功。显式释放句柄后两侧的新调用成功。此观察不是1175的复现，也不能据此将原始失败归因于同一种持有者。

这次有界修正是公共错误诊断：Windows安全描述符和替换边界现在保留原版 `name/message/code/errno/syscall/path/win32Code`，另保留原生 `winerror`。原版的2/3映射ENOENT、5映射EACCES、其他映射EIO；Windows编号不能作为POSIX errno解释。缺失目标的改名恢复仅在上层原版对应分支发生。1175/1176/1177仍原样拒绝，不增加重试、忽略ACL、改名降级或原版bug例外。

九条确定性拒绝控制验证原始编号、错误字段、仅一次调用、两侧文件内容保持和准确缺失/权限分类，加入正式必需lane。相关51项通过，四项既有Windows平台skip；门禁和迁移工作流961项通过（789.94秒）。第一次定向命令误选不存在的ACL测试文件，未运行任何测试，失败日志独立保留，随后使用实际ACL测试验证。门禁第一次运行遗漏Node路径，原版执行器错误的中断日志保留；正确显式设置Node路径后的961项全部通过。完整8537项失败仍为失败；新的完整验收待后续候选冻结。

正常pytest收尾自动删除528个可重建合成JSON、6080014005字节，审计摘要和完整候选摘要保留。用户已授权持续自动清理，不再逐批询问。真实回执、失败ZIP、XML、日志、Source与浏览器观察、冻结输入、仍活跃或未分类研究保持。

隔离研究已得到30项权限生命周期、22项共享文件提权控制、25个实际headless完整工具定义、151项读取窗口、263项差异卡及实际25项读取/41项写入编辑完整观察。headless实际工具往返的原生473个模块导入来源已校验，25个完整工具定义逐项匹配原版；这不包括所有条件配置或完整profile签收。完整结果、错误、事件顺序、回放与卸载逐项比较；这些尚未推广或通过新便携包验收。原始失败观察和明确诊断差异仍保留。七个父范围、完整profile、任意ABI/竞争和延期Win7仍开放，`accepted_upstream`为空。
