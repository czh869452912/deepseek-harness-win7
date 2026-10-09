# 工具、计划浏览器与原生搜索接续

固定 Source 为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。16 项任务仍开放；本文记录定向修复与完整候选拒绝，不提升父合同、全项目或 Win7 认证状态。

## 4a878f46 完整候选拒绝

干净 `4a878f463621c19f35387c81cc61f5d15429a610` 的统一门禁正常结束完整 Python：10341 passed、6 既有 skipped，3951.58 秒。22 组官方 Source 配置全部通过，包括83项原版计划测试。配对阶段 `cordis_runner_python.py` 在设置显式项目 root 前导入 SystemPrompt，独立进程因此报 `ModuleNotFoundError: dsh`。后续配对、实际解压和浏览器阶段没有全部执行；不能将 Python/Source 通过改称发行通过。

物理退出后、产品编辑前16573冻结输入、干净 HEAD 与精确 ZIP 均未变。输入清单 SHA-256为 `e53510ee3f2695856b018f1785ef0f5a15799be547164632c2d24afe3be1771b`；精确 ZIP 为 `ba4aa400183626a3846af1aa328833f11a7c736fecc41e8ff8159d603bab3e55`。1156成员拒绝归档 `CURRENT-RELEASE-REJECTION-20261009-4A878F46.zip` 为82781993字节，SHA-256 `2ea19f4fa380498f2cc2a956b948b8ef64121f3a2f087dbdd8ed0045b490ad5f`，保留完整XML、全部已执行Source/配对日志、原栈、输入、身份、原包及989份清理审计。

## 实际工具错误与独立观测修复

独立启动审查确认 retirement 也存在相同导入顺序错误。两个观察器都先绑定 root 再导入产品。新增回归用 `python -I -B`、外部工作目录和无 PYTHONPATH 执行真正独立进程；修复前2项失败，修复后及相关 runner/retirement 40项通过。

实际 Source/Root 观察发现 Tools 丢失任意抛出值及原始取消原因，错误地将只有 `code` 的普通对象当 HarnessError。现在解开 ThrownValueError、保留 Error.message 的原始类型、使用已有完整 JavaScript 字符串转换，并对敌对 getter/转换保留不可打印兜底。只有真实 HarnessError 子类发布 `info`。Source 的 FsError、GoalError、SubagentError、LlmError 都继承 HarnessError；相应 Python 类型已对齐，同时保留原生 ValueError/RuntimeError 捕获关系及需要保留的诊断字符串。AttachmentError 属于普通 Error，未伪装为 HarnessError。

28种实际抛出值与领域错误、每种3个顺序调用的完整结果、scheduler outcome 和 durable 事实匹配；只在核验唯一完整 UUIDv4 后对应结果消息分配。未删除字段或排序业务数组。真实 standard AgentLoop 的7种受控并发/补充/取消/typed body/post failure/待定审批取消/拒绝也取得 Source/Root 完整匹配。审批回答者显式 prepend 属于共同受控输入，用于限定真实策略服务路径；不称为完整 Web Remote/Loader 顺序资格，未推广观察器猴补丁。

新29项实际工具错误回归与直接消费者546项通过，SDK、AgentLoop、scheduler、abort等直接链路另112项通过。继承变更实际新增 LLM catalog 和 Win32 metadata 的 `dsh/llm/error.py` 导入；两份独立观察记录分别确认仅增加该文件，精确清单已补齐。203项消费者/浏览器控制通过后完整正例曾因第二处清单拒绝；随后37项 metadata 与完整回执正例通过。分别保留每次结果，不累加重叠计数。

## 原版计划审批和冷恢复

standard/cordis 实际浏览器旅程现在发送原版 `/plan` 命令，经实际 `exit_plan_mode` 工具触发原版计划面板，并由可信 CDP 点击原版 Approve 按钮。React/TSX/CSS/client bundle 无修改。门禁要求完整 active→call→result→inactive 链、精确计划参数/批准文本、顶层 `sourceEventSeqs` 关联、事件数组与序号顺序，以及严格布尔类型；cold 独立 Host 同样核验。

官方 Source、Root现代浏览器、Root固定Chromium108的原版 standard fresh/cold共6阶段均成功，Console错误为0且Host/浏览器物理退出。最终验证器重新消费原始报告全部通过。第一版验证器错误地从 event.data 读取 sourceEventSeqs，被实际报告揭示后修正，原拒绝保留；不是产品协议失败。

这是有限功能和持久化证据，不代表完整 wire 顺序、全部 profile 或同 ZIP own-runtime 资格。既有 Settings/catalog/mux 全图顺序差异仍开放。CSS动态适配尚为未推广研究；不得由本轮计划旅程推定 CSS/raster 或其他 realm 全面通过。

## 固定原生 ripgrep 输入

官方 [14.1.0发行](https://github.com/BurntSushi/ripgrep/releases/tag/14.1.0) 的 x64 MSVC ZIP为2020417字节，官方SHA-256 `fe4f75edfaa50f0d4fecbf47696b7629f3449c9c2c5a4da828753139e5a2e203`。侧边校验文件是三行 CertUtil 输出，按唯一完整64位散列行核验；首次误当 GNU 单行格式的拒绝保留。实际 `rg.exe` 为5332480字节，SHA-256 `1dce02aae98c0a48c2644abd1849fb90406296d4e0c95e239f95242ee8480ff8`。

静态PE普通导入仅为ADVAPI32/KERNEL32/bcrypt/ntdll/USERENV；子系统版本6.0，没有 delay import 或rg15的直接 WaitOnAddress/WakeByAddress/API-set/ProcessPrng载入依赖。二进制仍含动态同步API名称，静态普通导入分析不认证所有动态调用。官方[构建流程](https://github.com/BurntSushi/ripgrep/blob/14.1.0/.github/workflows/release.yml)使用当时 nightly、静态 PCRE2；下载产物未给出精确编译器修订，来源记录明确未知。发布日期和[后续Rust Windows基线调整](https://blog.rust-lang.org/2024/02/26/Windows-7/)不能替代目标OS运行证明。

源码和Portable默认使用 `dsh/fs/tool_fs_search/bin/rg.exe`，同目录固定来源清单、COPYING、LICENSE-MIT、UNLICENSE都按精确大小/散列核验。显式覆盖只能提供相同批准二进制；不接受宿主rg/其他版本代替打包输入。缺失、篡改、共享硬链接或别名在替换旧发行前拒绝，许可证/来源逐字进入实际ZIP布局。固定官方 Source pnpm 输入保持原样；新二进制是声明的Python Host兼容输入，未改上游 pin 或伪造npm身份。

34项初步搜索消费者通过/1既有skip；83项产品搜索/打包/预检消费者通过/1既有skip。重复验证揭示多文件grep顺序不稳定，同一固定官方rg15、同工作区20次实际执行出现两种完整match顺序；所有原始JSON保留。最终跨版本比较限定单文件grep与明确mtime的glob，完整公共结果逐项比较，没有排序业务结果；早先随机匹配不能证明一般多文件顺序一致。

最终45项通过，包括新进程空PATH中文搜索、九种受控完整工具值、真实114项批准导入的完整glob/grep/meta、20种运行回执拒绝、六种完整提取回执拒绝及完整有效正例。统一发行入口新增包内 `python.exe -I -B` 的空PATH真实搜索，检查默认二进制、实际version、完整工具结果与Root/own导入散列。最终ZIP的实际运行仍需新的冻结完整门禁，不能拿本轮Root进程替代。

Win7真机认证按既定决定延期。替换消除了已确认的rg15直接载入阻断；没有宣称Win7现场通过、所有native依赖闭合、PowerShell宿主初始化根因或零前置浏览器已解决。

## 有限修复归档与及时清理

168成员 `HANDOFF-TOOLS-PLAN-RG-FIX-20261009-V1.zip` 为38782485字节，SHA-256 `94ed0f43cc3baad3b18583fc439111d7e6bd0a8951f1743e4aefb901feb034ae`。逐成员大小/散列核验，保存确切提供端/观察器/消费者字节、原始Source/Root/浏览器观察、失败和最终XML、官方rg来源/PE及原始顺序反证。基线是4a加明确未提交修复字节；不是新的精确Portable或完整候选资格。正式档直接写入证据目录，未产生另一份大ZIP暂存副本。

V7的989份实际逐测试审计确认删除5442个可重建文件、13787627133字节；核验正式归档相同后另删除82781993字节暂存ZIP。两项分别记账。成功浏览器profile在Host/浏览器退出后由现有保留器校验清理；定向测试继续使用既有逐案例清理。失败、未知、活动材料、正式证据和受保护历史保持。后续只清理归属、结束及完整字节可核验的可重建副本，不批量删除 `.goose/out`。

最后四个定向工作区的26份既有逐案例审计另确认删除4125文件、1266554058字节；这是独立于V7与暂存ZIP的清理，汇总没有执行新删除。未分类的失败/调试副本仍保留，不将完整工作区整体归档到LFS。
