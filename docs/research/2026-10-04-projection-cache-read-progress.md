# B1 投影缓存冷读与 prepared 回放

固定原版 cd5ef8148158c3a752a658978873241fdf8e2bbc。在 subprocess 干净门禁期间于隔离树运行三份未修改原版 storage-domain/domain、invariant 与 projection-cache/cache spec，46 项断言通过；这是原版基线，不认证全部 Native domain/cache。

实际源/Native 同场景 JSON per-record domain、SessionProjectionRegistry 和 SessionProjectionCache 驱动发现冷读行为不同：原版 coldSnapshot 直接传播 schema parse TypeError、不调用 apply、不覆写畸形记录；Native cold_snapshot 捕获 TypeError 后从完整日志重放并覆写缓存，返回成功。这是迁移问题，不是上游 bug 例外。四组首次对照和失败 Native 记录保存在协调树 `.goose/out/acp-a4-work/cache-failure-*-v1*`。首次 Native 观察器还误用了 Session(events=...) 构造，随后纠正为实际 Session.create，单独记录；不把观察器错误当产品失败。

移除 Native cold_snapshot 的 catch/replay；hydrate_prepared 保留原版明确要求的 malformed cache fallback。八组 fresh 原始对照完整一致：畸形冷读拒绝及同一 parser failure 身份、不回放不写入；prepared 回放但不写缓存；matching row 只应用尾部且刷新 cut；createdAt/cwd 不同、版本不匹配、超出日志尾、空 rows 都完整回放并写回绑定当前身份的新 checkpoint。TypeError parser 是两侧明示的 executable schema seam；domain、JSON文件、Session、registry/cache本身均为实际实现。消息、异常身份、apply seq、snapshot、完整 durable document 不模糊规范化。

隔离定向 Source/observer/既有 registry/cache 48 项通过；推广主树后包含 current gate 的 279 项定向回归、fresh paired 8 和三份未修改原版 source 46 全部通过。当前门禁接入第九组 source（总计834项原版断言）、第37个 paired 驱动、第93条必需 lane，以及实际解压 embedded Python 3.8.10 的八组读取和完整 root/module 校验；20组新增门禁反例拒绝缺失、跳过、重复、隐藏冷读错误、prepared误写及异源运行时。还需要新的干净产品候选完整验收。

进程树候选97a4844b全量5765 passed、1 failed、6 skipped、1 warning；失败是host放置的原版浏览器导出包升级旅程，17项业务步骤通过但两条启动fetch错误。原始JSON和NetLog已保存；独立实际解压本候选全部旧观察及四条物理树、原版浏览器通过，但不能抵消全量失败。未签收97a4844b，也未签收本缓存产品；原版bug索引保持九项，accepted_upstream为空。

不得据八组认证全部 domain、FTS/长期历史、压缩JSONL/SQLite、Web listing及完整 profile 主链；MIG-SESSION-REPLAY-002 父范围仍开放。
消费端审查确认 canonical `dsh/api/session_list.py` 经 `sessionQuery.observeSession(projectionMode=all)` 读取并释放 prepared observation，与当前原版相同入口。`dsh/session/listing.py` 由退休 ApiProxy 使用，不作为当前 Web parity 证据，也不因其旧实现调用 cold_snapshot 而恢复旧 carrier。当前四/八组 provider 修复不认证整个 Web listing。
