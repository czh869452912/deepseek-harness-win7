# JavaScript工作流提前退出分类

干净修复产品 `b1b2f7971d904cce7047e7b679f9faf658383e85` 完整门禁通过：7087通过、6既有skip、1既有Proactor warning、0失败，1769.53秒；639必需lane、十八组1237原样Source断言、56实际配对、真实解压及原版浏览器均通过。Source/native/extracted的34组宿主完整观察digest相同；此前30组直接worker帧场景继续通过，物理死亡控制位于真实WorkerRun/Native宿主层。46既有合同重验，036仍running且只保留部分verification。下文保留问题发现与实施历史。

前一干净门禁产品 `17c1c521` 已通过7077项、629必需lane、十八组1237原样Source断言、56实际配对及真实解压/原版浏览器，记录提交 `211e80c9`。036完整合同仍running，本部分不重签全项目或消除此前八项engine/parse差异。

实际固定Source WorkerRun与真实Native WorkflowEngine在provider已进入但尚未返回时，均由holder物理结束各自真实worker；退出码均为1。Source结果为 `workflow worker exited before the run settled (exit code 1)`，Native误报 `workflow worker failed: JavaScript worker exited without a terminal result`。完整原始结果/事件保留于 `.goose/out/acp-a4-work/js-death-{source,native}-v1.json`；共同abort、迟到child的一次disposal和首个计数均匹配，只有提前退出分类不同。Source通过此前冻结门禁保存的真实host/worker bundle执行，未改Source算法或注入伪terminal。

根因是私有提供端把stdout EOF后的缺失terminal与协议解析错误放在同一个普通RuntimeError中；宿主无法区分实际退出和执行/协议失败。提供端现在以 `WORKER_EXIT` typed error保留真实退出码，宿主通过动态提供端错误码选择原版exit表述；协议异常仍按原有failure路径拒绝。缺失terminal依旧使低层future失败，不会伪造完成或挂起。Source pin、私有EXE/算法/许可资源和所有九项例外判据不变。

真实Source/native配对从30扩为34：provider发布前退出、已发布且结果未定的child退出、首个Result后退出、先取消再退出。双方使用实际provider/agent-start/disposal边界控制，检查全部result/events/requests、真实退出码、首个结果对象保留、signal和一次disposal。低层另有真实kill与畸形协议两项拒绝回归，确保退出分类不掩盖协议故障。worker/host/提供端/消费者共113项通过；独立CLI34项完整观察匹配，digest为 `4691424bcf754e599e6fae0cef6a90c4b6b4b6dc1bf2c92ea875e43af9fa7971`。598项门禁定向回归全部通过，639必需lane；迟到log篡改测试仍明确检查dropped-child-continuation，避免新增末尾场景改变测试含义。

下一步冻结新干净候选，执行全部Python3.8.10测试、原版断言、配对、实际解压和原版浏览器验收。这里只修复已观察的启动之后物理退出；ready之前退出/发布竞争、晚到provider与共享disposal的更多重入、完整model/profile及八项原始差异继续开放。没有提升超时、新增skip、豁免、付费调用或重跑不变候选；Win7继续延期。

验收归档 `migration/evidence/artifacts/JS-DEATH-20261005-b1b2f797.zip` SHA256为 `b362bfd251c30eff466f3f17b6cd8a3dea4bb6fdf46d0309a6125f3b00ac9f73`，精确Portable SHA256为 `6b193c4e0a4f246cd8962cada830b57999b5f7f1a7ce8ff4a461e26ce8e8ace2`，冻结输入SHA256为 `0c2150bb8675cf0acbf402dc7779c7b4df8aa7bb19cad70e5fe4f3093c631e0d`。归档CRC、每个回执和内嵌原包均核验；旧17c1c521归档保持独立原哈希。归档器第一版替换前缀时误指不存在的旧JS-DEATH包，在复制/新建归档/写入证据前失败；只修正旧包路径至原JS-WORKFLOW归档，记录保留，没有重跑已通过门禁或重建候选。实际提前退出原始差异、相关113项/598项定向日志/XML和全部Source/native/extracted观察均保留。

下一步执行已准备的原版两阶段主链实验：真实AgentLoop与spawn子代理、普通文本再结构化工具、未捕获结构化输出映射null、实际子会话发布与清理；模型边界保持无凭据可控。本次成功仍不归因1175/启动取消/Proactor/HTTP10054，也不签收完整Node/SDK/插件和全部迁移。
