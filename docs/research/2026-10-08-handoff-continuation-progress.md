# 16项开放迁移与兼容修复接续

基线为主目录 `master` / `4a4074ef`，固定上游仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。本记录区分局部修复、父合同规范和统一签收；不能把它当作16项已经闭环的声明。

## 本批次实现

- 推广既有不可变研究归档的三处真实差异：子代理 provider/model 缺项诊断保留反引号；前台结果按真实 stopReason 选择标题，区分缺失诊断与空诊断；Windows 工作区公开路径保留原生反斜杠。36组新鲜 Source/native 前台结果完整匹配，未改 Source 或增加上游例外。
- 搜索解析增加固定 pnpm `@vscode/ripgrep-win32-x64@1.18.0` 安装布局，保留显式环境覆盖、sidecar、Portable 和已有直接安装路径的优先级。无宿主 PATH 的新 Python 进程实际执行 glob/grep；这不改变打包 rg 15.0.0 的 Win8 API 依赖。
- 新增 Cordis Host 兼容插件，在最终 index 的所有可执行脚本前注入缺失的 `Promise.withResolvers`、`AbortSignal.any`；保留现有原生实现及 `AbortSignal.timeout`。最终 raw tap/CSP 校验、卸载和独立 realm 语义控制拒绝晚注入或被阻止执行。原版218份前端产物没有修改。
- Windows PowerShell 重定向 stderr 单独采用 UTF-16 BOM/初始ASCII-NUL证据或 UTF-8 无损转义策略；未知CP936字节不猜GBK，保存原始spill。跨单字节块及截断尾部保留编码证据，真实子进程退出码17不变。generic subprocess和PTY未改码页；现场初始化失败4294901760的根因仍未证明。
- 准备独立 Chromium 108.0.5359.0 开发观察器，固定 snapshot1058931、下载SHA、协议revision及84份分发资源SHA。该观察器在当前 Windows 上运行，不是 Win7 实机认证，也不是产品内置浏览器。
- 发行入口/实际解压验证新增固定108输入、缺API前后探针、适配层及实际ZIP散列绑定；包内Python执行三预设fresh/cold原版浏览器旅程，保留模型/工具请求、问答、审批、取消、物理关闭及冷恢复。缺预设/阶段/结果、换解释器/模块/包、错版本和晚注入等拒绝，实际导入字节在临时解压删除后仍与同一ZIP核对。CI准备固定观察器并把整体job期限由45分钟改为180分钟；普通PR仍走完整入口，未实施CI分层。

## 迁移合同与剩余范围

九项056—064和JS036继续保持running。六个draft父任务ACP transport、DeepSeek wire、Session replay、Tools policy、Web connection、Profile journeys已补正式 `CON-*` 合同、实际源路径、依赖及组合验收条件，删除占位acceptance；仍保留原始开放发现，不自动进入verified/integrated。合同定义本身不代替组合观察。

此前三预设研究生产者已从研究归档推广为可审阅脚本。固定108的minimal/standard/cordis六阶段源码Host功能旅程通过；现代浏览器与108的动态插件生命周期各18步通过。最小预设实际工具顺序仍为 `pwsh, str_replace_editor`，Source为相反顺序；保留原始值和差异，不通过排序认证完整预设。一次提前发布FS服务的假设没有改善结果，已撤回。

以下未取得完整资格：父合同的完整wire/动态图ABI/跨进程与竞争组合、JS完整Node API/所有spawn与清理重入；预览页面/Worker/iframe实际启用realm及完整CSS/语法兼容矩阵；原Win7现场精确ZIP和原始字节；rg15的Win7替代输入及VC/UCRT/其他native依赖闭合；零前置产品浏览器。Host事件式AbortSignal适配无法实现浏览器不公开的原生abort algorithms，例如早先监听器的stopImmediatePropagation。不得把主页面旅程称为全部G1—G4或Win7通过；既有延期真机认证不恢复。

## 定向验证与拒绝

验证覆盖变更提供端和直接消费者，不仅按文件名选择：搜索实际子进程、工作区公开身份、前台子代理/模型选择、WebServer最终HTML与卸载、PowerShell实际stderr与generic subprocess、SDK规范启动/协议/导入字节、发行负例和保留规则。

- 消费者175项、首轮Web/适配17项、PowerShell及前台70项、保留/适配/编码109项分别通过，存在重叠，不相加。后续编码尾部和generic消费者26项通过；SDK及完整有效基线后的解压负例118项通过；最终浏览器兼容/三预设包绑定负例、编码及实际打包前检81项通过。Python3.8解析与diff检查通过，六个父合同migration check通过，status由生成器更新。
- 第一轮验收回归误用全局Node22.20，被Source观察器严格拒绝；修正为固定22.22.2后JS配对匹配。随后SDK完整公开结果匹配，但导入白名单缺少新插件两个实际文件，被严格拒绝。仅补录实际文件，逐字节及未知导入拒绝保持，118项复验通过。未把中断轮次的标记猜成最终通过数。
- Win32 ReplaceFileW1175在一次定向FS消费者出现，完整原始栈已保留；相同单项复验通过，不能据此宣称根因修复。已增加先失败的UTF16长诊断截断控制并修复，不修改既有Windows原子替换实现或期限。

完整签收仍需对稳定、干净冻结候选执行一次 `scripts/verify_release.py --browser <modern> --browser108 <fixed108> --output-dir <fresh>`。该入口包含完整Python、83配对、20组Source及实际同包解压，前面不再重复全量pytest。完整回执只能支持其精确候选/输入/ZIP和已满足的合同；不能补写旧回执或认证未观察的父范围。

## 空间与材料保留

定向pytest沿用短自有工作区、每项合成回执/原样前检副本清理和结束维护。浏览器研究成功后等待两阶段浏览器/Host物理退出再删除其专属profile；失败日志、真实观察、XML、未知/活动材料及原历史备份保留。

固定观察器下载ZIP经SHA核验、解压后删除200249373字节可重建压缩副本，84资源清单与提取后的观察器保留复用。开始接续的既有维护四分类均为空，不声称额外释放历史空间。详细原始日志/观察/清理审计在 `.goose/out/continuation-20261008-v1`；未将整轮调试树或每次局部修复打包为LFS证据。

## 2026-10-09 完整候选拒绝与新诊断

干净候选 `d2c6b3136f376b00cead571abe1d41de47b20916` 已通过 migration check 和打包，完整 Python 正常结束：10168 passed、6 skipped、43 setup errors，控制台3930.37秒、XML3930.026秒。43项全部来自一个FS配对夹具，Native编辑时 `ReplaceFileW` 返回1175，完整公共值有9处差异。后续20组Source、83配对和同ZIP解压/浏览器资格未执行，整体发行仍拒绝。16519份冻结输入前后完全一致，不补写成功回执或提升16项状态。

[拒绝归档](../../migration/evidence/artifacts/CURRENT-RELEASE-REJECTION-20261009-D2C6B313.zip) 共85成员，81486447字节，SHA-256 `080afe62c859cf63277424a89b650d0256a9e2160c9cb45e61acef2c21259d54`。含精确候选ZIP（SHA-256 `11abe14d2cb38b77b42e9993791513653e526d0e01f8cca937f00bff5a3dafbe`）、冻结输入/运行后身份、完整XML/日志、即时失败栈、原始Source/Native组观察和9处差异。完整失败工作区另保留，不把调试树整体作为发行证据。

独立诊断的仓库目录100次场景中Native11次失败，跟踪读取对象时12次失败，Source9次失败，均出现1175；跟踪到的Native读取对象均已关闭，Restart Manager未报告占用进程，不能指认杀毒软件或其他占用者。同一场景移到系统临时目录，Source/Native各100次无失败；加长系统临时路径后的Native100次也无失败。实际完整FS观察器在独立临时目录的509组完整公开值匹配，比较不变。这支持运行目录环境线索，不证明替换算法根因已修复；不能以成功诊断重标原完整候选为通过。

另一个独立控制发现真实的读取共享方式差异：200000字节文件的首个65536字节相同，Source在读取流仍打开时能原子替换，Native使用Python普通读取打开方式时返回Win32 32。现已推广Win32读/写/删除共享读取，七个FS二进制读取入口统一使用；打开的流继续读取原文件，目标读到新文件。实际回归先复现32，修复后通过；83项FS/元数据直接消费者通过、4项既有跳过。这不是1175根因修复声明，不改变ReplaceFileW算法或错误比较。

完整FS观察器的可重建物理夹具现在分配到仓库外的短系统临时目录，原始Source/Native公共观察和输入身份仍写入自有输出目录。未改变509组完整有序值、差异判据或操作期限。成功报告保留夹具所有权、逐文件SHA/尺寸/只读位和目录清单，最后一个消费者结束后才核验删除；观察改写、未完成/不匹配、异主、未知文件/空目录、字节变化或reparse均拒绝。pytest模块末尾、独立Portable成功末尾和统一发行晚检查之后接入，各自失败保留材料。独立Portable清理异常也使整轮failed。

首版隔离观察46项测试均通过，但附件不可变对象的只读属性导致清理teardown失败，原失败审计保留。仅清除已验证自有夹具的只读位后，46项复验通过；目录清单与8个破坏/拒绝控制补齐后的最终54项通过，509组真实Source/Native值匹配。该轮末尾清理65个文件/3737字节，完整观察保留。首版部分清理失败在确认剩余文件属于原所有权且SHA未变后独立续清2281字节，未覆盖原失败审计。加长临时路径的100次成功诊断保留完整报告后另清理101文件/470424字节。新产品需下一稳定候选的完整门禁，旧d2c6b313拒绝不提升。

随后补共享硬链接拒绝控制，55项最终FS消费者通过（27.90秒）；33项FS发行消费者/错lane/篡改控制通过（397.72秒）。其门禁缓存夹具在回执TemporaryDirectory退出前补清理，实际正例1项通过（299.55秒），不遗漏新的仓库外夹具。测试的长构造与重复完整正例均属既有成本，不改为弱化比较。

七种选定子代理路由的原始Source/Native观察器从已绑定研究归档原样推广到 `scripts/oracles/route_execution`，完整值比较只投影已声明的子代理/持久化消息UUID图及完整校验的安装位置段落。新增 `scripts/route_execution_oracle.py` 要求新干净候选、固定Node/Source、无改写的实际ZIP及包内Python3.8.10，核查完整实际导入、请求/事件/创建/销毁/取消和冻结输入前后SHA。比较正例与业务值/顺序/字段存在性/未知ID/安装位置破坏控制通过；新鲜Source/Root/同ZIP运行仍待下一干净候选，不能用历史提案替代。这七种选定路由也不单独关闭全部父组合。

最小预设注册顺序与模块缓存有关：单纯增加一个import-await检查点没有改善Native顺序；Source预载terminal、terminal-bash和tool-pwsh-persistent三个实际模块后，公开工具顺序变成与Native相同的 `pwsh, str_replace_editor`。冷装载的Source相反顺序和原始数组继续保留；不能通过排序认证预设。

固定原始Chromium108探针绑定协议版本、revision和既定二进制SHA，物理退出码0后删除专属profile。确认 `.at`、findLast/Index、DecompressionStream、structuredClone、`:has`和container-type可用；color-mix、scrollbar-width、light-dark、scrollend及toSorted缺失。静态产物有29处真实CSS color-mix，含嵌套混色和局部变量，JS适配不覆盖它。scrollend已有特性守卫/去抖回退，light-dark只是第三方库选项字符串，不能直接标为实际调用。审计矩阵已补这些区分；其他realm和完整视觉兼容仍开放。

完整轮逐项清理932份合成回执12631934648字节、18组前检中4117份字节核验可重建副本1157901597字节，合计5049文件/13789836245字节。两组已成功的独立临时诊断另在保留完整公开观察后清理202文件/778748字节；浏览器及rg研究已验证下载压缩副本合计201983730字节清理。真实失败、未知/活动文件、正式归档和 `lfs-original-history-20261007.git` 始终保留。后续集中完成相关定向修复和父组合，再安排下一次稳定候选门禁。
