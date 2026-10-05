# 公共Session数值及只读元数据

041已有界进入主树，最新完整签收仍为47adea37。实际原版Session.create与Python公开Session.create执行51组观察：version/createdAt/seedLength/delegationDepth/seq/time六字段各八种数值，再加未知字段、顶层修改及嵌套修改。原始基线42组匹配、九组不同：六组whole浮点过度拒绝、未知元数据丢弃、公开header顶层可变和嵌套字段缺失。研究原始Source/native/fixed及comparison-v1、输入和日志保留于.goose/out/acp-a4-work/session-number-*，不改写失败记录。

JSON提供端在负零/非有限值拒绝之后，将安全整数值的float快照为整数表示；真正字段验证接受安全整数类型，仍拒绝boolean。这是产品内部表示适配，观察输出不删除字段或归一化。validated header保留完整JSON记录，并冻结独立图和已发布属性；用于组装的SessionHeader DTO保持其原有用途。to_dict导出与浅/深复制保留元数据且分离图，由四项独立原生回归验证，不算额外Source配对。

隔离原型通过303项核心Session/token回放与107项query/实际storage消费者。正式主树session-number-product-paired-v1的51完整观察匹配，绑定干净原版pin、Node22.22.2、静态Source守护清单和实际原生导入模块。守护清单不冒充动态Source导入闭包；完整冻结门禁另绑定整个输入清单。Source Error在该准入边界对应Python ValueError，其他异常会令观察器失败。

主树1233项公开Session/token回放、实际query/规范JSONL/SQLite、公共数值/取消read与全部门禁/解释器/拒绝定向回归通过（357.95秒）；原始日志/XML为.goose/out/acp-a4-work/session-number-focused-v1。041的73项消费者与新增拒绝lane全部通过。

门禁增至969必需lane、61实际配对；十八组1237原样Source断言不变。真实解压使用Portable自己的Python3.8.10和完整模块来源，拒绝缺失/变化Source、模块、解释器、尾项、重复、准入结果、元数据/修改/输入归属等损坏证据。必须独立提交、冻结不同干净候选并通过完整pytest/解压/原版浏览器后再推进integrated，当前没有新的完整签收。

Session.fromRestore数值符号/身份、任意malformed/public plugin ABI、图循环复制、长期/多workspace/多进程及完整B1/profile继续开放。040初始写入退出、JS036和完整B/C/D各自保留范围；九项Source缺陷判据及C58/C59不变，accepted_upstream仍为空，真实Win7继续延期。
