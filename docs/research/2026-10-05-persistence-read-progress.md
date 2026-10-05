# 规范持久化公共读取

2026-10-06：47adea完整干净门禁7271 passed及823必需lane、59配对、十八组1237原版断言与真实解压/浏览器通过，039的51组已有界integrated，见 `migration/reviews/RUNTIME-CONTEXT-READ-GATE-20261006.md`。公共Session另一组51观察的数值/扩展头部/冻结差异只完成隔离修复和303+107原型回归，不属于本合同或47adea签收；完整B1仍开放。

原版真实Cordis、SessionStore、plaintext/zstd JSONL及SQLite服务与原生规范服务的45组观察，暴露21组逐字段差异：createdAt与append seq的整数值浮点被过度拒绝，readFrom也拒绝0.0/-0.0，append负零和布尔拒绝消息不一致，已完成物理读取后取消仍返回成功；JSONL还漏转发信号。所有原始Source-v1、Native-v1、对照-v1与原生模块身份保留于 `.goose/out/acp-a4-work/persistence-public-*`。

第二组6项实际顺序观察涵盖排队取消、SQLite legacy前缀回读信号和取消后的backend错误优先级。第一版排队探针在新协程真正进入队列前取消，两侧都拒绝，未证明排队分支；原始生产者和v1记录独立保留。v2通过真实Source serialize/原生storage_lock入口屏障确认第二次读已在第一条真实物理读取后排队，再取消。未改实现的三后端均未在释放前结算，释放后还读取第二次；隔离修正在三者释放前保留原始取消理由且不进行第二次物理读取。完整6组均从baseline差异转为匹配，日志/对照为 `persistence-order-*-v2.*`。

隔离候选来自精确7060e67b Portable，修改仅限协调器与两套规范提供端，使用其自己的Python3.8.10；45+6组完整观察均匹配后才迁入主树。lossless snapshot继续先拒绝负零等非JSON值，再在准入的安全整数范围内适配Python整数值float；createdAt/seq转为可持久化int，bool不作为number。取消信号转发物理读取，前后检查；排队read取消可提前结算而其受控后台任务随后检查signal、不进入物理读取。SQLite legacy完整前缀读也转发信号，已有取消在suffix backend失败时保持优先。Source算法、格式与bug判据不改。

正式配对 `persistence-read-product-paired-v2.*` 51组通过。v1观察器误用libzstd.dll作为私有资源名称，实际产物是dsh_zstd.dll，导致观察器自身资源闭包拒绝；该runner-error及两侧原始输出保留，修正名称后使用独立v2输出，没有覆盖或重试不变产品门禁。新消费者比较每个完整row：值、确切有界错误、reasonIdentity、实际物理hook次数/转发、释放前结算、首个读与后续读。Source清洁pin/Node22.22.2和13项静态guard、实际两套原版服务测试绑定证据；guard不是全部动态导入闭包。原生/解压绑定实际选择的解释器、所有实际导入模块和SQL/SQLite/Zstd私有文件。

主树消费者及既有规范JSONL/SQLite、public storage/live/prepared的193项聚焦回归通过（58.44秒），尚不代替完整签收。新CON-PERSISTENCE-READ@1只签收这51组，任意元数据/事件/plugin ABI、所有取消/退休/竞争时序、完整profile及B1继续开放。当前门禁823必需lane、59配对，原版十八组1237断言、119前端输入、九项Source bug判据及C58/C59不变；037/038/039须新的不同干净完整候选通过后签收，JS036与整体accepted_upstream继续开放，真实Win7延期。

全部门禁拒绝、新51消费者、四类观察器的精确解释器身份及037/038消费者在仓库内basetemp的781项定向回归通过（301.71秒），日志/XML为 `.goose/out/acp-a4-work/persistence-read-gate-focused-v1.*`。有意覆盖先前仅在仓库外夹具通过的身份拒绝分支；没有以定向通过签收两份旧拒绝产品或新的完整候选。
