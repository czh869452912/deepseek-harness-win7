# Git LFS 存储转换与完整同步

用户明确选择 Git LFS，保留原始历史备份和哈希映射。126 个未推送提交从原 tip `02ad32af6dee6f290085e9bc82ac4e8e522caf5e` 转换至 `74adf4c6ae5777599f454a8d7393b3529ccab194`；已发布远程锚点 `9629973ebe3cda9b82af3f24cff391159dddcf06` 没有改写。只选择 master 未推送区间，Source pin `cd5ef8148158c3a752a658978873241fdf8e2bbc` 保持。

原历史保存在 `.goose/out/lfs-original-history-20261007.git`，裸仓库有完整对象、无 alternates，`git fsck --full` 返回 0；所报 dangling 对象不是损坏。利用 NTFS 不可变 Git 对象硬链接避免再次占用数 GB，本机恢复不依赖新谱系；同磁盘不等于异地物理备份，此目录禁止自动过程清理。原始元数据另打包进已跟踪 `migration/storage/original-git-metadata.zip`，3352 个原 commit/tree/属性对象、6297669 字节，逐对象检查 Git SHA-1。

86 份现有 ZIP、6910079579 字节分别核验实际大小、原 Git blob SHA-1 和 SHA-256；实际证据内容未重压缩或删除。LFS 缓存通过硬链接建立。Windows 恢复少数指针文件时 `unlink` 报 WinError 32，Restart Manager 没有返回持有者；采用验证后的缓存内容复制恢复，原缓存字节不变，并重验恢复文件。原拒绝与重试保存，不归为原版或产品缺陷，不增加 Source 绕过。

首版完整树证明拒绝工具删除属性文件内部空行；诊断定位真实 diff 后，仅允许空行规范化和精确的一条 LFS 跟踪规则，所有非空旧规则/注释仍完全匹配。新回归包含带内部空行和注释的真实 LFS import，产品内容、模式、额外文件、其他属性、指针、原始元数据、归档、映射和祖先变动继续拒绝。

最终定向 **44 passed / 22.48 秒**，包含实际 LFS 转换和不含原 commit 对象的新 clone；早两轮 42/44 原始日志独立保留，不累计重叠。实际 126 提交/86 归档的完整映射证明通过，migration check 通过。映射以 UTF-8/LF 保存后重算 SHA-256，避免 Windows 写入换行转换使新 clone 的证明失效；元数据/资格 ZIP 用 `-text` 保存。

证明资料：

| 文件 | SHA-256 |
|---|---|
| `migration/storage/lfs-map.csv` | `9e56788dfea43214deb22915fa8703bb868943845a02f8a311bb47debc4aef54` |
| `migration/storage/original-git-metadata.zip` | `9ced7101cfb23bdc1efbdcd41cb66134ad2116c66508a25869d262107179283c` |
| `migration/storage/storage-qualification.zip` | `38755e1568cbfda91bfece90db8fc246bdf013c93ebed5b5d3abf532adfdff11` |

28 成员资格归档保存三轮定向 XML/日志、实际历史转换、备份审计、Windows 占用拒绝、属性拒绝及诊断、准备/恢复脚本和提供端字节；逐成员大小/散列和 CRC 已核验。上传日志可能含临时认证 URL，不加入此公开归档。

原 product/candidate/integrated SHA 及接受/拒绝回执保持不变。验证器首先检查原 commit 原始编码的 Git SHA，再证明只替换 LFS 指针/属性，提交作者、时间、消息及映射后的父图不变，随后解析旧提交的祖先身份。未知或篡改映射、错误锚点和产品字节不允许通过。CI checkout 获取 LFS 实体；现有 SDK/Profile 等判据、83 配对、20 组 Source、正常 3600 秒预算和九项原版例外没有放宽。

## 完整同步结果（2026-10-08 收尾）

全部 86 个 LFS 对象上传成功，普通快进推送 `9629973e..b529a990` 成功；`git ls-remote` 核对远程 master 为 `b529a9901c79f052f406d4ac4a692e5ebada159b`。没有强推或改写已发布历史。自动 LFS 锁接口和重复 batch 检查曾分别拒绝、返回 HTTP 502；首次 Git push 的服务器完整性检查返回 GH009/Internal Server Error，重试成功。只在成功上传且核对当前 OID 集合完全相同后，为本次 Git push 临时省略重复客户端上传，环境随后恢复；服务器完整性检查仍执行，没有持久 hook 绕过或 Source 例外。

下载 batch 独立确认全部 86 个远程对象可取回；随后实际流式下载 **6910079579 字节 / 1245.03 秒**，逐份验证大小、SHA-256 和原 Git blob SHA-1，全部匹配。没有另保存 6.9 GB 下载副本。独立 HTTPS 远程 clone 无 alternates、无原始 tip commit 对象；Git fsck、126 提交完整映射证明和 migration check 均通过，Source 子模块实际下载并固定至原 pin。克隆中的证据实体通过本地已核验不可变硬链接补全以控制磁盘占用，远程实际字节下载校验另行完成，二者没有混称。

干净 `b529a990` 上执行实际 Python 3.8.10 全套 `pytest tests`，收集 **10046 项**，正常 **3600 秒**预算后在 **67%** 超时，收尾总计 3600.43 秒。没有完整 XML，不能报告完整 passed/failed/skip 数；截至中断日志未出现失败标记，存储与迁移两组 16/28 项在本次全套中执行通过。所有权进程树清理成功，日志、输入、退出诊断和原始工作区保留；测试前后完整冻结输入及 HEAD 一致。该结果登记 failed/TimeoutExpired，不能称全套通过，也不是 83 配对、20 组 Source、解压或原版浏览器发行验收。

`migration/storage/remote-sync-verification.zip` 保留 22 成员、799812 字节，SHA-256 **`ac318b5cb18f1a33742bddacd6bc21404dacb8a35302f38732ef178f34aedc3e`**；成员大小/散列/CRC 全部核验。包括原始测试日志/输入/超时诊断、远端下载散列、独立克隆、所有 producer 和脱敏上传/推送记录，不含认证或签名 URL。同步通过和完整回归超时分别登记，原资格归档没有覆盖。

已完成独立克隆属于可重建过程材料，按持续清理授权尝试删除前核对了路径、HEAD、origin 和原备份；工具自动审批以 `blocked by policy` 拒绝，未执行删除，未尝试绕过。`.goose/out/lfs-remote-clone-20261007` 暂留，拒绝记录进入上述归档；原历史裸备份始终保护。

最新完整产品签收仍为原始 `83026446` 的 65 个有界合同。账本 86 项中 70 integrated、10 running、6 draft，16 项开放；七个广范围/056–064及九项原版例外不因存储转换或同步改变。后续优先减少回执夹具重复元数据解析并重新资格，再在正常预算执行新干净完整发行门禁；不能通过延长预算或放宽拒绝规则宣称迁移闭环。
