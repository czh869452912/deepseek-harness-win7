# 共享 Session 写入生命周期

固定上游 cd5ef8148158c3a752a658978873241fdf8e2bbc。

本次解决上一闭包实测的两个失败：append 失败导致 pending 丢失，以及插件卸载未排空缓冲。进一步核对发现 JSONL 写入后 fsync 失败会留下重复重试风险，SQLite 没有批次 rollback，因此存储事务与写队列必须一起修复。

SessionWriteBehind 独立实现固定窗口、事件拷贝、同一 flush barrier、active write 期间的尾部 deadline、失败保留及暂停自动重试。Python observer 通过 shield 等待共享任务，不能把调用者取消传播给落盘。

LivePersistence 由 JSONL/SQLite 共用，负责初始化与种子、每 ID 锁、精确 Session owner、退休任务、HMR 前缀接管、最终 drain/close。disposer 先注册，随后注册 listeners，让 Cordis 反序释放时先关闭事件准入。HMR 直接读取物理前缀并验证 cwd/事件一致，只截断坏尾，不走冷修复误关活跃 turn。

SQLite 同时改为 inspect 只读逻辑修复、read_from 物理后缀、load 显式修复，使用共同核心 repair，去掉事件中额外 session_id。SQLite append 使用事务回滚；JSONL append 在失败时截回原字节位置并 fsync，rollback 也失败时保留两个错误。

验证分三层：174 项上游原样 Session 测试只提供源码基准；本地确定性时钟及两个后端生命周期矩阵检验实现；四组真实 JSONL 双侧观察比较 type/seq/data 和冲突拒绝，不比较生成时间与诊断文本。七组冷恢复观察继续逐字段匹配。

尚未认证：完整 persistence 公共 create/append 协调、共享 preparation 缓存/reservation/observer cancellation、跨进程并发物化、完整 schema/SQLite 原样基准、跨代缓存版本协调、配置 sessionId/resumeSessionId、launcher identities 和 Agent reload。现有 live 层没有替代这些契约，不据此将整个 Session 或 Profile 标为完成。
