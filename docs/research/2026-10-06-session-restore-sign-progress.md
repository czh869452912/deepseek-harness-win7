# 公共Session恢复数值符号

实际原版Session.fromRestore对六字段各whole/negative-zero/fraction，共18组控制。观察接受或精确错误，以及Number.isSafeInteger、Object.is(actual,-0)、Object.is(actual,input)实际数值谓词。Python数学符号及数值相等表达同一数值谓词，不过滤输出，不声称完整Header图/对象身份或JSON wire等价。

基线14组匹配，version/createdAt/seedLength/delegationDepth四字段恢复负零被int转换为正零。seq/time已经正确。精确未修改4a127b73 Portable以其自有Python3.8.10也复现同样四项差异；完整差分为.goose/out/acp-a4-work/session-boundaries-exact-4a-baseline-comparison-v1.json。隔离Source/native/fixed原始记录保留于session-restore-sign-*，两项诊断/恢复研究的完整行比较和51组初版创建控制再次匹配；该修改原型不是可签收Portable。

修复只移除字段验证后的int转换，保留已经准入的原始数值及符号。Session.create先进行lossless快照，仍拒绝负零并将安全whole float适配到内部整数表示；恢复直接验证所有权归属的数据，不能再改变数值。已发布对象冻结、可变独立query副本和未知元数据继续按CON-SESSION-NUMBERS修订2执行。

正式主树18完整观察匹配，原始Source/native和模块身份见session-restore-sign-product-paired-v1。扩大1457项回归通过（454.71秒），同时验证创建53控制、诊断76控制、恢复18控制、独立属性/复制/导出保护、全部精确拒绝门禁、解释器及实际corpus/list/load/lineage/snapshot Source消费者。日志/XML为session-restore-sign-focused-v1；它仍不替代完整pytest tests及冻结解压/浏览器验收。

CON-SESSION-RESTORE-SIGN@1限定18数值控制。16项独立原生属性/浅复制/深复制/导出符号保护不冒充Source配对。必需拒绝包括负零/input-value/safeInteger结果、错误、缺项/重复、Source/模块/解释器身份。实际门禁要求1167必需lane、63配对、十八组1237原样Source断言；任务保持running，全量/解压/浏览器验收仍待执行。完整恢复图/别名/循环复制、malformed/public plugin ABI、长期/多进程/多workspace、完整B1/B/C/D及延期Win7继续开放；九项原版缺陷判据、C58/C59与accepted_upstream不变。
