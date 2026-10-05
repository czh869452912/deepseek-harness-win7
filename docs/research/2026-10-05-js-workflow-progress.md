# 通用JavaScript工作流推进

最新完整有界签收仍为产品 `6ceef0f9`（6944通过、496必需lane、55配对），记录提交 `a016e434`。本部分开始036，不能用私有引擎可执行或研究用例替代工作流/C2验收。

私有QuickJS-NG0.17.0输入固定至 `6d46d07d04041b40f4f49eaa7fdebe44c314c699`，官方源码ZIP SHA256为 `d0d41bf4842480ca8672a856eb86cb2d5cb6aae008072c9fe91786f9185a0692`。构建器逐文件验证228项源码和MSVCRT编译器归档闭包，拒绝修改、额外输入与路径逃逸；保存命令、源码/编译器/wrapper/产物及许可哈希。QuickJS完整许可、源文件额外版权声明（含atomics）及静态LLVM/MinGW/winpthreads许可随提供端保留。

二个真实JS context共享一个runtime：脚本在script realm编译执行，args/冻结函数来自host realm。一次进程只承载一次运行；stdout专用于JSON协议。解析与运行分离；ready后必须go/cancel才可执行。C wrapper初始同步切片有中断预算，后续Promise工作仍在独立进程；宿主可在取消宽限后物理终止。PE版本为Windows6.1，只直接导入KERNEL32/msvcrt，实际Win7依旧未认证。worker SHA256为 `7bfad5d6b20510e9827f466358080f02bdd4fa8f1a4666d27ae6bece4b091740`，完整构建来源和许可在 `dsh/javascript/bin`。

`ctx.jsRuntime` 提供端能显式挂载；每次解析/创建前检查私有资源，环境仅转交TMP/TEMP，自有进程在创建取消、提供端卸载和宽限结束时排空/终止。最初19项真实进程与资源反例通过，连同现有Ralph/workflow消费者共77项通过；补齐五项归档输入拒绝及实际迟到spawn/卸载竞争后25项通过。卸载先关闭新工作准入，既有spawn拥有共享cleanup，迟到进程不得在已卸载服务上登记。首轮夹具把200000字符预期值放入pytest默认id，Windows的PYTEST_CURRENT_TEST超过32767而出现2项setup/teardown错误；原始日志保留，显式短id修正后实际大响应观察通过。这不是产品错误绕过或新增skip。

22组实际 pinned WorkflowExecution与初始引擎研究记录保留在 `.goose/out/acp-a4-work/js-runtime-{source,prototype}-v1.json`。闭包/循环/Promise、host realm、phase/log、root undefined、own __proto__、null prototype、DAG、getter/Proxy、非canonical数组别名、non-enumerable与自定义抛值共14组完整匹配。其余8组错误和解析文本不同：QuickJS默认stack不含Node形式的错误首行，且宿主/引擎栈和SyntaxError不同。原始差异没有被过滤、豁免或计为通过。

生产WorkflowEngine尚未消费此提供端，仍拒绝未登记的任意脚本。下一实施是Source-backed子代理start/result/disposal、fatal与普通失败、FIFO/caps、parallel/pipeline、materialization、取消/先终态/迟到回执，以及原版builtin/model/profile与持有run跨engine卸载。完成消费者后再签发干净全量和实际解压来源绑定证据。Node/Intl/WebAssembly/任意Cordis插件/SDK/preset/trust与全部C2继续具名开放，`accepted_upstream`仍为空。

提供端实现提交 `696802b3`。首次提交后的Git属性审查发现未固定私有JSON/许可资源字节；自动CRLF转换会令其他checkout与清单哈希不符。现对私有资源设置-text、C wrapper固定LF，并逐个核对index中的原始blob与实际清单/文件字节。此修正保持二进制和manifest原始哈希不变，不能以本机运行通过代替重新检出的便携资源证明。

后续工作流worker基础已接入：固定Source的session/runtime/realm/json-schema算法保持原样，经固定esbuild0.28.2构建为42613字节IIFE。自有vm桥仅将相同wrapper的已编译真实脚本交给script context，并转交初始同步预算；自有port桥承载原版消息，不替换子代理、组合器或materialization算法。构建记录Source闭包、适配器、开发Node/bundler字节及许可；运行只读取已固定的私有资源，不依赖Node或TS。新worker SHA256为 `26609aa1d86b3d4f8509859ad94d79229b40abd9978f4faf0d237c45e88259aa`，引擎manifest为 `234dce43f6963a751b8024b7133a271f0cde12bd96fec215d91ad9404a4967d9`，工作流manifest为 `cc42006bfdbfb86cc0e32bc031d86dc35ff06b6c239674594fa42ec1ceaca686`。

实际Source worker与私有worker的首批25场景有21组匹配，4组失败原始帧保留于 `js-children-{source-v1,native-v1}.json`。根因是QuickJS把内置Object/Array构造器打印成多行，而原版lossless-JSON/schema守卫明确要求Node的单行intrinsic字符串。C适配器仅按两个realm的真实构造器身份转交单行字符串，其他函数沿用原始实现；未修改原版守卫。补充host-realm、descriptor、仿冒构造器、重命名和跨realm schema后，30组完整消息匹配，含负零符号、文本/结构化子结果、provider/model、FIFO、总量/items cap、parallel/pipeline、普通失败、fatal参数、取消及丢弃child在Result后的end/log。Result之后进程继续承载消息，直到holder或提供端物理终止；基础进程25项和现有消费者58项一并共119项通过。原始观察在pytest各场景目录；研究v1/v2拒绝与成功记录均保留，没有新增原版bug例外。

第一次新增回归是55通过、1失败：资源损坏实际被正确拒绝，但测试匹配 `differs` 未接受manifest消息中的 `differ`。修正断言后119通过；失败日志/XML保留于 `.goose/out/acp-a4-work/js-source-session-focused-v1.*`，后续通过记录为v2。构造器适配未消除此前8项原始stack/parse差异，它们继续开放。完整Python宿主的provider发布/迟到拒绝/共享disposal/死亡边界、WorkflowEngine/Ralph/canonical消费者及实际解压尚未接入。此提交不签收036、C2或整体迁移，仍须干净全量门禁。
