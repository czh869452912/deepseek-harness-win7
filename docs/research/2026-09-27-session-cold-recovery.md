# JSONL 冷恢复闭包

固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。本次优先修复配置恢复所依赖的真实持久化路径；公共 Agent factory 已通过并不意味着磁盘恢复可靠。

## 已复现的问题

旧 JSONL 只生成一个带当前时间及额外 session_id 的 turn/end，未使用已移植的完整 interrupted_turn_closers。未完成工具缺少结果，step 没有结束。扫描器把坏行也算入 committed_bytes，load 又没有先截断半行；首次返回看似成功，第二次读取却可报 committed corruption。read_from 实际调用 inspect，返回了合成修复事件或未落盘 live 事件。格式判断还错误地允许 v1，而固定上游只读 v0。

## 修复与验证边界

- 接通核心 repair：工具未开始/结果未知、sourceEventSeqs、step/end、turn/end，使用最后真实事件的时间。
- 扫描器仅在完整且连续的合法记录后推进字节边界，跨块输入保持精确偏移。坏行之后若发现 turn/end，拒绝作为已提交损坏处理。
- 冷 load 先验证身份，再截断尾部并 fsync，再追加修复事件；重复打开不再产生新事件。
- inspect 不修改磁盘；read_from 只读物理记录并验证非负安全整数；live open turn 不允许走冷修复。
- 七组 fixture 在上游真实 Context/SessionStore/JSONL 与 Python 后端双侧执行，逐字段比较 inspect、readFrom、load、再次 load 和磁盘只读性，不删除时间或错误字段来促成匹配。
- 两个上游原样测试文件共 164 项；它们验证基准可运行，不能当成本地 164 项对齐证明。

## 下一闭包

MIG-SESSION-REPLAY-002 仍为 draft：共享 preparation 的 observer/cancel/cache/reservation、每 ID 写入序列及失败后 pending 保留、持久化插件卸载 flush/retirement/HMR adoption、Session 全量投影尚未认证。配置启动的 restore-or-create、缺失与损坏区分、旧身份 draining、reload 需要与这些提供端一并修复。不得以本次冷恢复完成解除整个 Web/配置层依赖。

Win7 真机验证继续按用户要求暂缓。没有创建上游整体 accepted 标记。
