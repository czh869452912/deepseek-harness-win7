# 规范 SQLite 提供端推进

最新有界签收：干净产品 `1f180e40` 的6892通过/6既有跳过/1既有warning完整门禁成功，444必需lane、十八组1237原样断言、54双侧及实际解压/原版浏览器通过。323项提供端观察、29模块和50资源绑定实际包内运行，031已integrated；见 `migration/reviews/SESSION-STORAGE-CLOSURE-20261005.md`。以下实施与拒绝历史保留；完整ABI/竞争/多工作区/长历史和整体迁移仍开放，Win7延期。

独立 schema-19 格式已在干净产品 `0edcc616613eb95f35d5ff27abe5d76591de23b1` 完整验收，台账提交为 `15b119157f1f279980de0e708600ebf85c5323b5`。本次规范提供端位于 `persistence_sqlite_canonical.py`、`sqlite_store.py`、`sqlite_schema.py`、`sqlite_sql.py` 和 `sqlite_logical.py`；正式 registry 和 `dsh.session` 公共导出均指向它。旧 `persistence_sqlite.py` 仅保留明确导入的历史适配边界，不作为产品回退，不静默转换旧库。

原版的 36 个 SQL 资源逐字节复制，清单与每项内容均闭合校验；`-text` 保存 Git/Portable 字节。插件声明 sessions 注入和原版 Config，初始化仅验证路径，一次共享 open reservation 在首次使用时打开私有 SQLite 3.51.2。读事务获取 detached physical rows，写事务重新检查 application/schema 所有权；schema19、UUID、整数主键、STRICT ANY、65536 新页/4096 既有页、四种 journal、安全/同步设置、来源限定 revision、批次内压缩和陈旧尾段修复均单独实现。

实际双侧矩阵包含 323 项：33 个存储/互读/所有权观察、230 元数据/事件/UUID 向量、22 配置向量、8 个原版及原生真实 Context 冷恢复结果、5 个跨进程锁/胜出尾段结果，以及 25 个逻辑版本/旧事件/seek 拒绝和升级向量。两侧读取对方生成的压缩文件，完整文件身份/store UUID/incarnation/revision 必须相等。inspect 对损坏尾段只在内存平衡；load 提交恢复并改变 revision；新 Context 准备保留不属于 durable prefix 的 unpublished end-seed。

新增逻辑对照抓出了未来/较老版本被 `SessionHeader.from_dict` 过早拒绝的问题。规范提供端改用已由物理 schema 验证的原始元数据，随后执行原版方向明确的版本拒绝；列举元数据仍能显示未来版本。保留初始不匹配，不改变原版实现、断言或增加例外。一个 journal 测试最初把全局 time.monotonic 替换成有限序列，干扰了 asyncio 时钟；改为只注入 schema 模块自己的 clock 对象，完整失败和后续观察均留存。

实际 canonical JSONL/SQLite 模型/profile 流程执行五个 Session 工具后冷恢复；另外三个 Web preset 经真实 Remote、本地模型、fork、查询和新 Context 重启通过。未提交的 Portable 预览中，298 项初始提供端矩阵也在真实 Python3.8.10、限制环境和互读数据库中通过；它是开发验证，不能签收最终产品。最终 323 项与来源模块/资源闭包须重新在提交后的完整冻结门禁和实际解压包核验。

原样资源边界与 property differential 套件通过 4 项断言。完整原版 SQLite 研究套件的符号链接 EPERM、两个 POSIX 跳过和缺少原版 lib 的 built-package 跳过仍如实保留；未修改权限、增加新 skip 或称整套通过。冻结门禁扩展到 358 必需 lane、十六组 1128 原版断言、52 双侧驱动。

产品 `d5cc655471febc74203ab3a6a93c023e5f95fd90` 的首次完整冻结门禁被拒绝：6769 passed、2 failed、6 既有平台 skipped、1 既有 Proactor warning，耗时 1582.36 秒。失败是部分字节流活动的 idle watchdog 和原版浏览器 creative host 升级启动取消；两项均不属于本次 SQLite 专项断言。原版/配对/解压正式阶段尚未执行，不能签收 SQLite 提供端。确切失败包保存在 `.goose/out/sqlite-provider-clean-d5cc6554/candidate-portable.zip`，SHA256 `8a123afd7c216676935ec10f14b3d26aa931d563a0fa1f0469a66dd248af5392`，输入清单 SHA256 `f903faee0ae1d0da5e0f60c63091618c087d158b25cae1659a508156816aa1c3`；同目录 rejection-provenance.json、完整日志和 XML 绑定此失败候选，不重试同一产品、不新增例外或跳过。

浏览器业务的 17 步/9 次 RPC 已完成，但升级页面的五个启动 POST 被 renderer 取消并触发原版错误日志。取消发生于 load 附近，无中间 navigation/context destruction；NetworkService 的 syncInspectManifest 请求实际上收到 200。另一个开启诊断的十次启动循环通过，未复现取消，不能替代失败候选的签收或归因。

流超时另有独立受控复现：真实 HTTP 读取已产生首块，把其异步交付延迟 350ms 时，250ms watchdog 仍错误取消底层 signal。原版 idleWatchdog 在 iterator.next settled 时即停止计时；原生原先直到外层收到块才停止。OwnedStream 的读取完成回调修复这一边界，真实空闲超时、字节活动、取消与消费清理的 54 项定向测试通过。共享 timeout 双侧十项实际观察也通过，settled 后延迟接收的测试仍保留真实阻塞超时和 stable signal 判据。原始失败缺少活动时间戳，不能把这个受控根因直接归为 d5cc 的部分字节流失败原因。

完整 malformed/public extension ABI、任意竞争与多工作区/长历史、压缩 JSONL、所有 UI/reconnect/profile 组合、OAuth/云端、通用 JS/plugin/package/trust、fresh uncached bootstrap/remote Actions 与整体迁移仍开放。历史启动取消、Source 固定等待 cache、Proactor warning 和外部目录持有者也未因本次通过而归因。accepted_upstream 为空，Win7 真机按用户决定延期。
