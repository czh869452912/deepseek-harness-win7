# 0.2.2-rc.3 实施准备区

日期：2026-11-14。用户已认可[目标复核](../../../docs/research/2026-11-14-upstream-target-selection-update.md)，授权评估实施路径并准备实施。

- 固定目标：`dsh-v0.2.2-rc.3 / 38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。
- 当前上游生产 pin：`a4c74a91e06b00fe0b0937bde982170c526cc842`。代码基于当前工作区，包含已完成的创造模式适配。
- 本目录名称 `rc022` 明确区别于历史 `rc3`（0.1.5-rc.3）；不是新的活动基线或发行资格。
- 详细执行顺序、合同和准入标准见[实施路径](../../../docs/research/2026-11-14-rc022-implementation-path.md)。
- [准备检查](preparation-checks.json)记录实际执行的发现、回归、源码与工具准备结果；完整生成清单和日志留在自有忽略输出目录。

下一工作单元是 S0-B：使用独立 Source 与固定现代工具链完成依赖安装和原样前端构建，随后执行 Chromium108/Electron22 探针。S0-C 的 v3→v4 与插件协议探针尚未执行。所有迁移合同保持未签收。

2026-11-15：已按用户授权开始分批实施并提交。C2-A 的显式[值转换助手检查](value-helpers-checks.json)完成 Source/native 配对；仅覆盖工具结果角色、消息来源和扩展内容，不代表完整 v4 格式、持久化或消费者闭合。Source 安装通过，artifacts 构建正在独立候选环境推进。

生产 reference、注册表、运行时/前端输入清单和旧迁移任务本轮不切换。待合同实现与消费者定向检查闭合后，统一执行显式 promotion；`accepted_upstream` 不随准备记录自动变化。

2026-11-15：C2-B [准入校验助手](admission-guards-checks.json)完成 620 组固定 Source/native 对照、80 项原版测试及 43 项 Python 定向测试；覆盖 system/developer 字段、来源与退役语法的拒绝边界，仍未接入目录或生产持久化。S0-B 原版 artifacts 8 个构建阶段已通过，浏览器探针发现旧浏览器新增 API 需求，继续核实兼容适配。

2026-11-15：S0-B [构建与浏览器边界记录](source-build-browser-checks.json)完成：固定原版构建 8/8 通过。Host 的 `toSorted` 兼容补齐后，Chromium108/Electron22 模型菜单与插件页导航可操作；截图同时确认 CSS Anchor Positioning 缺失导致菜单定位错误，插件清单加载完成状态也尚未验证。二者仍是后续准入工作，不标记视觉、插件或 Web 合同签收。

2026-11-15：C2-C [子会话事实与引用检查](child-facts-checks.json)完成 1025 组 Source/native 对照、54 项相关原版测试、59 项 Python 定向测试；历史自有 descriptor 选择、fork not-started 身份、未知可忽略事件归属和移动后的本地引用已按独立助手落地，完整流式迁移与生命周期关系仍待实现。

2026-11-15：C2-D [显式格式库检查](format-library-checks.json)完成 1321 组固定 Source/native 对照、404 项原版格式包测试和 778 项 Python 定向回归；新增流式 v3→v4、V4 编解码、生命周期/压缩/工具/重试/标题/命令/目录/交付关系校验。测试合成工作区清理完毕；这些 API 已作为独立版本模块导出，生产 format catalog、CurrentSession、持久化与消费者尚未切换，C2 不据此整体验收。

2026-11-15：C2-E [历史目录检查](historical-catalog-checks.json)完成 1426 组固定 Source/native 对照、155 项原版提供端测试和 785 项 Python 定向回归。独立 V0–V3 历史读取用于收集迁移前置事实，修正旧物理头与损坏头结果的字段输出顺序；生产目录仍为 V3。已删除本批用完的合成夹具，保留初次失败诊断与所有运行记录。

2026-11-15：C3-A [历史前置事实读取](catalog-prerequisite-checks.json)完成 240 组明文/zstd 实际文件对照、124 项原版提供端测试与 899 项 Python 定向回归。新增只读解码、子会话局部失败隔离及物理身份复核；补齐固定原版对历史 descriptor v1/v2 的读取规则。本批原始诊断和矩阵保留，已用完的实际文件夹具及时删除。此阶段仅证明 V0–V3 前置事实读取，V4 子会话读取、父目录补全、Session 与生产发布整合仍待闭合。

2026-11-15：C1-A [事件分发检查](event-dispatch-checks.json)完成固定原版/Python 的独立观察对照、12 项原版生命周期测试，以及两组 95/116 项 Python 定向回归。新增 Symbol 身份事件键、每个 middleware 独立的单次 next、parallel 调度标识、空监听键清除与 internal/update 注册 effect；配置解析/更新参数和 Fiber 依赖生命周期属于后续同合同整合工作，未据此宣称 C1 完成。

2026-11-15：C1-B [配置生命周期](config-lifecycle-checks.json)完成固定 Source/Python 配对及 58/98 项定向检查；原始输入与生效配置分离，提交先于更新，候选解析不发布，过期完成不覆盖新值。C1-C [服务保留](provision-retention-checks.json)完成 5 组 Source/Python 旅程、12 项原版与 168 项 Python 检查；每次 provision 独立身份，隔离服务不混入依赖快照，提供者等待消费者清理后释放。

2026-11-15：C1-D [定义与使用上下文](trace-context-checks.json)完成原版/Python 配对和 103/15 项定向检查，覆盖方法、getter、调用入口、继承、权限与日志归属。三批已用完的合成夹具均在提交前清理，失败诊断保留。独立 Source、node_modules 与工具链继续由 rc022-C1–C9 持有，用于其余固定上游合同和最终验收；完成 C9 或目标被否决后清理。C1 整体及其余合同仍未签收。

2026-11-15：C1-E [volatile 基础](volatile-foundation-checks.json)完成 1153 组固定 Source/Python 对照、28 项原版和 253 项 Python 定向检查。实现不可变快照引用、Schema 固定路径约束及默认/缺省值、严格数组/循环/不透明值比较、按原始配置元数据忽略 volatile 字段。保留原版对未完整水合 schema 节点的拒绝边界，未用更宽松的宿主替代。Python 冻结 JSON 以 dict/list 子类表达；JS URL 对象行为不属于本轮 Python 数据语料。Loader 的引用提交、日志式配置落盘及装配仍待后续整合，C1 尚未整体验收。

2026-11-15：C1-F [Loader volatile 提交](loader-volatile-checks.json)完成 4 组固定原版/Python 实际入口旅程、26 项原版与 93 项 Python 定向检查。纯 volatile 更新保留引用及插件实例，所有引用提交后只通知所属插件；无效候选保留原始输入，混合生效值变化进入普通更新，依赖未就绪和强制更新另行覆盖。本轮确认生产使用 `loader.py` 中的类，拆分的 `loader_entry/tree/group.py` 尚未被装配；此前对拆分文件的修改不作为生产 Loader 证据。已删除本批通过测试的 4188 字节合成夹具，首轮失败报告和全部运行记录保留。journal、完整上下文生命周期和 boot 仍待实现。

2026-11-15：C1-G [Include journal 基础](include-journal-foundation-checks.json)完成 1634 组固定原版/Python 对照、11 项原版及 64 项 Python 检查。新增逐 entry 增量、创建/删除折叠、外部文件优先的三方协调，以及 patch 字段与插入条目的归属路由；当前仍是独立助手，尚未替代生产 Include 队列。直接消费者旧断言按固定原版更新为 raw/effective 分离、新更新参数和失败激活的显式恢复。已删除用完的合成夹具，保留失败报告和运行记录。

2026-11-15：C1-H [Include 原子写入](include-atomic-checks.json)完成 32 组原版/Python 实际文件对照及 32 项 Python 检查。生产写入器采用独立临时文件，每次重命名重试前核对预期原文；拒绝覆盖外部修改或消失的文件，失败清除临时文件，成功后才发布内容缓存。保留 UTF-8 与 CRLF 原文，并覆盖暂时锁冲突和不可恢复写入失败。已清理本批实际文件和合成工作区。journal 队列和 Loader commit 接入仍未完成，未据此宣称完整持久化验收。

2026-11-15：C1-I [Include journal 队列](include-queue-checks.json)已接入生产：7 组原版/Python 实际文件旅程通过，直接消费者 98 项、Fiber/profile/Web 启动 83 项、写入故障补充 3 项分别通过。覆盖双向并发编辑、文件冲突优先、缺失/损坏恢复、patch 归属落盘、失败刷新后的最新配置和重复 ID 的原版规则。更新同步前缀及 commit 提前到生命周期等待之前；Group 逐行记录失败，保留目标列表。旧 C38 回滚观察原文保留，当前用候选失败刷新旅程验证；旧 patch watcher 暂由自身承担激活失败恢复，不作为新版 profile 重组证据。已清理 50 个自有目录共 34432 字节，移除 478 个测试链接且未跟随目标。跨树所有权/位置、完整生命周期时序和 boot 重组仍待后续闭合。

2026-11-15：C1-J [Loader 跨树所有权](loader-moves-checks.json)完成 7 组固定原版/Python 双文件旅程、101 项 Python 消费者及 48 项原版检查（1 项既有 Windows 权限跳过）。跨树移动递归迁移同树成员及 Group 归属，预检全部目标 ID 冲突，保留条目/Fiber 身份；显式根组、负数位置、禁用条目和迁移后删除亦覆盖。创建先登记位置与 commit，Group 不再重复插入配置。原版同父组重排不单独持久化，未扩展该合同。已删除 54 个自有临时目录/文件共 32652 字节，保留失败观察和运行记录。完整生命周期时序及 boot 重组继续推进。

2026-11-15：C1-K [Entry 原始发布与激活](loader-lifecycle-checks.json)完成 8 组固定原版/Python 旅程，直接消费者 102 项及 Fiber/profile/Web/HMR 消费者 115 项分别通过。Entry 在比较前发布原始配置，无变化时仅保留 Fiber 输入；name 修改不替换已加载模块，禁用保留已释放句柄，再启用才重新导入。导入错误记录日志，激活错误留在 Fiber；Loader 等待只收敛任务。初次激活通知 Loader，而已收敛后的直接 Fiber 更新不自动通知，这一原版边界明确保留。旧替换回滚与空 diff 丢弃调用方对象的断言已更正。合成工作区和测试链接已清理，原始失败与运行记录保留；同步删除/创建时序和完整 boot 重组继续推进。

2026-11-15：C1-L [Loader 同步时序](loader-timing-checks.json)完成 4 组新增固定原版/Python 旅程，并复验生命周期 8 组、volatile 4 组、跨树 7 组与持久化 7 组；直接消费者 103 项、Fiber/profile/Web/HMR 115 项分别通过。Group/Tree 删除同步注销、报告增量并启动 Fiber 清理，保留句柄；Loader 仅查询在树条目的导入与 Fiber inertia，父所有者等待被移除资源释放。Group 创建、更新和导入调用的同步前缀亦已对齐，实际导入结果保留 Promise 等待边界；删除前注销与父级卸载不误记为自禁用。volatile 观察器显式等待两个插件均激活后再检查局部通知。合成工作区、双文件夹具和测试链接已清理，失败观察及运行记录保留。服务关联属性、严格 waterfall 消费者与新版 boot 重组仍待闭合。

2026-11-15：C1-M [严格 waterfall 与消费者](waterfall-checks.json)落实末尾零参数 continuation、原始监听参数与单次 next，并修正 prompt、请求错误和遥测生产调用。原版瀑布、5 组时序、7 组移动与 8 组持久化旅程通过对照，12 项原版生命周期检查通过。业务发现集最初 939 通过、24 失败、1 跳过；修复后原失败及新增用例 26 项通过，组合集 290 通过、1 失败，最后一个 Include 同步读文件导致 journal 提前截取的问题修复后，相关 62 项通过。并发导入共享 Future 的调度和动态 Python 模块最后所有者释放均补充覆盖。各运行独立保留，不合并宣称完整回归。已删除本批用完的合成工作区、实际文件和测试链接，失败诊断、观察与日志保留；服务关联属性和新版 boot 重组继续推进。

2026-11-15：C1-N [服务关联属性](associated-properties-checks.json)完成 Service 与通用 tracker 的关联读写原版对照，并复验定义/使用上下文旅程；125 项提供端与直接消费者、115 项 Fiber/profile/Web/HMR 回归分别通过。`ctx.api.sub` 按 `api.sub` 的声明与定义方注入权限解析，accessor 保留原接收者，扩展卸载后恢复原字段；影子上下文同时继承普通元数据。Python 完整 hook 显式接收 context 与 receiver，既有简短 hook 兼容保留。合成夹具和测试链接已清理，初次失败诊断与运行记录保留。日志等级、剩余核心生命周期及新版 boot 重组继续推进。

2026-11-15：C1-O [日志生命周期](logger-checks.json)完成固定原版/Python 对照及 51 项定向检查。日志等级改为 ERROR/WARN/INFO/DEBUG 对应 0/1/2/3，按 nullish 顺序选择 exporter 阈值；注销释放自身注册，各 exporter 获得独立消息对象并保留共享参数，元数据覆盖、空 AggregateError、原位裁剪共享缓冲区和显式空名称亦已覆盖。启动缓冲 exporter 在根卸载后保留，按原版观察记录。已清理合成工作区与测试链接，首次断言修正的原始诊断保留。剩余核心生命周期和新版 boot/profile 重组继续推进。

2026-11-15：C1-P [启动判定与诊断](startup-checks.json)完成 8 组实际 boot 原版/Python 对照、103 项原版启动检查；Python 启动/持久化 84 项、Fiber/profile/Web/HMR 118 项分别通过，测试工作区修正后另有 55 项通过。仅固定必需入口及根 Include 的失败拒绝启动，可选失败警告并保留正常兄弟节点；StartupError 保存原始原因，卸载前采集限额配置无关快照，外部日志收集器保留卸载期间的告警。循环 cause 不再无限遍历，Include 使用目录 file URL，7 组跨树旅程复验通过。已删除本轮 98 个精确识别的系统临时夹具及指定工作区资产，旧测试已改为在指定工作区内生成；原始失败、命令与观察保留。profile 重组、解析与兼容预检等 C1 工作继续推进。

2026-11-15：C1-Q [分层环境路由](environment-checks.json)完成 48 组真实 `.env` 原版/Python 对照和环境/凭据/配置链/启动定向回归。用户目录允许精确拼写的两个 DeepSeek 端点及不区分大小写的代理名称，项目目录仍拒绝；错误端点拼写给出修正指引，两个文件校验完毕才发布值，继承值优先。已删除本批合成工作区和环境文件，保留观察与首轮回执生成失败诊断。兼容预检、解析和 profile 重组继续推进。

2026-11-15：C1-R [插件版本要求与独立授权](plugin-compatibility-checks.json)完成 5867 组固定原版/Python 对照、114 项原版提供端及 159 项 Python 定向检查。纯 Python 实现 npm 严格版本范围与预发布规则，保留 engines 优先、dsh peers/workspace 规则和精确版本豁免；独立 compatibility.json 采用锁与原子替换，损坏记录不授权、不阻断读取，拒绝改写含有未接受记录的文件。授权、撤销、并发写与发布失败保留均已覆盖。配对明确使用候选运行时版本，安装版本默认值尚不切换。已清理本批合成夹具和中间输入，保留严格前缀差异及错误测试路径的原始诊断；装配预检和 profile 重组继续推进。

2026-11-15：C1-S [装配兼容预检](preflight-checks.json)接入 root Include 和 launcher profileContext，34 组固定原版/Python 实际预检/启动旅程通过。拒绝导入不兼容插件，按 Group 后代递归检查，对包含拒绝项的原生 Include 整体禁用且文件不改写；已覆盖豁免、元数据损坏、包服务归属和缺失模块交回 Loader。组合回归 135 项通过、1 项新增测试 Logger 用法错误，修正后 4 项预检通过。原版 27 项通过，循环文件链接夹具因本机 Windows EPERM 不能执行，保留失败原文并单独排除此项复验，不宣称全量通过。每插件导入先于 apply；跨插件顺序原始观察保留，不作为预检合同固定。合成夹具已清理；完整运行时解析、profile 层与重组及 preset 消费者仍待闭合。

2026-11-15：C1-T [Profile 有序层与跳过诊断](profile-layers-checks.json)完成 53 组固定原版/Python 实际文件和 Host 平台对照、36 项原版所选检查。Python profile/初始化/Web/HMR/预检 126 项通过、1 项新增测试错误地要求多行解析诊断只能一行，修正断言后 9 项通过。Bundle patch 字符串及列表均按顺序读取，每个文件的相对模块路径独立锚定；整层失败、平台不符或版本不符记入 skippedBundles，用户 patch 错误仍抛出。仅移除两个固定退役 bundle，保留其它 manifest 字段；launcher 明确报告跳过项并传播根配置写入失败。测试 helper 已收进指定工作区，合成夹具和链接已清理。旧 Python patchReload 字段留到整体重组迁移，不作为新版合同证据。

2026-11-15：C1-U [Profile patch 协调](reconciliation-checks.json)完成 11 组固定原版/Python 实际 boot/reconcile 旅程及 94 项启动/Loader/Include/HMR/预检检查。协调完整 patch 栈，按 entry/Fiber/原始配置身份保留未变化的旧失败警告，拒绝新增/变化失败或显式必需的不活动条目；pending 仅警告且 provider 到达后激活。移除条目虽已离开 Loader，仍等待原 Fiber 清理；成功才发出零参数 config-reload。原版所选协调收敛测试通过，日志/观察保留，合成夹具已清理。完整 recomposeProfile 的代际发布与 launcher watcher 接入仍待后续 C1 工作。

2026-11-15：C1-V [运行时包表构建](runtime-resolution-checks.json)完成 10 组固定原版/Python 实际依赖图/后继表对照和 8 项原版所选构建检查。安装与 profile 依赖采用 BFS 首次解析优先，包含 peers/optional，记录 declarer/version/scope、直接安装名称和外部链接；表不可变，读取不写 fallback，重算重新读取磁盘而不保留合成层。Python 112 项通过、2 项夹具/异常断言错误修正后，17 项补充通过。首次悬空 junction 创建失败的诊断保留，改为先创建自有目标、建立 junction 后移除目标；本批全部合成工作区和链接已清理。运行时路由/发布、完整重组及旧 fallback launcher 替换仍待后续 C1 工作。

2026-11-15：C1-W [包元数据路由与发布](package-routing-checks.json)完成 46 组固定原版/Python 路由、缓存与代际发布对照及 7 项原版检查。新增 Context 所有的 PluginPackages，按活动/其它 profile、安装目录、本地目录和链接 peer 确认包归属；拒绝需要重启的后继表且保留旧缓存，允许新增和安全删除。重算失败原子性、链接历史移动链与拒绝发布不改历史补充覆盖。Python 56 项通过、1 项误将跳过 bundle 当作致命错误的断言修正后，6 项通过。清理 5 个自有资产共 134257 字节及 39 个链接，观察和诊断保留。Python Loader、worker、localized metaOf 和整体重组尚未接入，未将元数据合同冒充 Node 全局模块 hook 对齐。

2026-11-15：C1-X [完整 Profile 重组](recomposition-checks.json)完成 10 组固定原版/Python 实际 boot/包表旅程及原协调 11 组复验，14 项原版与 57 项 Python 定向检查通过。重算先于停止，移除项在旧映射下释放，之后才发布后继表；发布拒绝恢复原位置，已应用的新组合失败则保留并报错。重试调用方失效的 runtime 和导入失败条目，保留 required/running 判定与异步清理边界。配对发现并移除 Loader 提前构造的占位 Group，避免覆盖 Include 根组所有权。自有 20 个资产共 51313 字节已清理，首次组内停止顺序差异及观察器自禁用/失败等待修正的原始诊断保留。Launcher、实时层读取、模块路由和 HMR 仍待接入。

2026-11-15：C1-Y [实时组合输入](profile-context-checks.json)完成 44 组固定原版/Python 文件与启动快照对照及 1 项原版检查。Bundle 读取不消费默认用户层，完整读取支持自定义用户路径、显式 home、分离的启动 overlay 和最后应用的隐私开关；当前 bundle 选择/内容变化都会重新读取。Launcher live reader 修复启动 bundle 缓存与环境 home 漂移，ComposedProfile 不再把隐私补丁混入原始 overlay。Python 32 项通过、1 项新增断言错误修正后，4 项通过。已清理 7 个自有资产共 177119 字节及 478 个测试链接，观察器修改自身结果和断言修正的诊断保留。真实 HMR、模块/服务接线和旧 patchReload 退役继续推进。

2026-11-15：C1-Z [canonical Python 模块路由](runtime-loader-checks.json)完成 33 组原版真实 ESM/Python 根模块导入及元数据归属对照，并复验包表构建 10 组。Launcher 挂载配置树前发布包服务，不再 heal 或安装物理 fallback 根；Loader 按选中目录导入 Python，仅安装映射使用原生类表，未选中名称不再透过旧表逃逸，外部 JS 不执行测试占位函数。Portable 平铺目录通过显式只读安装图适配，重算重新枚举，真实安装副本优先，普通包表 API 不引入 workspace fallback。Python 86 项通过、1 项旧可选 gateway 致命断言改为新版必需 connection 合同后，10 项通过。已清理 6 个自有资产共 144114 字节及 12 个链接；历史直接 boot 辅助仍保留。完整 exports/imports、自引用、元数据、worker 和 HMR 尚待后续闭合。

2026-11-15：C1-AA [包资源解析](resource-resolution-checks.json)完成 232 组固定原版/Python 实际文件对照和 19 项 Python 定向检查。使用原样构建产物与原生 Node，避免 tsx 扩展名补全改变观察；覆盖 exports/imports、条件与通配符、自引用、数组边界、编码分隔符及目录/缺失文件拒绝，不执行入口。已清理本批全部合成夹具，保留载体差异和修正前原始诊断。Loader/预检消费者、本地化元数据、链接移动、worker 和 HMR 继续推进。

2026-11-15：C1-AB [资源解析消费者](resource-consumers-checks.json)接入 canonical Loader 与兼容预检，22 组原版实际 ESM/Python 导入及准入对照、27 项基础消费者和 99 项分发/CLI/Web 定向检查通过。外部包按完整导出规则选择真实文件，支持自引用、条件及通配符别名；安装类映射先检查导出准入，显式 Python descriptor 与文件导出语法保留。已清理本批合成工作区及链接，保留日志/XML和原始观察。元数据、缓存/移动、worker 和真实 HMR 继续推进。

2026-11-15：C1-AC [插件本地化元数据](package-meta-checks.json)提供 PluginPackages.metaOf 与公开只读 API，95 组固定原版实际资源对照和 26 项 Python 检查通过。逐语言/字段回退、完整子路径、严格字段、图标优先级/归属/256KiB 限制及读取后增长覆盖；图标比较真实字节摘要，错误仅对照是否存在并保留原始措辞。原版 102 项通过、2 项文件 symlink 夹具因 Windows EPERM 创建失败、1 项大小写文件共存检查跳过，未宣称完整 Source 通过。合成目录和链接已清理；实际目录 junction 归属与注入重复清单已覆盖，UI 消费者留到 C8。

2026-11-15：C1-AD [Profile 原子替换](profile-replace-checks.json)完成 22 组固定原版/Python 实际目录快照及故障对照、20 项原版和 121 项 Python 检查。自定义目标以同目录 staging 原子替换，仅复制 bundle 元数据；移动失败恢复旧目录，恢复失败保留备份和双原因，并发新目标优先，成功后清理失败给出诊断。大小写 shipped 名拒绝、活动 Python 租约保护、依赖 junction 目标保护、dump/启动及分发消费者覆盖。旧独占创建观察原文保留，当前断言采用新合同；本批合成备份/工作区已清理。公共旧 patchReload 参数与 launcher watcher 等待真实 HMR 接线后整体退役。

2026-11-15：C1-AE [HMR 模块文件身份](hmr-files-checks.json)完成 15 组固定原版/Python 实际文件观察、2 项原版与 8 项 Python 检查。比较 inode/size/mtime，保留 seen/retained 记录及 FAT 两秒边界，hardlink 造成的 ctime 不触发重载；时钟标记成功与 stat 失败均清理。此助手尚未接入生产 HMR，队列、缓存替换和 profile 监听继续推进。本批合成文件、工作区已清理。

2026-11-15：C1-AF [HMR 串行事务与精确监听](hmr-queue-checks.json)完成 7 组固定原版/Python 实际服务旅程、32 项原版与 33 项 Python 定向检查。失败后队列可继续使用，拒绝嵌套；watchConfig 的初始回调在事务后运行，路径重复和启动失败释放、事务内卸载及外部卸载等待均覆盖，Python 取消调用方等待不取消服务事务。本批全部合成夹具和临时目录已清理。应用就绪、整个文件批次派发、profile 监听、模块替换和旧 patchReload 退役继续推进。

2026-11-15：C1-AG [HMR 应用就绪与模块基线](hmr-ready-checks.json)完成 5 组固定原版/Python 实际服务对照、9 项原版与 37 项 Python 定向检查。Profile HMR 缺少 appReady 即拒绝，重载回调等待成功启动，调用方事务可先运行；启动中断释放屏障且不执行回调。ModuleFiles 接入启动记录，覆盖普通包、scoped junction 包及根外 sibling；观察失败警告后继续启动。本批合成文件、工作区及链接已清理。自动 profile 监听、整个批次派发、模块替换和旧 patchReload 退役仍待完成。

2026-11-15：C1-AH [HMR 只读替换规划](hmr-plan-checks.json)完成 360 组固定原版/Python 受控图与真实 manifest 祖先对照，4 项原版所选真实消费者及 5 项 Python 检查通过。保持发现顺序与实例身份，宿主依赖及无受影响 Loader 祖先的实例留待重启；依赖环、重叠变更、子插件和过期 entry wrapper 覆盖。首个 Python 断言顺序错误修正，配对值未变化；原始诊断保留，全部合成工作区已清理。此助手尚未接入生产模块图/缓存，停止执行与 profile 重组继续推进。

2026-11-15：C1-AI [HMR Python 模块缓存](hmr-cache-checks.json)完成 3 组原版真实 ESM/Python 文件导入与缓存恢复对照，2 项原版缓存消费者和 71 项 Python 定向检查通过。新增可撤销的模块/别名/父包属性缓存驱逐，源码编译避开同大小同时间戳旧 pyc，失败不发布半成品；Finder 由 Context effect 持有并随 HMR 释放。显式 Python 文件导入保留活模块身份，沿用最后所有者释放约定。本批全部合成目录和链接已清理，初次观察器缺少原型方法的诊断保留；生产 profile 替换尚未调用此驱逐器，模块图与重组继续推进。

2026-11-15：C1-AJ [已求值的 Python 导入图](hmr-graph-checks.json)完成 2 组实际 ESM/CJS/Python 模块图旅程、4 项原版所选消费者与 58/11 项 Python 检查。文件及 descriptor Host 导入记录实际成功的 import，保留函数运行时 import 与显式 importlib 动态加载的差别；已求值链接不随源码改写变化。旧未跟踪模块采用一次性语法/绑定快照，不宣称重建任意旧导入历史；弱快照不保留已卸载模块。Descriptor 缓存键修正为真实 Host 文件。全部合成目录及链接已清理，生产 plan/stop/profile 重组继续推进。
