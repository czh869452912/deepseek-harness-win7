# 通用JavaScript工作流推进

最新干净门禁产品 `17c1c521bb6743bcb1bc28942db315a614d4866d`：7077通过、6既有skip、1既有Proactor warning、0失败，1754.75秒；629必需lane、十八组1237原样Source断言、56实际配对、真实解压Python3.8.10/原版浏览器均通过。46个既有有界范围重验；036仍running，只新增部分verification，不能把30场景/12消费者回归或私有引擎可执行当作完整工作流/C2签收。原版九项判据、八项原始engine/parse差异和整体accepted_upstream保持不变。下文保留各次实施与开发拒绝历史。

私有QuickJS-NG0.17.0输入固定至 `6d46d07d04041b40f4f49eaa7fdebe44c314c699`，官方源码ZIP SHA256为 `d0d41bf4842480ca8672a856eb86cb2d5cb6aae008072c9fe91786f9185a0692`。构建器逐文件验证228项源码和MSVCRT编译器归档闭包，拒绝修改、额外输入与路径逃逸；保存命令、源码/编译器/wrapper/产物及许可哈希。QuickJS完整许可、源文件额外版权声明（含atomics）及静态LLVM/MinGW/winpthreads许可随提供端保留。

二个真实JS context共享一个runtime：脚本在script realm编译执行，args/冻结函数来自host realm。一次进程只承载一次运行；stdout专用于JSON协议。解析与运行分离；ready后必须go/cancel才可执行。C wrapper初始同步切片有中断预算，后续Promise工作仍在独立进程；宿主可在取消宽限后物理终止。PE版本为Windows6.1，只直接导入KERNEL32/msvcrt，实际Win7依旧未认证。worker SHA256为 `7bfad5d6b20510e9827f466358080f02bdd4fa8f1a4666d27ae6bece4b091740`，完整构建来源和许可在 `dsh/javascript/bin`。

`ctx.jsRuntime` 提供端能显式挂载；每次解析/创建前检查私有资源，环境仅转交TMP/TEMP，自有进程在创建取消、提供端卸载和宽限结束时排空/终止。最初19项真实进程与资源反例通过，连同现有Ralph/workflow消费者共77项通过；补齐五项归档输入拒绝及实际迟到spawn/卸载竞争后25项通过。卸载先关闭新工作准入，既有spawn拥有共享cleanup，迟到进程不得在已卸载服务上登记。首轮夹具把200000字符预期值放入pytest默认id，Windows的PYTEST_CURRENT_TEST超过32767而出现2项setup/teardown错误；原始日志保留，显式短id修正后实际大响应观察通过。这不是产品错误绕过或新增skip。

22组实际 pinned WorkflowExecution与初始引擎研究记录保留在 `.goose/out/acp-a4-work/js-runtime-{source,prototype}-v1.json`。闭包/循环/Promise、host realm、phase/log、root undefined、own __proto__、null prototype、DAG、getter/Proxy、非canonical数组别名、non-enumerable与自定义抛值共14组完整匹配。其余8组错误和解析文本不同：QuickJS默认stack不含Node形式的错误首行，且宿主/引擎栈和SyntaxError不同。原始差异没有被过滤、豁免或计为通过。

生产WorkflowEngine尚未消费此提供端，仍拒绝未登记的任意脚本。下一实施是Source-backed子代理start/result/disposal、fatal与普通失败、FIFO/caps、parallel/pipeline、materialization、取消/先终态/迟到回执，以及原版builtin/model/profile与持有run跨engine卸载。完成消费者后再签发干净全量和实际解压来源绑定证据。Node/Intl/WebAssembly/任意Cordis插件/SDK/preset/trust与全部C2继续具名开放，`accepted_upstream`仍为空。

提供端实现提交 `696802b3`。首次提交后的Git属性审查发现未固定私有JSON/许可资源字节；自动CRLF转换会令其他checkout与清单哈希不符。现对私有资源设置-text、C wrapper固定LF，并逐个核对index中的原始blob与实际清单/文件字节。此修正保持二进制和manifest原始哈希不变，不能以本机运行通过代替重新检出的便携资源证明。

后续工作流worker基础已接入：固定Source的session/runtime/realm/json-schema算法保持原样，经固定esbuild0.28.2构建为42613字节IIFE。自有vm桥仅将相同wrapper的已编译真实脚本交给script context，并转交初始同步预算；自有port桥承载原版消息，不替换子代理、组合器或materialization算法。构建记录Source闭包、适配器、开发Node/bundler字节及许可；运行只读取已固定的私有资源，不依赖Node或TS。新worker SHA256为 `26609aa1d86b3d4f8509859ad94d79229b40abd9978f4faf0d237c45e88259aa`，引擎manifest为 `234dce43f6963a751b8024b7133a271f0cde12bd96fec215d91ad9404a4967d9`，工作流manifest为 `cc42006bfdbfb86cc0e32bc031d86dc35ff06b6c239674594fa42ec1ceaca686`。

实际Source worker与私有worker的首批25场景有21组匹配，4组失败原始帧保留于 `js-children-{source-v1,native-v1}.json`。根因是QuickJS把内置Object/Array构造器打印成多行，而原版lossless-JSON/schema守卫明确要求Node的单行intrinsic字符串。C适配器仅按两个realm的真实构造器身份转交单行字符串，其他函数沿用原始实现；未修改原版守卫。补充host-realm、descriptor、仿冒构造器、重命名和跨realm schema后，30组完整消息匹配，含负零符号、文本/结构化子结果、provider/model、FIFO、总量/items cap、parallel/pipeline、普通失败、fatal参数、取消及丢弃child在Result后的end/log。Result之后进程继续承载消息，直到holder或提供端物理终止；基础进程25项和现有消费者58项一并共119项通过。原始观察在pytest各场景目录；研究v1/v2拒绝与成功记录均保留，没有新增原版bug例外。

第一次新增回归是55通过、1失败：资源损坏实际被正确拒绝，但测试匹配 `differs` 未接受manifest消息中的 `differ`。修正断言后119通过；失败日志/XML保留于 `.goose/out/acp-a4-work/js-source-session-focused-v1.*`，后续通过记录为v2。构造器适配未消除此前8项原始stack/parse差异，它们继续开放。完整Python宿主的provider发布/迟到拒绝/共享disposal/死亡边界、WorkflowEngine/Ralph/canonical消费者及实际解压尚未接入。此提交不签收036、C2或整体迁移，仍须干净全量门禁。

worker基础提交为 `0ca45ea2`。随后Python宿主已通过动态 `ctx.jsRuntime` 接入实际 `ctx.subagents`，保留同步接受计数/provider启动前缀、统一abort、迟到provider拒绝后独立清理、共享child disposal、先Result/死亡/宽限终态以及Result后的生命周期消息。原版WorkerRun与规范Native WorkflowEngine的30组实际观察匹配；Source的结果回调前缀在Native中通过独立的done callback与消息边界排空保留。Windows canonical boot在root挂载原生JS服务，engine卸载不卸载root提供端；规范Ralph不再注册Python映射，改为执行已固定的原版脚本。私有Runtime缺失的历史直接单测仍明确属于旧映射检查。

新增12项真实消费者回归通过：四种Ralph状态、caller pipeline/实际durable记录、持有run在engine卸载后继续第二个child、迟到provider的拒绝回执不等待慢disposal、取消宽限后的Promise/CPU物理终止、parse在发布之前失败和缺失args保持undefined。此前149项worker/host/历史消费者回归及规范Web冷恢复已通过；没有远程付费模型调用。发布门禁新增当前JS必需lane、实际Source/native配对及实际解压模块/私有资源/完整观察校验，仍须冻结全量验收。

保留三类开发拒绝：早期Native host研究夹具缺少真实parent.ctx，触发Subagent通知失败，修正夹具后30配对；host首次pytest为29通过、1失败，立即dispose与迟到消息竞争导致双方观察到不同消息数，现在在两侧共同持有run直到真实agent-end/log边界才dispose，早期无控制竞争记录保留而不宣称其唯一序列；配对CLI第一版把Path导入放在参数声明后，NameError导致observer1拒绝，修正导入后新输出30匹配。相关v1/v2原始JSON/日志/XML保持独立；未新增skip、错误过滤、原版bug豁免或放宽原版断言。八项原始stack/parse差异及完整Node/SDK/插件、模型/profile和全部C2仍未闭环。

发布门禁现在固定629必需lane、56双侧驱动和十八组1237原样Source断言，增加解压30场景的实际Python3.8.10模块、19项JS私有资源和完整观察身份检查。运行时在解压目录尚存在时核对实际文件，外层已归档回执再以该次live检查和确切候选closure核对；不错误地重读TemporaryDirectory退出后已删除的目录。门禁定向为700通过、1项旧硬编码lane总数断言失败；严格更新496至629后该断言通过，未放宽任何必需项。预冻结验证一度使用默认Node22.20而触发30项Source fixture setup拒绝，保持严格版本要求并正确设置固定22.22.2后74项通过。失败与成功日志/XML独立保留，当前仍待冻结完整门禁。

定向门禁在pytest-703生成327个可重建合成JSON，共3453851061字节。候选清单 `unit-receipt-cleanup-candidates-v3.json` 仅选择具有 `runtime.checks=[actual runtime]` 且所在测试目录的portable.zip字节严格等于 `exact candidate archive` 的结构单测回执；实际Source/native观察、失败日志、XML与真实包不在清单中。此清单属于新的清理范围，已另行请求授权，不能套用此前两份清理许可。

预冻结独立pytest运行触发pytest默认旧临时目录回收，v3清单327项随后均已不存在，本代理没有执行该清单删除。清单及全部 `.goose/out/acp-a4-work` 原始配对/日志/XML仍保留；此申请不扩展至未来文件或任何不同清单。后续完整门禁使用独立 `--basetemp` 目录，保留该次验收输入与观察。

冻结候选完整门禁已完成，`result=passed`、`publishable=true`、`worktree_dirty=false`。Source/native宿主和实际解压观察digest均为 `b440a07031bf1069c0a5de0db0355b28fa62c9ecdfff2ff37e1361a1e06b58b8`，真实导入模块及19项私有资源均核对选定根目录和字节。精确Portable SHA256为 `eebe1c6b48629b332e2719ae78a7ae9ce7c5bb0e427bcfc900d368f7720ccbc9`，冻结输入清单SHA256为 `9bea41bb5519fba5d7b57faf23e7ec2c6d57bfddf13cac5987871a92a562d66c`。归档 `migration/evidence/artifacts/JS-WORKFLOW-20261005-17c1c521.zip` SHA256为 `e1bc67d42ae0999ad163b618e0679d434934c356ee48e6ea67637090a5d21fbc`，CRC、每个门禁回执及内嵌精确ZIP已验证；包括原始22组差异和开发拒绝日志/XML/JSON，旧TOOLS-HTTP归档按原哈希独立链接。

后续继续实际Source宿主的进程提前退出、迟到provider、共享disposal和回调重入边界，再补齐完整模型/profile旅程。当前门禁未归因旧1175/启动取消/Proactor/HTTP10054，未重跑不变候选、修改Source pin/frontend或新增例外；实际Win7仍延期。
