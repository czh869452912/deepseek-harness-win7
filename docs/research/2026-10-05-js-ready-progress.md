# Ready交付跨物理退出

2026-10-06：47adea完整干净门禁及实际解压/原版浏览器通过，038两组已发出Ready跨退出已有界integrated，详见 `migration/reviews/RUNTIME-CONTEXT-READ-GATE-20261006.md`。发出前的初始写入研究另复现真实Connection-lost分类差异，仅隔离原型匹配，不属于038或47adea签收；JS036继续running。

原版真实WorkerRun/worker与原生真实Context/JavaScriptRuntime/WorkflowEngine分别持有已经发出的Ready消息，在宿主处理或发布worker前物理终止进程；随后准入该迟到消息。无取消时，原版返回 `workflow worker exited before the run settled (exit code 1)`，旧原生却在Go/send路径返回 `workflow worker failed: JavaScript worker already exited`。另一组先以空原因cancel，再终止，首个取消结果两侧已经一致。原始 `js-ready-delivery-source-v1.json`、`js-ready-delivery-native-v1.json`、对应日志及生产者保留在 `.goose/out/acp-a4-work/`；修正后Native-v2两组完整观察均匹配，独立正式配对 `js-ready-product-paired-v1.*` 也通过。

根因在低层open只等待Ready成功，未检查同一个reader已记录的物理退出失败；宿主opening又把该物理失败归为generic。现open在返回worker前传播已记录失败，WorkflowRun._open按既有WORKER_EXIT类别处理。正常快速terminal、协议失败与既有取消语义由原有实际消费者继续覆盖，没有新增Source bug绕过或修改原版worker算法。原版观察只在实际Ready接收边界控制交付；原生只控制真实stdout.readline交付，均物理终止真实worker，未模拟产品结果。

正式CON-JS-READY@1覆盖两组有界合同：完整result、所有按序事件、空child requests、准入前状态、真实exit code、首个结果保持与dispose归属逐字段比较，不删除字段或规范化。Source输入为真实esbuild导入闭包且绑定原版pin/clean checkout/Node22.22.2，Native绑定实际3.8.10解释器、导入模块及19项私有资源；解压使用确切Portable自己的python.exe -I。门禁增至722必需lane、58双侧驱动，原版十八组1237断言不变；037及038须新干净完整候选通过后才能签收。

这里的Ready已经由worker发出，只是transport交付延迟，不能称为发出Ready前死亡，也不覆盖所有竞争时序、完整model/profile、八项原始engine/parse差异或完整C2。JS036仍running，九项Source bug判据及C58/C59不变，accepted_upstream仍为空，真实Win7仍延期。整批pytest预算2400秒是单独公开的容量调整，各消费者期限与判据不变；3be2afde旧超时候选继续拒绝。

实际Ready配对、既有私有引擎/宿主/session/workflow消费者和全部门禁拒绝测试的770项定向回归通过（272.14秒），原始日志/XML为 `.goose/out/acp-a4-work/js-ready-focused-v1.*`。此时尚未运行新干净完整门禁，不据此推进integrated。
