# 规范 SQLite 提供端推进

独立 schema-19 格式已在干净产品 `0edcc616613eb95f35d5ff27abe5d76591de23b1` 完整验收，台账提交为 `15b119157f1f279980de0e708600ebf85c5323b5`。本次规范提供端位于 `persistence_sqlite_canonical.py`、`sqlite_store.py`、`sqlite_schema.py`、`sqlite_sql.py` 和 `sqlite_logical.py`；正式 registry 和 `dsh.session` 公共导出均指向它。旧 `persistence_sqlite.py` 仅保留明确导入的历史适配边界，不作为产品回退，不静默转换旧库。

原版的 36 个 SQL 资源逐字节复制，清单与每项内容均闭合校验；`-text` 保存 Git/Portable 字节。插件声明 sessions 注入和原版 Config，初始化仅验证路径，一次共享 open reservation 在首次使用时打开私有 SQLite 3.51.2。读事务获取 detached physical rows，写事务重新检查 application/schema 所有权；schema19、UUID、整数主键、STRICT ANY、65536 新页/4096 既有页、四种 journal、安全/同步设置、来源限定 revision、批次内压缩和陈旧尾段修复均单独实现。

实际双侧矩阵包含 323 项：33 个存储/互读/所有权观察、230 元数据/事件/UUID 向量、22 配置向量、8 个原版及原生真实 Context 冷恢复结果、5 个跨进程锁/胜出尾段结果，以及 25 个逻辑版本/旧事件/seek 拒绝和升级向量。两侧读取对方生成的压缩文件，完整文件身份/store UUID/incarnation/revision 必须相等。inspect 对损坏尾段只在内存平衡；load 提交恢复并改变 revision；新 Context 准备保留不属于 durable prefix 的 unpublished end-seed。

新增逻辑对照抓出了未来/较老版本被 `SessionHeader.from_dict` 过早拒绝的问题。规范提供端改用已由物理 schema 验证的原始元数据，随后执行原版方向明确的版本拒绝；列举元数据仍能显示未来版本。保留初始不匹配，不改变原版实现、断言或增加例外。一个 journal 测试最初把全局 time.monotonic 替换成有限序列，干扰了 asyncio 时钟；改为只注入 schema 模块自己的 clock 对象，完整失败和后续观察均留存。

实际 canonical JSONL/SQLite 模型/profile 流程执行五个 Session 工具后冷恢复；另外三个 Web preset 经真实 Remote、本地模型、fork、查询和新 Context 重启通过。未提交的 Portable 预览中，298 项初始提供端矩阵也在真实 Python3.8.10、限制环境和互读数据库中通过；它是开发验证，不能签收最终产品。最终 323 项与来源模块/资源闭包须重新在提交后的完整冻结门禁和实际解压包核验。

原样资源边界与 property differential 套件通过 4 项断言。完整原版 SQLite 研究套件的符号链接 EPERM、两个 POSIX 跳过和缺少原版 lib 的 built-package 跳过仍如实保留；未修改权限、增加新 skip 或称整套通过。当前冻结门禁扩展到 358 必需 lane、十六组 1128 原版断言、52 双侧驱动；完整冻结候选尚待执行。

完整 malformed/public extension ABI、任意竞争与多工作区/长历史、压缩 JSONL、所有 UI/reconnect/profile 组合、OAuth/云端、通用 JS/plugin/package/trust、fresh uncached bootstrap/remote Actions 与整体迁移仍开放。历史启动取消、Source 固定等待 cache、Proactor warning 和外部目录持有者也未因本次通过而归因。accepted_upstream 为空，Win7 真机按用户决定延期。
