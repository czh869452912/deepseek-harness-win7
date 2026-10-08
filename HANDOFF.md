# Python 3.8.10 / Win7 迁移交接

交接日期：2026-10-07。此文档交接当前主目录迁移工作，供下一位维护者直接接续。**迁移尚未全部闭环，最新产品尚未通过新的完整发行验收。**

2026-10-08 第三次干净 `c53fff6d` 全套正常结束：10086 passed / 2 failed / 6 既有 skipped，3414.466 秒，完整 XML。拒绝为首次 DeepSeek 完整 HTTP 观察不同，以及 settled-reader 测试在数字 IPv4 的 DNS 线程等待期间达到250ms；原观察临时目录已被旧夹具删除，不把其差异归因于 DNS。数字 IPv4 直接构造地址，主机名仍保留可取消 DNS 等待，原短超时不变；新增真实服务器回归先失败后通过，186 HTTP/DeepSeek/重定向及14门禁/DNS控制分别通过，不合并计数。首次差异的后续原始观察保留，无重试或放宽比较。第四次新干净10095项/83配对/20组Source/同包实际解压及原版浏览器待执行；旧任务状态、九项例外与延期认证保持。下面“第三次待执行”等为此前历史，当前详见本日完整验证进展。

**2026-10-08 完整验证正在修复。** 当前工作目录 `D:\Project\deepseek-harness-win7`、分支 `codex/full-validation-performance`。第一次路径优化后的干净 `dea32b1c` 收集 10091 项，在正常 3600 秒、约 91% 超时，未取得完整 XML；精确实际 ZIP、冻结输入和拒绝日志已独立归档。随后补齐本机 `LongPathsEnabled=0` 下的插件历史访问、长路径夹具、浏览器夹具 UTF-8 控制通道及显式 Agent-owned Python 导出扩展；第二轮六处元数据/SQLite 名称生成优化的新鲜完整正例校验约 0.36–0.38 秒。新的完整门禁仍待冻结后执行，任务状态不自动提升。详细当前进展见 `docs/research/2026-10-08-full-validation-performance-progress.md`；下文未实施/65%/67% 的内容是此前基线和历史拒绝，不代表本轮最终结果。

## 起点与同步范围

第二次完整门禁干净 `13d0ae22` 已在正常 3600 秒内正常结束：10082 passed / 6 failed / 6 既有 skipped，3467.69 秒，完整 XML；仍被门禁拒绝，后续 Source/配对/实际解压未执行。六项失败已分别修复并通过16项 profile/工作区和15项前端复验；实际本机 official 重建的33个路径相关产物差异保留，reference 按已核验历史归档恢复冻结218产物/原记录，不改产品前端。第三次干净全套待执行，详细材料见本日验证进展；此前最新有界合同签收仍83026446/65。

- 本地仓库：`C:\Users\czh86\Documents\Codex\deepseek-harness-win7`，分支 `master`。
- 远程：`https://github.com/czh869452912/deepseek-harness-win7.git`，跟踪分支 `origin/master`。
- 最近产品修复的原始身份：`022852f5f508b792f289a86c82e7865d4f3dd24b`。
- 最近迁移证据/状态收尾的原始身份：`1c0e9180`；存储转换不把这些记录重标为新产品验收。
- 固定原版：`reference` 子模块 `cd5ef8148158c3a752a658978873241fdf8e2bbc`；不得自动升级 pin。
- 最近干净完整签收：`83026446`，65 个有界合同；不是全项目原版等价认证。

**全量同步采用 Git LFS。** 用户已明确选择仅转换未推送历史、保留原历史备份与哈希映射。转换原 tip `02ad32af6dee6f290085e9bc82ac4e8e522caf5e` → `74adf4c6ae5777599f454a8d7393b3529ccab194`，126 个未推送提交；已发布锚点 `9629973ebe3cda9b82af3f24cff391159dddcf06` 不变，后续正常快进推送。86 份 ZIP、6910079579 字节的实际内容全部保持原 SHA-256；Git 树内改存 LFS 指针。

所有旧提交名称按**原始身份**理解，在 `migration/storage/lfs-map.csv` 查对应新 SHA。`migration/storage/original-git-metadata.zip` 保留原始 commit/tree/属性 blob，`lfs-transport.json` 绑定映射与元数据散列。祖先检查验证原 Git 对象身份、提交元数据、完整树差异和原 ZIP 字节后才解析别名；不跳过检查，不改写原始验收/拒绝回执。LFS 工具去掉属性文件的内部空行，所有非空属性/注释行原样验证；产品源码变动仍拒绝。

本地完整原历史备份为 `.goose/out/lfs-original-history-20261007.git`，通过 `git fsck --full`，没有 alternates。使用不可变 Git 对象硬链接节省空间，逻辑自包含但与工作区同一磁盘；**不得把该目录作为过期测试结果清理**。原历史元数据和完整原 ZIP 内容也随全量同步保留。当前 Windows 的少数 LFS 指针因删除共享限制采用校验后复制缓存字节恢复，未删除原数据；占用者未归因，不新增原版例外。

新环境须下载 LFS 实际内容；只获得指针时证据散列检查会拒绝。示例：

```powershell
git lfs install
git clone --recurse-submodules https://github.com/czh869452912/deepseek-harness-win7.git
cd deepseek-harness-win7
git lfs pull
git lfs fsck
```

普通 clone 会同时保留工作区文件和 LFS 缓存，需要为约 6.9 GB 证据及缓存预留空间。本机采用硬链接控制临时占用，归档必须保持不可变；新增回执使用新文件名。CI 已启用 LFS checkout。方案和额度边界见 `docs/research/2026-10-07-full-remote-sync-plan.md`，转换及验证记录见 `docs/research/2026-10-07-lfs-storage-progress.md`。全量同步不等于完整迁移或发行验收通过。

**2026-10-08 同步核验已完成。** master 全量普通快进到 `b529a990`，86 个 LFS 对象上传后实际远程下载全部 6910079579 字节，大小/双散列全部匹配。独立远程 clone 无 alternates 或原 tip 对象，Git fsck、126 项映射及 migration check 通过，原版 pin 不变；证据实体用本地核验硬链接补全，实际远程下载另行流式核验。首次服务器 GH009/Internal Server Error 和重复 LFS 接口 502 拒绝保留，重试成功，没有强推。最终记录提交另在该同步基线上追加。22 成员小型归档 `migration/storage/remote-sync-verification.zip` SHA-256 `ac318b5cb18f1a33742bddacd6bc21404dacb8a35302f38732ef178f34aedc3e` 保存完整验证材料。

该干净基线全套收集 **10046 项**，正常 **3600 秒**、**67%** 超时，无完整 XML；未取得全套通过，日志截至中断未见失败标记。16/28 项存储/迁移控制在全套中通过，完整输入/HEAD 前后不变；拥有的进程树已结束，失败工作区 `.goose/out/lfs-storage-full-regression-v1/pytest-workspace` 保留。同步 passed 与全套 failed/TimeoutExpired 分别入账，不替换 `83026446/65` 最新完整产品签收。后续仍优先解决重复回执验证成本再做新干净发行门禁。

自动审批拒绝删除已验证的可重建独立克隆（`blocked by policy`），所以 `.goose/out/lfs-remote-clone-20261007` 暂留；拒绝记录保留，不绕过删除。原历史 `.goose/out/lfs-original-history-20261007.git` 必须继续保护，不纳入自动过程清理。

## 先读这些本地记录

1. `AGENTS.md`：Python 3.8.10、Win7、Cordis ownership/effect、原版前端和 canonical boot 规则。
2. `migration/README.md` 与生成的 `migration/status.md`。
3. `docs/research/2026-10-07-current-work-close-status.md`：最新完整状态、成本测量、候选研究、未闭合项及优先顺序。
4. `docs/research/2026-10-07-frontend-preflight-order-progress.md`：最新完整门禁拒绝及两项已修复失败。
5. `migration/upstream-bug-exceptions.json`：九项原版缺陷发现索引；实际接受由各 oracle 的精确谓词决定。

账本当前共 **86 项：70 integrated、10 running、6 draft**。70 含历史/工具类记录，不能用作当前产品完成率。`accepted_upstream` 仍未建立。

## 已完成与验收情况

| 提交/范围 | 已完成 | 仍存在的边界 |
|---|---|---|
| `46c8d4e1` | 导入固定原版完整官方前端 218 文件，公共 Schema refs 对齐字符串键 | 原版 React/TSX/CSS 不因主机适配而改写；浏览器功能旅程不是完整 wire 认证 |
| `2003821e` | 四处旧前端/Schema 消费者预期同步，291 实际回归、32 必需控制通过 | 不累计重叠数量，不代替干净发行门禁 |
| `6aabea10` | pytest 模块/类/完整方法名绑定，121 相关控制通过 | 未放宽错类/错模块/歧义拒绝 |
| `022852f5` | 脏目录在前端清单读取前拒绝；rg 打包夹具复制完整记录的 shell/client 输入 | 5 定向、35 预检分别通过；占位 EXE 仅分发控制，不是实机运行证据 |
| 056–064 | 权限/预设、工具错误/SDK 元数据、工具持久发布、Agent 依赖、问答、Message、FS、子代理配置、Unicode 已有正式实现和局部证据 | 九项任务仍 running，最新统一签收尚未完成 |
| `1c0e9180` | 测量及路由/路径/浏览器研究归档，逐成员核验；迁移 check/ready/status 和 diff 检查通过 | 仅证据/状态提交，没有推广候选或实施新优化 |

最新干净 `6aabea10` 完整门禁收集 **10030 项**，在正常 **3600 秒**、**65%** 进度时超时，无完整 XML，不能给出完整 passed/failed 数。两项失败由单项确认并在 `022852f5` 修复；修复后的产品没有新的完整通过。后续 **83 配对、20 组 Source、实际解压和原版浏览器**阶段没有开始。历史 9277 passed / 6 skipped / 3556.59 秒属于旧产品，不得冒充当前通过。

## 第一优先：减少验证重复开销

实际 Python 3.8.10 完整正例回执测量：13555721 字节；冷构造 345.08 秒，暖构造 0.452 秒、序列化 0.068 秒、写入 0.019 秒、完整校验 1.47 秒，总计 2.01 秒。完整校验 profile 为 2.154 秒；`Path.resolve` 5279 次累计 1.168 秒，`nt._getfinalpathname` 20605 次累计 0.838 秒。**优化尚未实施**，不能推断完整套件加速比例。

入口：`tests/test_current_release_gate.py::extracted_receipt`、`scripts/verify_release.py::validate_extracted`；热点包括 `llm_prepared_oracle.py`、`canonical_llm_oracle.py`、`sdk_profile_oracle.py`。已有 `scripts/import_paths.py::resolve_import_path` 仅在单次元数据校验、缺失首级目录时减少重复解析，实际文件、路径逃逸及链接语义不放宽；回归见 `tests/test_import_paths.py`。后续可评估相同保护是否适用于其他元数据校验，不能新增文件散列缓存或绕过真实路径检查。

测量脚本第一版从 `report.provenance` 猜 candidate，遗漏后加入的 Unicode 字段，被拒绝；第二版保存实际返回的 candidate 后完整通过。接续务必使用实际 tuple 和保存的 candidate，保留错误基线。

## 第二优先：推广候选研究并补缺口

以下修改只在忽略目录中的独立候选，**主目录产品尚未包含**：

| 提案 | 修改与结果 | 推广前必须补齐 |
|---|---|---|
| `dsh/subagent/model_selection.py` | 半配置错误保留原版反引号；七条实际子 Agent 路由候选匹配 | 新鲜完整 Source/Root/自有解释器、实际消费者；完成回合 fork 前缀、后台继续及竞争仍未认证 |
| `dsh/subagent/canonical_tools.py` | 按 stopReason 提供原版 foreground 文案，区分诊断缺失/空值并保留部分输出 | 36 终止组合候选匹配，但该组没有独立完整输入前后守卫，不能借用七路由的资格 |
| `dsh/workspace/paths.py` | realpath 不强制把 Windows 反斜杠换为斜杠；六项真实 Unicode 目录/文件路径候选匹配 | 第三处提案不在两文件 v10 守卫范围内；补跨消费者路径与实际导入资格 |
| minimal 原版浏览器 | Source/候选完成真实工具、下一请求、取消、物理关闭、冷恢复 | 完整最终快照仍有四处原始工具注册顺序差异；结果为 `different`，不得排序/删除字段改成 matched；完整网络载体仍未闭合 |

七路由 v10 资格记录含 **477 实际导入、15488 输入前后守卫**，只覆盖当时的两文件 overlay。Source/import 名称和任务报告不是原版等价证明。Browser observer 的 native-only 诊断移入独立 diagnostics 后仍保存，完整原始结果留存。

## 归档定位与重建

本地 `migration/evidence/artifacts/`：

| 归档 | SHA-256 | 用途 |
|---|---|---|
| `RELEASE-FIXTURE-MEASUREMENT-20261007-022852F5.zip` | `daf504c784479ea41538881474afe69a8c082915198f59340efdf40c1c3586c3` | 36 成员；六个样本、实际 candidate、profile、原始失败、被测字节及维护记录 |
| `ROUTE-PATH-BROWSER-RESEARCH-20261007-6AABEA10.zip` | `a6d37689e5b2f51c4e89cc543dadf14d4cce7c77b8b8bd142dae1d7baf0694c8` | 120 成员；路由/终止/路径/浏览器观察、失败版本、比较器、三处候选字节和两文件 overlay |
| `CURRENT-GATE-REJECTED-20261007-6AABEA10.zip` | `422ba5b5e1d19ccac5b74c52382581cbf2a6cc9633f435acbc705c8923d8958d` | 951 成员；精确拒绝候选、冻结输入、原始超时/退出和清理审计 |
| `FRONTEND-PREFLIGHT-ORDER-20261007-6AABEA10.zip` | `f7fd7140b7093a2e116f8a35c3c3029b3f7ca20f89452bebb3c716c207b7500f` | 17 成员；两失败基线、5/35 通过、观察环境拒绝和精确修复 diff |

精确基础包位于拒绝归档成员 **`candidate-portable.zip`**，SHA-256 `ac8d4f88d98d2ea03d50b62b2b703e39974b939754d186a72ae16fe4ca53deb8`。研究归档内 `route-execution-owned-qualified-overlay-v10.zip` 为两文件 overlay，SHA-256 `767e4a6a5d6c22a9016355050853459b9da79c51b7b6d34acfb3413c052ca6d5`。安全解压精确基础包，再应用这两个文件即可重建 v10；第三处路径提案在 `current-owned-proposal/dsh/workspace/paths.py`，需独立重新资格，不能重标 v10。

忽略目录 `.goose/out/acp-a4-work/` 仍有原始脚本/日志和独立候选；新环境不能依赖这些未同步文件。归档内 producer/manifest 可定位散列与完整观察，恢复运行脚本时须适配其原工作目录和 `parents[3]` 路径假设。不要直接在 archive 或最新产品上不加校验地覆盖文件。

## 接续命令

在完整 clone 并获取 LFS 实际内容后执行；本地原始备份不作为祖先检查的隐藏依赖：

```powershell
git status --short
git submodule status reference
.venv\Scripts\python.exe --version
$env:PATH = 'C:\Users\czh86\AppData\Local\Volta\tools\image\node\22.22.2;' + $env:PATH
node --version
.venv\Scripts\python.exe scripts\migration.py check
.venv\Scripts\python.exe scripts\migration.py ready
```

Python 必须为 **3.8.10**；观察器 Node 为 **22.22.2**。Node/Chromium 是开发验收依赖，不是便携产品依赖。已有 Edge 路径 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`；在其他机器使用实际可用的 Chromium 路径。API 凭据不写入交接或证据，不能擅自调用付费服务。

每一部分完善实际回归和证据后单独提交。产品任务完成前必须执行：

```powershell
.venv\Scripts\python.exe -m pytest tests
```

提交并确认干净后执行统一发行门禁，输出目录采用新名字，避免覆盖旧拒绝；下例目录必须尚不存在：

```powershell
.venv\Scripts\python.exe scripts\verify_release.py --browser 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' --output-dir '.goose/out/handoff-next-clean-gate-v1'
```

缺失固定开发依赖时先阅读门禁的 `--prepare` 行为再准备。不得用 `--allow-dirty` 的开发预览作发布资格，不扩大正常 3600 秒预算，不跳过必需 lane 或修改九项精确例外。完整门禁执行期间不得改其冻结输入；真实解压及浏览器必须验证同一个精确候选包。

维护命令：

```powershell
.venv\Scripts\python.exe scripts\process_artifact_retention.py
.venv\Scripts\python.exe scripts\migration.py status --write
git diff --check
```

`process_artifact_retention.py --output` 表示**既有 release 输出目录**，不是审计 JSON 文件名。用户已授权持续自动清理过期、可重建过程产物，无需再次请求权限；保留真实回执/观测、失败日志/XML、精确候选 ZIP、冻结输入、未知/变更/活跃文件，不以 `.gitignore` 作为任意删除依据。最近门禁清理 932 合成文件/12629254058 字节；交接前维护没有新增合格材料。

## 最后需要关闭的范围与不可改变的决策

开放 16 项：056–064 九项 running、六个 draft 父范围（ACP transport / DeepSeek wire / profile journeys / Session replay / Tools policy / Web connection）以及 JS036 running/partial。顺序为成本优化 → 正式推广与补观察 → 新干净完整门禁 → 九项有限集成 → 六父合同及 JS036 剩余 Node/图 ABI/Ready/重入/竞争 → 最终统一验收。

九项原版缺陷例外维持精确谓词；Python Future 调度差异另为语言适配。启动取消/cache 时序、Proactor/HTTP 关闭及部分文件系统错误仍未归因，不新增抑制、不把未知失败当原版 bug。真实 Win7 和目标浏览器认证按用户明确决策延期，不再重复询问，也不能用当前 Windows 的 Python 3.8.10 通过记录宣称 Win7 实机认证。

架构继续 canonical profile/boot、Cordis 动态服务和可撤销副作用、原版 Connection/Typert Remote `/api/remote.mux`。不恢复旧 `ApiProxy`/双业务 SSE/`--mode` 启动路线，不通过更改原版前端迎合主机协议。`expected_paths` 为影响提示，不是编辑权限；跨提供端/消费者的同一合同修改需一并处理。`migration.py` 不自动调度或转状态；已 integrated 的旧任务不塞入未解决 findings，新的未签收状态应明确记录。
