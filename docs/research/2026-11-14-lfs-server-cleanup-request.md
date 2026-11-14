# GitHub LFS 服务端清理草稿（未发送）

下面的请求须在不再使用 LFS 的源码版本推送、原始归档完成持久外存后，再按 GitHub Support 的实际要求提交。本机 GitHub CLI 当前未登录；本轮没有上传附件、删除远端资产、强推或发送工单。

## Support request draft

Subject: Request guidance on purging retired Git LFS objects while preserving repository metadata

Repository: https://github.com/czh869452912/deepseek-harness-win7

I maintain this repository and want to stop using Git LFS for historical test evidence. The locally referenced set contains 240 unique LFS objects totaling 13,586,583,847 bytes. All are historical test ZIP archives under migration/evidence/artifacts/. There may be additional server-side objects not visible in local refs.

I have preserved the original archives outside Git and verified their sizes and SHA-256 identities. The object inventory is migration/storage/external-artifacts.json; each sha256 is the corresponding LFS OID. The current source migration replaces archive-dependent tests with minimal original members and disables default LFS checkout in CI. Historical result and candidate identities are preserved.

Before rewriting published history or deleting any repository, could you confirm the supported process and eligibility for purging retired LFS objects and stopping future storage charges? I would prefer to preserve issues, stars, forks, release assets, and repository identity. Please advise which branches/tags/references must first be retired or rewritten, whether the supplied object inventory is sufficient, and whether additional repository-associated objects must be included.

I understand that removing LFS tracking or rewriting Git history alone does not remove server-side objects, and I am not requesting deletion of published release attachments or repository metadata.

## 服务端操作前的检查点

- 当前工作区改造必须先提交并审查，再明确上传位置。不要把 240 个 ZIP 再添加为普通 Git 文件。
- 当前本地档案路径：`C:\Users\czh86\Documents\Codex\deepseek-harness-win7-evidence`。它是持久迁移副本，需在远端副本完成上传及核验前保留；不是可删除测试夹具。
- 不将整个 `.git` 缓存或保护性备份删除作为“GitHub 配额清理”；本地清理与服务端计费不同。
- 若必须改写历史，先在隔离副本演练，覆盖仍引用归档的发布标签、archive 标签和分支，记录旧/新提交对应及签收影响。当前历史包含先前 LFS 转换证明，不能盲目过滤后继续声称该证明有效。
- 删除并重建仓库会影响仓库元数据。先取得 Support 的实际答复；没有答复前不承诺配额立即归零。
- 约 601 MB 的普通 Git evidence JSON 本轮保留原字节。后续如精简或外置这些回执，需要单独迁移来源索引和文档链接，不能直接覆盖原始签收材料。
