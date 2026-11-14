# 历史测试证据退出 LFS：本地实施记录

2026-11-14，基于 `0e58297cb4869014662135c6ace7e96b29fd723e` 工作区实施；存储改造已作为 `cde273216c78f5f51f0e9f0ae3d958169e624a65` 提交并推送至 `master`。用户原有 `.gitignore` 的 `/.local_plugin/` 修改保留，未纳入提交。当前 HEAD 已无 LFS 文件，旧历史仍包含 LFS 指针，不声称历史或服务端对象已经清除。

## 已完成

- 240 个 ZIP、合计 13,586,583,847 字节，已复制到 `C:\Users\czh86\Documents\Codex\deepseek-harness-win7-evidence`，逐个验证源与目标尺寸及完整 SHA-256 后，才移除工作树原件及 Git 跟踪。外部目录同时保存原回执与历史转换证明；没有销毁原始证据。
- Git 保存 `migration/storage/external-artifacts.json`，保持原路径、LFS OID/SHA-256 及尺寸。不记录本机绝对路径作为公共解析规则；显式配置 `DSH_EVIDENCE_ROOT`，不自动联网取材料。
- 从三个原归档提取 8 个测试实际使用的原始 JSON 成员，gzip 无损压缩后连同来源清单共 5,537,183 字节。消费测试同时检查成员原字节与原归档身份，继续执行原正例与破坏拒绝判据。
- 台账默认检查索引/checkout；明确显示外部字节未核验，不赋予当前验收资格。`--verify-artifacts` 显式校验外部原件，缺失、截断、同尺寸篡改均拒绝；历史整合状态与原回执字节保持。历史 Git 转换的元数据证明与归档实体校验分别执行。
- 前端冷恢复从已经版本化的原构建成员恢复，仍检查完整构建摘要、全部成员哈希与原构建记录；不再从历史测试 ZIP 恢复。上游浏览器代码未改。
- 移除当前 `.gitattributes` 的 LFS 规则，忽略按需恢复到原路径的 ZIP，两个 CI 工作流关闭默认 LFS checkout，更新开发指引与证据存储规则。

## 验证结果

本轮仅做与存储提供端、直接消费者、CLI 和历史证明相关的定向验证，没有运行完整回归或 Portable 发行门禁。

| 检查 | 结果 |
|---|---|
| `test_evidence_assets`、`test_migration_workflow`、`test_migration_storage`、三个归档消费测试、`test_reference_preparation` | Python 3.8.10，93 passed，39.511 秒 |
| `test_frontend_import` 与 `test_current_release_gate` 的 frontend / node setup 消费者 | 固定 Node 22.22.2，54 passed，452.826 秒 |
| `scripts/evidence_assets.py verify` | 240 个原归档、13,586,583,847 字节，尺寸及 SHA-256 全部通过 |
| `scripts/migration.py check --verify-artifacts` | 原外部字节与历史证明通过；不是新候选资格认证 |
| 最终 `scripts/migration.py check` / `ready` | 均退出 0，明确提示索引检查不核验外部字节 |
| 当前索引/工作树中历史 ZIP | 均为 0；工作树属性不再给这些路径设置 LFS filter |
| Python 3.8 语法与 staged/unstaged diff whitespace 检查 | 通过 |

前期一次新增测试因测试消费者错误继承任务状态而失败，修正后通过。前端发行消费者第一次运行 47 passed / 6 failed，根因是 PATH 使用 Node 22.20.0，Source 观察器要求 22.22.2；改用项目已有固定运行时后 54 项全部通过，没有放松判据。一次移除前的索引校验因新生成 JSON 的 Windows 换行转换而拒绝，规范为已记录的 LF 字节后才执行移除。

命令、XML、日志、出口校验回执、历史大小盘点及清理审计保存在 `.goose/out/evidence-storage-20261114/`；机器摘要为 `result.json`。失败日志与报告保留，未覆盖原观察。

## 清理与保留

已移除本轮 15 个已结束的合成工作区/Source 缓存，按逻辑文件长度合计 144,733,593 字节（约 145 MB），保留 XML、日志、失败报告及必要的 JSONL 原始 Source/native 观察。未全局清理 `.goose/out`、系统临时目录或其他任务资源。

仓库外 evidence 目录是有 owner、用途与复审节点的持久迁移副本，须保留到远端持久归档完成并核验后再复审。原有 `.git/lfs` 缓存与历史备份仍保留，因为旧 refs/历史尚未退休。移出工作树的 13.59 GB 是存储位置调整，不是全机净释放同样空间。

普通 Git 中约 601 MB 的未压缩 evidence 回执继续保持原字节；其本地可达历史 blob 存储量约 53 MB。包括其他资源的可达 blob 存储量合计约 209 MB，不能把本地 6.13 GiB pack 当作 GitHub 当前仓库大小。先处理 LFS，不立即对这些回执做有损精简或大规模历史改写。

## 本地阶段结束时的边界

本地验证结束时尚未执行远端操作。其后用户明确授权提交、推送并处理已有 LFS，已通过现有 Git Credential Manager 凭据完成推送；没有要求扩大凭据权限。GitHub 已计费 LFS 不因本地移除而自动释放。

远端归档与服务端回收单独记录；已准备 [Support 草稿与检查点](2026-11-14-lfs-server-cleanup-request.md)。只有在明确需要时，才在隔离副本演练历史改写并单独审查发布标签、分支和旧资格身份的影响；本次 147 项定向通过不是改写历史或新发行包的资格证明。
