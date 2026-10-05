# Ready发出前的初始管道退出

040已有界进入主树，尚未完整签收。最新完整签收仍为47adea37；本次门禁增加到876必需lane、60实际配对，十八组1237原样Source断言不变。

实际原版WorkerRun启动真实Node Worker，公开的计时bootstrap在加载独立保留的原版worker bundle前使用SharedArrayBuffer屏障暂停；物理终止时Ready尚未发出。原生持有真实stdin初始字节，在真实私有worker死亡并等待退出后，继续原始StreamWriter写入和drain。未取消时，原版返回真实exit code 1对应的workflow退出结果，47adea原生却返回generic Connection lost；先以空原因取消时，两侧首个取消结果一致。两组完整result、事件、child requests、入口屏障、零Ready消息、退出码及dispose观察不删字段、不归一化。

根因是初始管道失败覆盖reader已经记录的物理退出。open现仅在清理前已经观察到退出、原始错误为BrokenPipeError或ConnectionResetError、且存在真实JavaScriptWorkerExitError时传播记录的失败并保留cause。四个独立原生控制交叉两类管道错误与live/already-exited状态；活进程被清理终止不能反过来将原始管道错误升级为物理退出。这四个控制不算额外Source配对。

保留的研究证据位于.goose/out/acp-a4-work：js-before-ready-source-v1、native-v1、fixed-v1及comparison-v1，四项控制baseline/fixed-v1/v2和实际原版三份编译bundle。v1控制把ready future settled误称admitted，v2明确区分成功准入与异常结算，旧输出保留。正式js-initial-product-paired-v1两组完整观察一致，绑定干净原版pin、Node22.22.2、实际导入模块及19项私有资源。隔离修改过的Portable只是研究原型，不作为精确发行验收。

157项产品/工作流定向回归通过。762项门禁/解释器/Ready/context定向回归结果为761 passed、1 failed（303.21秒）；唯一失败为门禁自身仍断言旧823数量，现显式修正为876，旧日志/XML仍保留于js-initial-gate-focused-v1。单项修正另外验证，不能把首次失败改写为通过。

真实解压资格要求Portable自己的Python3.8.10、全部实际模块/私有资源、Source完整观察摘要，以及missing/changed/partial/duplicate/outcome/phase/entry/emission等拒绝lane。候选须独立提交后冻结完整门禁，尚不推进integrated。本屏障与038已经发出Ready后的交付控制不同，不涵盖所有spawn/Ready竞争、八项原始engine/parse差异、完整model/profile/C2。九项Source缺陷判据及C58/C59不变，整体accepted_upstream仍为空，真实Win7继续延期。
