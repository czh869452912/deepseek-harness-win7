# Provider、UCRT 与默认组合接续

本轮继续 HANDOFF 的 16 项收尾。四个工具策略场景的 11 个 token 差异已获用户有限批准；原始数值、输入/header 锚点和九个上游 bug 精确判据保持留存。此批准不覆盖其他业务差异。目录四处完整行排列与独立 mux 流交错的提案仍待答复，不能据此签收 Web。

## 完整拒绝与修复

干净候选 `3dca2a325dde5e89cb815559dd03a4d8ace4baa4` 的第九轮完整 Python 正常退出 1：10444 passed、4 failed、6 既有 skip，XML 4215.139 秒。三个失败是 creative 夹具的旧 bundle 表遗漏新增 native 扩展；一个是保留短 pytest 工作区时 `WinError5`。16619 个冻结输入、干净 HEAD 和精确 ZIP 在物理退出后未变；22 组 Source、83 配对、实际解压和浏览器阶段未执行。

拒绝封存于 `CURRENT-RELEASE-REJECTION-20261010-3DCA2A32.zip`，SHA-256 `ae7c14c5db370ccef4191be8bf536250a5b9fd0971df265ba1b955c1b343b5ef`。原始 23 字节 CRLF 孤立观察、原始映射和 WinError5 另封存于 `RETENTION-ORPHAN-20261010-3DCA2A32.zip`，SHA-256 `f4d787f271314baa26dc9852a77f6788d4138f94c4338e693b21e357b9b1eef7`。归档后将确属已退出夹具的观察恢复到其实际保留目录，原始路径不重标。占用者未归因。

产品修复：creative 测试表对齐活动 bundle；保留工作区增加有限、可中止的共享冲突重试，拒绝目标覆盖和链接替换，持续冲突仍失败并保留首个错误。真实 Win32 读句柄释放/持续占用、碰撞和首个结果控制纳入测试。

实际浏览器发现 `llm/listConfigurableProviders` 丢失扩展字段且注入 `declared:null`。产品现按 Source 浅拷贝整行，只分离 settingsPath 数组；省略/null/false/true、扩展字段、替换/释放和路径借用均有原版事实夹具。新 Source/Native 14 RPC、42 持久事件在保持完整 Schema 共享图和逐流顺序的诊断中无残余业务差异；原始目录排列/全局流交错仍保留，不是新的完整 Web 验收。

## Win7 运行库缺口

旧实际 Portable 的 65 个 PE 原生模块审计发现未打包 UCRT，存在 14 个 `api-ms-win-crt-*` 依赖。采用 Microsoft Windows SDK 10.0.14393.795 的 41 个原始 x64 UCRT DLL，共 1854160 字节。引导文件及 DLL 的 Microsoft Authenticode、Burn manifest、MSI 只读表、CAB 大小/SHA-1/SHA-256、许可和官方 REDIST 逐项留存；未执行 SDK 安装器、未修改系统。

固定输入位于 `vendor/ucrt/`。manifest SHA-256 `632086f43adc87c504808fe3d94b6adf8e743388749426ba25b257a6c0f67380` 由校验器固定。构建前检查完整输入，41 DLL 放在主 Python EXE 同目录，连同 manifest/SDK 许可/REDIST；实际解压阶段重复检查字节及 provenance。遗漏、修改、错误位置、共享和 reparse 路径控制均拒绝。微软的[UCRT 部署说明](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment?view=msvc-170)要求旧系统的 app-local DLL 与主 EXE 同目录；[SDK 档案](https://learn.microsoft.com/en-us/windows/apps/windows-sdk/downloads-archive)与[官方 REDIST](https://learn.microsoft.com/en-us/legal/windows-sdk/redist)提供来源与许可记录。

API-set 转发 DLL 的 PE subsystemVersion 为 10.0，ucrtbase 为 5.2，原始值保留；不修改 PE 头，不拿静态审计或现代系统优先使用系统 UCRT 的行为代替原生 Win7 测试。用户延期的 Win7 真机认证仍未完成。

## 定向验证与真实默认配置研究

已物理退出 0 的定向集合：103 项覆盖 creative/profile boot、Provider DTO、工作区保留；49 项覆盖 Agent/LLM/Web 直接消费者；99 项覆盖 UCRT、打包前检、vendor 身份、ripgrep 兼容和完整正例回执；新增 101 项覆盖过程清理及 UCRT 私有副本保留规则。计数不累计成完整回归。四场景 token 控制 26 项，目录/逐流提案损坏控制 16 项，creative 精确语言映射损坏控制 10 项另通过。

补充 28 项工作区/保留控制通过：身份 guard 失败也保存诊断，并让先发生的 pytest 失败保持主结果。不存在主失败时，保留失败仍拒绝门禁。

Source 实际自动默认 profile 是 acp/web/headless/sdk/sdk-minimal，**没有 minimal/standard/creative 同名默认值**。先导 Source `standard` 启动失败保留；不能把自建三种 manifest 当作原版默认配置。实际 minimal 对应 Source sdk-minimal；SDK 正常/取消/错误分别 30/14/18 完整帧，既有完整持久、时钟、分配身份及实际导入判据匹配。Source 取消夹具的真实 WinError10054 仅沿用已有精确关闭谓词。

实际 Native standard/headless 与自动 Source headless 的公开事件、完整两次真实 HTTP 工具调用/下一模型请求及原始工具数组顺序匹配。creative 的 Source 对应 headless 加两个真实 Cordis 扩展，剩余九处既有 Python Host 语言映射在 request/header 和两次 HTTP 请求逐项解释，10 项破坏控制确认不允许模型、工具顺序、Schema、额外/null 字段、事件序号或响应损坏。上述仍是研究，缺少新同 ZIP/干净候选的父组合验收。

历史精确 3dca2a32 包另取得七路由、三 engine、七 policy、四批准 token 场景、四真实 Worker ownership、三物理格式双向独立进程冷恢复及三 ACP 边界场景的有限资格。各自守卫/物理退出和原始观察留存；不能借用被拒绝的第九轮作为完整签收。

研究归档 `PROVIDER-UCRT-COMPOSITION-RESEARCH-20261010-3DCA2A32.zip`：290 成员、29912624 字节，SHA-256 `0c7e9c9ea25e048186d030d508547b89fd6fc925baa23f5fee99a703fda4ae2f`。内容是有界真实观察、比较器、损坏控制、SDK 来源和本批被测字节，未归档每个调试工作区。

## 及时清理及下一稳定节点

第九轮 995 份实际清理审计合计删除 5448 个可重建文件、13891871346 字节；重复暂存归档另删约 81.6 MB。两个新且已物理关闭浏览器 profile 清理约 33.3 MB；99 项已结束夹具的 647 个私有 UCRT 原件相同副本清理 24528635 字节。历史独立 own 副本也已在退出及原件核验后清理。失败、正式证据、未知/修改/共享文件和原历史备份保留。

同一已退出 99 项集合的 18 个前检夹具另清理 792 个原件相同 UCRT 文件、38491902 字节，先核验完整成功 XML/所属目录，再由现有清理函数复核两端散列及私有普通文件身份，独立审计保留。

现有按测试清理机制新增 UCRT 原件相同私有副本，清理前复验保留原件和冻结输入；不会遍历删除整个 `.goose/out`。新的完整门禁安排在本批稳定提交后：一次 `verify_release.py` 包含完整 Python、22 Source、83 配对、同 ZIP 实际运行及固定 108/现代浏览器，不预先重复全套 pytest。16 项台账尚不提升，七个父任务需额外组合证据，九个子任务需新完整回执。
