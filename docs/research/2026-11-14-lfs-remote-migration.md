# 历史证据远端归档及 LFS 回收状态

2026-11-14，承接 [本地存储改造](2026-11-14-evidence-storage-migration.md)。用户明确授权提交、推送并处理已有 LFS。源码改造 `cde273216c78f5f51f0e9f0ae3d958169e624a65` 已推送至 `master`；当前树 `git lfs ls-files --json` 无文件。用户原有 `.gitignore` 的 `/.local_plugin/` 修改未提交。

## 原始材料已发布

[历史证据归档 Release](https://github.com/czh869452912/deepseek-harness-win7/releases/tag/evidence-archive-20261114) 是历史材料归档，标记为 prerelease、不是 latest，也不是新的软件发行或资格认证。目标是上述源码改造提交，未修改原产品发布标签或历史候选身份。

- 240 个原 ZIP，合计 13,586,583,847 字节，全部有持久附件位置。238 个上传到新归档 Release；2 个复用已有 Creative preview 附件，尺寸及 SHA-256 完全匹配，避免重复上传。
- 新归档 Release 共 241 个附件：238 个原 ZIP、原始身份索引、位置映射及回执归档。新增上传 13,661,891,029 字节，经普通 Release 接口上传，没有再次使用 LFS。
- `historical-receipts-20261114.zip` 保存 1,225 个原回执/历史证明文件及成员清单；尺寸 185,433,473 字节，SHA-256 `31b4abc276f757cb369195483b73cdb906184ed3300364e01b34a4fb04f012c3`。打包时逐个核对成员原字节。
- 发布前和发布后分别检查全部原归档与附加资产的 `uploaded` 状态、尺寸及 GitHub SHA-256 digest；发布后逐项确认正式 URL。两个小型 JSON 附件和一份 673 字节原 ZIP 另行下载，逐字节/哈希核对；两个 JSON 的正式 URL 还做了无需登录的回读。

原始身份仍由 [external-artifacts.json](../../migration/storage/external-artifacts.json) 提供，其 SHA-256 保持 `47bdb484028bf8161cde53810f8404a402a1d2d0a10fb18bc2936a426c7d3c5c`，未修改被导出回执绑定的索引。新增 [位置映射](../../migration/storage/external-locations.json) 只提供下载位置；[远端核验回执](../../migration/storage/remote-evidence-archive-20261114.json) 记录附件 ID、身份摘要、读取范围和发布状态。位置映射的原字节也作为 Release 附件保存，SHA-256 `b992f65a783dee81b2cbd7fbeb4a53607afb0bc3899d2352fb1b19ee6f0e13ee`。

这些检查证明迁移后的存储身份及可取回性，不代表重新执行了历史测试，也不是 240 个 ZIP 的全量远端下载。源码改造的 147 项定向测试结果保持；此次追加仅涉及存储位置和文档，未另跑完整回归或 Portable 门禁。源码推送没有触发自动 CI 运行，未声称远端 CI 已通过。

## GitHub LFS 尚未回收

当前分支停止跟踪 LFS 不会删除历史服务端对象。[GitHub 官方说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/removing-files-from-git-large-file-storage) 要求联系 Support，或删除重建仓库；本轮保留现有仓库及其元数据，没有采用删除重建。

使用现有管理员授权尝试官方 LFS disable 接口，实际返回 HTTP 404；没有禁用成功，也没有清除对象。该接口文档并不等同于逐对象存储回收接口。LFS batch 元数据探针此前返回原 673 字节对象仍可下载，只读取元数据，未下载 LFS 对象。账户用量 API 缺少所需权限，未为盘点而扩大凭据 scope，因此没有账户配额归零的证据。

2026-11-14，用户明确授权回收后，已通过仓库的 **Remove LFS objects** 表单提交[具体请求](2026-11-14-lfs-server-cleanup-request.md)，明确选择不能删除重建仓库。Support 最初以账户仅提供自助支持为由关闭工单；补充 LFS 存储配额/计费说明并请求转交后，已重新打开，观察状态为 **Open**。请求仅回收清单中已备份的 240 个对象；额外对象先提供清单，若需退休/改写 refs 先明确范围。尚无实际回收确认，没有强推或修改旧历史，不能宣称旧 LFS 已清理完毕。提交/状态截图和具体工单地址保存在本轮忽略的输出目录，不公开账户联系信息或完整支持会话。

提交后，同一 673 字节 LFS 对象的 batch 元数据探针仍返回 `download_available=true`，没有获取对象字节。这至少证明该对象尚在服务端，不能将工单提交/重开视为配额释放。

## 清理与后续复审

上传全部结束且正式附件核验通过后，再对回执 ZIP 及成员逐项核对尺寸和 SHA-256，移除仓库外打包时复制的 1,219 份散装 JSON，释放 606,883,296 字节；Git 中原回执、归档成员及历史证明均保留。加上本地阶段已清理的 144,733,593 字节，本轮可重建/重复资产合计释放 751,616,889 字节。没有把 13.59 GB 的位置迁移称为全机净释放同样空间。

仓库外 `deepseek-harness-win7-evidence` 保留 240 个原 ZIP 和回执 ZIP，作为 Support 回收期间的回退副本；owner 为仓库维护者，下一复审节点为 Support 答复或 2026-11-21（先到者）。原 `.git/lfs`、reflog 和受保护历史备份仍保留，等待 Support 对历史引用的实际要求，不做全局 prune/GC。命令、上传/核验结果、早期草稿 URL 检查失败及修正后的日志、逐成员清理审计均保存在本轮 `.goose/out/evidence-storage-20261114/`，未覆盖失败诊断。
