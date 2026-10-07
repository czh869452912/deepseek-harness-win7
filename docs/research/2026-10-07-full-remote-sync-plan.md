# 完整迁移同步：大文件与历史身份方案

用户要求同步全部迁移代码和证据，不再只推 handoff。本记录给出只读审计和可执行的方案边界；截至审计，尚未改写历史、删除证据或上传 LFS 对象。

## 实测输入

审计 HEAD `ef5b3710d5d8310cf7326e56ac8d0fdcc0072bec`，远程 `origin/master` 为 `9629973ebe3cda9b82af3f24cff391159dddcf06`；125 个本地提交尚未推送，远程是本地祖先，可以只转换尚未发布的区间，保留远程历史并最终普通快进推送。

| 项目 | 结果 |
|---|---|
| 未推送的新增普通 Git blob | 3547 个 / 7273391083 字节（6.774 GiB，未压缩对象大小） |
| 其中证据 ZIP blob | 80 个 / 6852754007 字节（6.382 GiB） |
| 超过普通 Git 100 MiB 的 blob | 14 个 / 3905479236 字节 |
| 当前跟踪证据 ZIP | 86 个 / 6910079579 字节 |
| 没有被顶层 evidence JSON 直接引用的 ZIP | 19 个 / 1052643082 字节；并不等于可删除 |
| 当前可用磁盘 | 只有 C 盘，约 6.25 GB；不足以直接复制全部 ZIP 再制作完整独立备份 |
| Git LFS | 已安装 3.5.1；现有 ZIP 尚未按 LFS 存储 |

`git lfs migrate info` 只读检查列出 86 ZIP、约 6.9 GB；它统计扫描到的文件，不能等同于上述未推送区间的唯一新增对象计数。上传成本以最终转换的唯一 LFS OID 清单为准。

## 清理不能单独解除阻塞

14 个超限对象中，13 个仍有顶层证据记录引用：最大的 Session storage 684522308 字节有 44 条 acceptance 引用，Session query engine 630761252 字节有 36 条，最近干净发行的 SDK retention 263454668 字节有 66 条 acceptance/verification 引用。

剩余一个超限对象 `CONFINED-CONSOLE-WEB-QUALIFICATION-20261007-94A34B5D.zip` 没有顶层 JSON 直接引用，但仍被 `docs/research/2026-10-07-confined-console-progress.md` 引用。19 个没有直接引用的 ZIP 中也包括独立反证、失败基线和 qualification。删除候选必须追踪文档、嵌套归档、重建关系及真实失败的完整保留链，不能仅按 `validity=historical`、`stale-inputs`、失败结果或日期删除。

历史失败是反证，不因为修复成功就变成无价值垃圾。即使从当前目录删掉全部大型 ZIP，旧提交仍含超限 blob，普通 push 仍会发送它们。删除或重新压缩已跟踪档案若想减小推送历史，同样需要历史调整，而且会改变归档 SHA-256；因此不优先采用此方案。用户已授权的 `.goose/out` 可重建过程清理继续按现有规则执行，其与跟踪的验收证据不同。

## 推荐：Git LFS，保留旧身份与验证映射

Git LFS 用小指针替代 Git 树中的大型 blob，并保留原文件实际字节。GitHub Free/Pro 的 LFS 单文件上限为 2 GB，当前最大 ZIP 在范围内；Free/Pro 目前包含 10 GiB 存储和每账期 10 GiB 下载额度。约 6.4 GiB 新 ZIP 对象在总免费额度内，但账户其他仓库的既有使用和预算尚未核实，不能保证剩余额度或承诺零费用。上传不计下载带宽；协作者和 Actions 下载会使用仓库所有者的下载额度。见 [LFS 文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)及 [LFS 计量规则](https://docs.github.com/en/billing/concepts/product-billing/git-lfs)。

这不是只添加 `.gitattributes`：必须转换尚未推送历史中的普通 ZIP blob。转换会改变这些提交及其后代的 SHA。`scripts/migration.py::validate_checkout` 当前检查 baseline 和每个 integrated 原始提交是 HEAD 的祖先；只运行 `git lfs migrate import` 会使新克隆的祖先检查失效。原版 pin 不应转换；原有原始接受/拒绝回执也不应批量改写为新 SHA。

实际推进步骤：

1. 核对账户可用 LFS 容量/预算，清点所有待上传唯一 OID；解决临时磁盘空间。原始提交必须先有可恢复备份；本地 backup ref 只防 GC，不等于独立的物理备份。不要先清空历史对象来腾空间。
2. 保留原始 HEAD、原提交图及全部证据字节；记录每个转换旧 SHA → 新 SHA。只选择 `master` 尚未推送区间，明确排除已发布 `origin/master`，不使用 `--everything`，不改远程既有历史、不强推。
3. LFS 只覆盖 `migration/evidence/artifacts/*.zip`；不将运行时 DLL/EXE、前端、Source 子模块或整个仓库一并转换。转换后证明所有 ZIP 的实际大小/散列不变，所有产品文件字节及 reference pin 不变；逐提交核对允许的 LFS 指针和属性变化。完整 object map 是对照资料，不是直接“放行”依据。
4. 给迁移祖先检查补可审计的存储转换身份解析：原回执中的 product/candidate/integrated SHA 保留；只有经验证的旧 → 新对照可用于祖先检查。不跳过检查，不将任意 missing SHA 视为通过，不把存储转换视为新产品验收。补未知/篡改映射、错误祖先、改变产品字节和无转换的旧行为拒绝控制。
5. 更新 clone/恢复说明和 CI 的 LFS 下载。当前 `actions/checkout@v4` 没有 `lfs: true`；没有获取实际内容时 migration 的散列检查会读到指针，应明确拒绝而不是把指针当证据。
6. 验证 migration check、证据散列、输入清单、全量测试及新环境恢复。最新完整发行仍未签收；存储迁移和当前 10030 项完整测试超时分别披露，不伪造新完整通过。
7. 先上传全部所需 LFS 对象，检查远端可取回；确认 `origin/master` 仍为转换后 HEAD 祖先，普通快进 push。验证新克隆/受控新 Git 对象目录中的祖先检查和实际内容解析，确认不能依赖本机遗留的旧 commit 对象。

完成后应交付：全量远程提交、唯一 LFS OID 清单与散列、原始历史备份定位、验证后的旧新 SHA 映射、CI/恢复方式，以及存储资格和产品验收各自的真实结果。

## 其他方案

| 方案 | 优点 | 代价及边界 |
|---|---|---|
| 源码/索引进 Git，证据和完整原历史放 GitHub Release | 证据原字节和原历史可以作为不可变归档保存；普通源码 clone 较小 | 仍需移除未推送历史中的超限 blob，或发布清晰标识的新源码谱系；补下载/散列验证、历史恢复和祖先身份机制。Release 应是研究归档，不得冒充通过发行门禁的产品版本 |
| 完整 Git bundle 分卷归档 + 可恢复源码快照 | 原历史恢复后原 SHA 完全保持；不需把原始 commit 字段重标为新身份 | bundle/分卷需要额外空间和可访问存储；新克隆须先恢复原对象及分支才能运行现有祖先检查，普通 remote 本身不再足以复现。需要明确用户接受此交付方式 |
| 证据内容去重 / 重新归档后普通 Git | 可减少反复嵌套相同便携包的长期体积 | 不保证每个对象小于 100 MiB；重建所有受影响档案、SHA 引用和历史，工程量大，且必须保留原反证。适合作为后续存储维护，不作为本次最快同步方案 |

GitHub 普通文件限制见 [官方说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。仅清理工作区或添加新的 LFS 跟踪规则不能消除既有提交中的超限对象；也不能在没有完整恢复链时删掉被称为“历史”的验收证据。

## 决策点

用户已明确选择 Git LFS，并授权保留原始历史备份和哈希映射。后续只转换未推送区间，落实上述字节与历史证明后全量同步；原有自动过程清理授权继续有效。
