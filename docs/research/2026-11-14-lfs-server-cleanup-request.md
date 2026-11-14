# GitHub LFS 服务端清理请求（已提交）

2026-11-14，原始归档完成远端发布和核验后，用户明确授权回收，以下正文已通过 GitHub Support 的 **Remove LFS objects** 表单提交。不再使用 LFS 的源码版本 `cde273216c78f5f51f0e9f0ae3d958169e624a65` 已推送至 `master`。未强推、删除远端 LFS 对象或重建仓库；提交请求不等于回收完成。

## 已提交正文

Subject: Purge retired Git LFS objects while preserving repository metadata

Repository: https://github.com/czh869452912/deepseek-harness-win7

I maintain this repository and want to stop using Git LFS for historical test evidence. The locally referenced set contains 240 unique LFS objects totaling 13,586,583,847 bytes. All are historical test ZIP archives under migration/evidence/artifacts/. There may be additional server-side objects not visible in local refs.

I have preserved the original archives outside Git and verified their sizes and SHA-256 identities. The object inventory is migration/storage/external-artifacts.json; each sha256 is the corresponding LFS OID. Commit cde273216c78f5f51f0e9f0ae3d958169e624a65 is pushed to master. It removes LFS-tracked archives from the current tree and LFS tracking rules, replaces archive-dependent tests with minimal original members, and disables default LFS checkout in CI. Historical result and candidate identities are preserved.

The backup is published at https://github.com/czh869452912/deepseek-harness-win7/releases/tag/evidence-archive-20261114 . Its evidence-locations.json maps all 240 original archives: 238 are stored in this archive release and 2 are reused from the existing Creative preview release. All asset sizes and GitHub SHA-256 digests match the original inventory. Both metadata assets and one original object were also downloaded and compared byte-for-byte. Original receipt JSONs and the historical transport proof are separately preserved in historical-receipts-20261114.zip. These are ordinary Release attachments, not LFS objects.

Please purge the 240 retired LFS objects in that inventory and stop their storage usage if this is supported while preserving the repository, issues, stars, forks, release assets, and repository identity. If branches/tags/references must first be retired or rewritten, please identify the required scope before any changes. If there are additional repository-associated LFS objects not in the inventory, please identify them before deleting them.

I understand that removing LFS tracking or rewriting Git history alone does not remove server-side objects. I do not authorize deletion or recreation of the repository, deletion of published release attachments, or removal of other repository metadata.

## 工单状态

Support 最初以当前账户仅提供自助资源为由关闭工单。随后补充说明这是 LFS 存储配额/计费处理请求，请转交能执行存储回收的团队或提供适用于该账户的支持入口，并重申保留仓库及 Release 的边界；工单已重新打开，观察状态为 **Open**。尚无 Support 已执行回收或配额已释放的确认。工单编号、具体地址、原始页面观察和截图保存在本轮忽略的 `.goose/out/evidence-storage-20261114/`，不将账户联系信息或完整支持会话提交到公开仓库。

## 服务端操作前的检查点

- 当前源码改造已经提交并推送；不得把 240 个 ZIP 再添加为普通 Git 文件。
- 当前本地档案路径：`C:\Users\czh86\Documents\Codex\deepseek-harness-win7-evidence`。它是持久迁移副本，保留 240 个原归档作为 Support 回收期间的回退副本；下一复审节点为 Support 答复或 2026-11-21（以先到者为准），不是可删除测试夹具。
- 不将整个 `.git` 缓存或保护性备份删除作为“GitHub 配额清理”；本地清理与服务端计费不同。
- 若必须改写历史，先在隔离副本演练，覆盖仍引用归档的发布标签、archive 标签和分支，记录旧/新提交对应及签收影响。当前历史包含先前 LFS 转换证明，不能盲目过滤后继续声称该证明有效。
- 删除并重建仓库会影响仓库元数据。先取得 Support 的实际答复；没有答复前不承诺配额立即归零。
- 约 601 MB 的普通 Git evidence JSON 本轮保留原字节。后续如精简或外置这些回执，需要单独迁移来源索引和文档链接，不能直接覆盖原始签收材料。
