# f90ded26 完整发行与十六项逐项审查

候选为 `f90ded26e96ecfb0c1737a47d9f47b034b26c93a`，Source 仍固定 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。本轮后续工作没有改变生产代码或原版前端。四实际策略场景的十一项 token 差异保持用户已批准的原边界；不扩展九项既有上游 bug 判据。

## 当前：十六项有限范围全部闭环

用户针对精确Web顺序v2答复“批准，继续签收”。批准记录为 `migration/evidence/HANDOFF-ORDER-APPROVAL-20261010-F90DED26.json`，SHA256 `f0768888f53a09d6ef603e20cd80e3d3748ad46e86aaa40978c3aff770d58a6d`；绑定原提案 SHA256 `9ad0e65bd9c89690e806dcbf776d206d7b7d3fe1800e20a374a52a6bf4a1454b`、原绑定清单 `73399f327175f469aeab4cb3123b37a256a1d67f415dda0bbf1c953b2fbf5711`。原提案文字仍作为批准前历史保存，审批记录另存，不把旧token批准当作此次批准。

`apply-approved-pending-five-v1.py --direct-human-v2-approved` 读取正式父归档原快照/逐项审查及当前已发布证据，核验前81/5状态、同候选依赖、原验收/发现、16个完整顺序诊断与物理退出后，仅增量签收DeepSeek、Session、Tools、Web、Profiles五项。调用回执 `approved-pending-five-caller-v1.json` 物理退出0；此前81项任务字节未变。HANDOFF后续16项已在原记录有限范围闭环，全账本 **86 integrated / 0 review**；五新父验收保持同f90候选/原验收摘要，所有原finding原文/SHA移入reviewed_findings，范围限制保留。

只允许四指定目录的完整行唯一键双射排列，以及四独立mux流全局交错。每条流内完整帧/顺序、业务/持久/请求/正文/终止/错误、其余数组/字段及16破坏控制保持严格；五合同的原ordering原文未删除，另附用户批准的有限行为边界。原完整比较qualification=false与原120/1/1/1失败不重标；完整发行证据仍由原单次完整回执提供，本次不是拼接或新运行。任意ABI/调度、付费云、未归因兼容性诊断及延期Win7不因此认证。

正式闭环归档 `migration/evidence/artifacts/HANDOFF-ORDER-CLOSURE-20261010-F90DED26.zip`，SHA256 `6925f810329114a88cf67175fa0660d4080765d9a319d435d40f4394f90d5f25`，保存实际人类批准、精确提案/清单、前后任务/合同、增量脚本、物理调用日志及五新验收记录绑定。维护记录 `migration/evidence/RUN-HANDOFF-ORDER-CLOSURE-20261010-F90DED26.json` 记录16项闭环、86/0状态及清理。原观察/Portable使用已有正式完整/父归档，不新增测试运行或重建Portable。

正式归档逐成员CRC/尺寸/SHA及当前文件字节核验通过后，删除已消费的逐项审查散装副本和本轮before-state ZIP，共2文件、13302237字节；两份原始字节仍分别保存在正式父归档与闭环归档。原工作区/失败/未知材料继续保留，临时写入文件全部原子替换完成。以下十一项已签收/五项待批准及存储阻塞为前阶段历史。

最终元数据核验 `verify-handoff-closure-ledger-v2.py` 物理退出0：执行canonical migration check，再从同一已校验视图生成status及按原CLI规则检查ready，避免重复解析同一台账。86项integrated、81项当前有限验收有效，所有依赖无阻塞，本次16项原验收/发现及五合同原ordering/invariants均核对，ready为空。5项既有历史任务（Inventory、Repro Gate、Search、Web Protocol Discovery、Workflow）维持原集成提交，不冒称本次重新认证。首版附加检查错误要求这5项也有当前验收，canonical check本身通过但首版脚本退出1；原脚本/日志保留，修正版仅纠正验证范围，不改历史任务或伪造当前证据。回执/日志为 `handoff-final-ledger-verification-v2.json`/`.log`。验证范围为台账、同输入依赖、原合同与归档身份；本轮只改文档/台账，因此不重复pytest、全套或构建。文档链接、diff及新归档LFS/批准记录的实际Git字节绑定另核验。

## 完整发行：已通过

第十五轮统一入口 `scripts/verify_release.py` 在干净候选物理退出 0。完整 Python **10520 passed / 6 既有 skipped**，10526 项收集，XML 4077.732 秒；22 组固定 Source 配置、83 配对驱动、实际解压包内 Python 消费者、现代浏览器及 Chromium 108 必需旅程通过。六项跳过是既有 Windows symlink 权限或 POSIX 权限/路径行为边界，不增加跳过。

冻结输入 16701，清单 SHA256 为 `17ff4240fd399abf9108fb1a6eaa867b9bfa085ac07e8d0fbe59ba434673decb`。验收 ZIP SHA256 为 **`61232e8054bbd73c01365579f74357e617383e1956f0cce3357c17eaabe6c509`**，只使用 `dist/dsh-win7-portable-v0.1.0.zip` 此精确包。退出后输入与包不变；后续台账/文档不是新的产品发行认证。

正式完整归档：`migration/evidence/artifacts/HANDOFF-CLEAN-20261010-F90DED26.zip`，138065207 字节，SHA256 `6b6711df6ae94610d909890340e27822cb4c47669b9c8efbf34616e796b3dd9c`。该单次完整回执提供发行证据，不能用多个局部通过拼接另一次完整通过。

## 前阶段父组合与逐项审查：十一项已签收，五项待批准

原父运行先完成五个物理退出 0 的独立任务：九个实际 route/engine/policy/cold/ACP/ownership/close 组合、真实默认 SDK normal/cancel/error、五个默认 profile HTTP、三预设 fresh/cold 完整 wire，以及真实 Web 模型 HTTP。原外层最终退出 **120**，因为最后 UI 报告写入 ENOSPC；仍是失败。后续三个完整 UI 重做分别退出 **1/1/1**，原因是私有临时路径消失、再次 ENOSPC、检查点替换 WinError5，均保留原始拒绝。

原第一次 UI 的前十一独立子进程已物理退出 0：每个完整报告与 fresh/cold Host0、原实际 imports、Source Node22.22.2/Python3.8.10、所选模型及 Low effort 请求使用均严格核对。原观察器推进下一标签的条件、原日志和封存字节共同绑定这些已完成子进程。最后 cordis-own108 在新隔离外部 Host home 单独执行，通过两阶段，物理退出 0、Host 无错误，候选/完整包/观察器输入未变。十二独立旅程覆盖三预设 Source、Root、own-modern、own108；**这不是另一次完整 UI 批次通过，也不是拼接完整发行**。

九个子任务 056–064 已逐一重算完整有序 Source/Root/own 值与原 oracle 摘要，并核对实际模块和全部15561包内字节。十六任务每个原 acceptance、finding 文本与 SHA、依赖及完整消费者证据已审查，原任务/合同快照封存。九个子项、ACP、JS 共十一项的原记录有限范围已独立签收，原 finding 按原文及 SHA 保存在 reviewed_findings，范围限制保留；DeepSeek、Session、Tools、Web、Profiles 五项为 review，原 acceptance/open_findings 保持，仍依赖单独的 Web 顺序决定。任意 ABI、调度、云付费调用及 Win7 真机不在本次有限签收中。

`apply-independent-handoff-ledger-v17.py --independent-literal-scopes-only` 的当前应用物理退出0，调用回执为 `independent-ledger-application-v4.json`，脚本 SHA256 `2a463eb5e0e4483c4896a023805c23fd28660ea7e68408a0da35c65c7c41f227`。74当前复验/子验收和两个独立父验收已写入：65既有有限合同复验、9子项、ACP及JS。全账本 **81 integrated / 5 review / 86**。migration check通过（不是自动对齐证明）；只读五项预检确认所有原条款、五项未清除发现、十一项原发现保留和当前同候选依赖验收。

正式父归档：`migration/evidence/artifacts/HANDOFF-PARENT-REVIEW-20261010-F90DED26.zip`，767809673 字节、1383 成员，SHA256 `9013d05837b14f7c23fee81bf0695900ed6c43332ba6f1a4c18a63372e495526`。保存完整观察、原16任务/合同、逐项审查、观察器、审批提案、原120/1/1/1拒绝及两个诊断；原 Portable 只在引用的完整归档保存一份。封存后退休的散装报告应按对应审计的 archive/member 查找，不能再假设原散装路径存在。

待独立批准的 v2 提案位于 `.goose/out/continuation-20261008-v1/wire-order-review-v2.md`，绑定清单位于相邻 `wire-order-review-v2-bindings.json`。16 个当前完整比较已重新计算：只涉及四指定目录完整行排列和四独立 mux 流全局交错，其余字段、流内、业务/持久、请求、终止与错误严格一致。原合同禁止排序掩盖注册/发布差异，因此不能把 token 批准当作顺序批准。原始全局顺序仍完整保存。

## 清理与已解除的磁盘阻塞

完整门禁有 997 份清理审计：993 完成，6348 文件、**13964953532 字节**已清理；四个故意失败/未完成负例保留。最后 own108 使用的解压副本在逐文件输入及生成 bytecode 归属核验后删除，15715 文件、250494010 字节。其他已结束的解压副本也按独立审计及时退休。

大量散装原始观察仅在正式 ZIP/member CRC、尺寸及逐字节 SHA 核验后删除重复副本。失败、截断观察仍在正式归档，不重新标为成功。归档前的 V4/V5/V6 小快照在父归档保存完全相同嵌套字节后才删除外层重复。闭合观察另采用 NTFS 压缩，保持读取字节不变。没有删除未知/活动 home、正式证据或 `.goose/out/lfs-original-history-20261007.git`，没有 bulk-delete `.goose/out`。

此前 ledger 写入两次因 C 盘 ENOSPC 退出 1。第一条记录及第二次第16条均留下零字节文件，已原样移到本轮 ignored 失败目录；第二次前15条未引用完整准备记录与保留 gzip 数据按 ASCII/CRLF 重建后逐字节一致，回退这些可重建副本。那两次原16任务字节保持不变，不能把失败写入当作签收。新增占用来源未确认；空间前检不足时第三次应用在写入前拒绝。用户随后释放空间，本轮前检为215768248320可用字节；第四次应用已物理退出0，当前状态以上节为准。

本轮又删除36个已闭合原始观察副本56229454字节；只按正式父ZIP/member的CRC、尺寸、逐字节SHA及自身目录归属核验后逐项删除。另核对74已发布记录值与准备数据相等，把原51564464字节gzip在正式维护归档保留一次后删除临时准备副本。本轮共37文件、107793918字节，未把新增正式归档占用说成净释放空间。完成测试的合成大回执定向复查未发现新增残留。零字节压缩审计和458字节失败ZIP原样封存，不补造当时成功审计。

正式维护归档：`migration/evidence/artifacts/HANDOFF-POST-REVIEW-STORAGE-20261010-F90DED26.zip`，SHA256 `84fb6beead41a1dfb604dc43957bdf9ff299dd9cd17c8452263cd73d514597b0`，含当前成功应用、此前存储失败、各次重复副本退休审计、待批准预检和准备gzip原字节。对应记录 `migration/evidence/RUN-HANDOFF-STORAGE-LEDGER-20261010-F90DED26.json` 如实记录删除及81/5状态；这是维护证据，不是新发行认证。

此前接续使用 `review-pending-five-preflight-v1.py` 只读逻辑及 `pending-five-preflight-v1.json`，直接读取正式父归档原快照/逐项审查与当前已发布记录，无需恢复临时准备gzip。本次已取得并绑定实际人类v2批准，再用五项增量入口完成签收。**旧全16、11项、五项应用脚本及81/5前置预检均不可直接重跑**，已完成的状态/路径前置条件不再满足；它们只作历史证据。后续继续兼容诊断，不再把16项当作待签收任务。按实际变更执行migration check/ready/status和diff/链接检查；文档/台账提交不因此重复全套或重建Portable，认证候选仍为原f90ded26及精确ZIP。

## 兼容性待查

用户认可后，已完成充足空间下的本机定向复核：源码standard仓库内、同一验收Portable自有Python的cordis仓库内、仓库外三个实际原版浏览器场景，每个fresh/cold，两阶段共六次Host物理退出0；三个浏览器调用分别退出0。生产14773输入、包内15561文件、原ZIP及观察器在运行前后核对不变。实际浏览器为本机现代Edge，Python3.8.10、固定Node22.22.2；这不是新的完整发行或Win7真机测试。

空间以真实epoch/monotonic时间每0.5秒采样，三个场景52/55/56条、最大间隔0.516秒，最低247199715328可用字节（约247.2GB）；临时/输出/产品卷及每个目录/检查点操作另记录空间。15次materialize返回路径当时存在、35次原os.replace检查点替换成功，无相应错误。六个私有temp均由原owner结束时dispose，最终路径不存在。六阶段Host stderr为空，页面/console错误数组为空；浏览器进程stderr中Edge自身后台导入/同步/组件诊断按原文保留。缺失私有目录、检查点WinError5本次均未重现；只能说明充足空间下这次通过，不能证明旧错误由磁盘满引起或生产根因已修复。未加入生产重试、错误过滤或新上游判据。

正式诊断归档 `migration/evidence/artifacts/DISK-PRESSURE-UI-DIAGNOSTIC-20261010-F90DED26.zip`，94087507字节，SHA256 `8a044a02c37999d6eb374512fb1e9d1339c06002b44dd0abb36cb68e8e57d1aa`。含本次完整原始浏览器/Host观察、连续空间、生命周期、原操作结果、实际调用、观察器及清理前归属清单；原失败、Source记录和Portable引用已有正式归档，不再重复打包。记录 `migration/evidence/RUN-DISK-PRESSURE-UI-DIAGNOSTIC-20261010-F90DED26.json` 为research，台账任务/合同未变。canonical migration check物理退出0，完整归档/输入/pin/依赖有效；同一已校验视图生成status和ready，86 integrated/0 review、ready为空，新增research不作为任务验收。文档链接、diff及实际Git LF/LFS字节绑定核验通过；验证范围对应本次诊断与元数据变更，不重复pytest、完整门禁或Portable构建。

归档逐成员CRC/尺寸/SHA核验后，清理本次结束的三个Host home、三个工作区、精确解压runtime、两份封存Source复制报告及三个浏览器大报告重复副本：15608文件、705038941逻辑字节（约705MB）。655个新建junction/symlink均由本次link-created事件绑定，no-follow核验后只移除链接本身，目标当时仍在；六个浏览器profile已由原观察器在进程退出后删除。小型日志/审计保留，未删除未知/活动/原失败目录或保护历史，94MB新增正式归档占用另计。封存脚本v1错误把浏览器原始stderr当页面错误、v2错误使用Windows DirEntry缓存nlink=0，两次均在写归档/删除前拒绝；原脚本和拒绝记录封存，v3使用原观察器判据及直接no-follow lstat，物理退出0。此为封存检查纠正，未改原始运行结果或重跑浏览器。

用户补充：本机测试期间硬盘曾满，可能导致error。磁盘压力列为优先环境假设。已有明确ENOSPC的报告/台账写入失败可归因于空间不足；另外两种原始错误与磁盘压力的因果关系仍需证据。正式父归档中v5 `storage-preflight.json` 记录启动前1038700544可用字节（约1.04GB），v7记录3226644480字节（约3.23GB）；这是启动前快照，未记录错误瞬间余量，不能据此排除运行中耗尽，也不能直接归因。上述成员按父归档manifest SHA核对，未生成新的解压测试副本。后续若再运行相关场景，应同步记录错误时间、对应临时/输出卷空间与目录/检查点生命周期，结束后及时清理已核验自有副本。当前不把这两种本机异常认定为已证明的Win7专属兼容缺陷，不改变原失败结论或追加生产绕过。

v5 的私有临时目录消失在同场景 fresh/cold 诊断中未重现；诊断观察一次共享 owner 创建、复用和最终 revoke/delete，不识别原删除者。v7 的缓存 `os.replace` WinError5 在仓库内/外实际 own Cordis fresh/cold 诊断中均未重现，RestartManager holder 探针只在真实失败时触发，因此未识别持有者。未加入生产重试、抑制日志或新的上游例外，不能声称根因修复。

既有原始 HTTP10054、短期限缓存、ReplaceFileW1175/5 等未归因材料保持；后续有限通过不识别原原因。已实施的 UCRT/原生搜索、Host CSS、预设组合、DTO/模型/计划、欢迎状态和工作区兼容修复由单次当前完整发行覆盖，但现代 Windows 与108通过不等于 Win7 真机认证。Win7认证继续按用户决定延期。
