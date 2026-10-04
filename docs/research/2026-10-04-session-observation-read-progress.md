# B1 Session point read 的错误与租约

固定原版 cd5ef8148158c3a752a658978873241fdf8e2bbc。逐行审查当前 SessionObservationReader，发现 Native 的 not-found、corrupt、borrow/projection failure 与 source-conflict 消息省略了原版身份及原始错误上下文；foreign rejection 被既有 ThrownValueError 语言载体包装后作为 cause 返回，丢失原始值身份。disposed observation 的 retain 错误也省略 Session id。这些是迁移差异，不登记原版 bug。

隔离树实际 reader、SessionStore、SessionProjectionRegistry 驱动得到16组 fresh 原始观察；borrowed source、拒绝和调度顺序是明示的控制 seam，不冒充真实磁盘 persistence。首次 Source/Native 记录分别位于协调树 `.goose/out/acp-a4-work/session-observation-*-v1.json`，修复后 v2 全部一致。live projection failure 的首次探针误用 sessions.create，注册投影因 announce 提前失败；已在两侧改成 actual Session.create + sessions.enter，真正观察借用后胜出的 live projection 拒绝。这个探针问题与产品消息/cause 差异单独记录。

修复 Native 精确消息和 cause 值；错误实例不重新制造，foreign rejection 只剥离已有 ThrownValueError 载体，取消原因仍由 signal 保留。FileNotFoundError 对应原版 SessionPersistenceNotFoundError 的语言类型映射显式保留；generic disposed Error 对应 Python RuntimeError，由两侧 ordinaryError 精确构造类检查，不改写消息。

16组包括 absent provider/record、corrupt/generic/foreign rejection、错误身份、借用前后取消、prepared/live projection failure、prepared/live independently retained cut、借用中发布 live、detached-live retry、projectionMode=none 和实际 registry prepared projection。直接比较 code/name/message、cause/raw failure 身份、cut/revision/投影及 borrow/release/apply 次数。prepared 最后一个租约才释放；winning live projection 失败也只释放一次；live lease 不借用 persistence。

目前 Source/observer/既有真实 JSONL/SQLite observation 初步31项通过，接入新 current gate 后282项定向回归通过；六项未修改原版 observation assertions 通过。扩展门禁新增第94条必需 lane、10组840项原版断言、第38个 paired 驱动和16组实际解压观察，并增加20个门禁拒绝反例。完整 pytest 的临时工件固定放在本次 ignored output/pytest-workspace，便于保留实际浏览器JSON/NetLog，避免全局pytest临时清理丢失验收原始记录。还需在主树独立产品提交及新版完整 clean gate/实际解压 embedded Python 3.8.10 后才集成。此范围不认证整个 query/FTS、durable借用/长期历史、Web listing/profile 或外部模型、JS、Win7。

主树推广后的282项定向回归与fresh16双侧观察也通过。此前a3315a7b完整回归为5806 passed、1 failed、6 skipped、1 warning；安装包浏览器旅程12项业务步骤通过，但rollback新Host启动产生六个取消POST和两条fetch错误，不能签收缓存/此前subprocess共同候选。所有五条必需浏览器原始JSON及可用NetLog已关联运行中的pytest PID/.lock保留到cache-read-clean-a3315a7b/required-browser-raw；失败也保留，工件收集不认证本次门禁。
