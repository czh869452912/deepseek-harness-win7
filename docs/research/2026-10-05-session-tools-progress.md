# 可选 Session 工具推进

目标仍是 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。前一 Unicode/文本候选 `fc275a66` 已通过完整冻结门禁，签收记录提交为 `c756bbff`。本项单独提供原版 `@deepseek-ai/dsh-tool-session-query` 的五个可选工具；原版 README 明确不默认挂载，故没有修改默认 profile。

实际原版两套工具与 SQLite 集成套件 102 项断言通过。78 组实际原版/原生观察覆盖注册、schema、prompt、literal query、calendar/submillisecond bounds、受控授权/分页/谱系/事件读写呈现、十八种服务错误映射及取消优先。共享 Tools 的 `ToolArgsError` 消息前缀曾与原版不符；已修正规范提供端，并用实际原版参数拒绝及原生回归验证，未用单个插件包装绕过差异。

两种真实持久化的规范 profile 已完成模型依次调用五个工具、结果进入下一次模型请求、flush/shutdown 与新 Context 冷读取，工作区外记录没有进入模型结果。补充完整可撤销注册、2500 层谱系裁剪、标题观察重授权及合作式搜索 deadline 等回归。观察器首轮回执写入曾因局部 `provider` 名称遮蔽模块而失败；随后对照又发现原版观察行持有可变 section 数组，在配置探针后污染历史注册行，已改为观察时捕获数组快照；两次诊断原始输出保留在 `.goose/out/acp-a4-work`，未修改原版实现或判据。

独立实现提交 `ae2c1abee258d219f8b90284cd2efd8191bd99e5` 已完成冻结验收：6657 passed、6 既有平台 skipped、1 既有 Proactor warning、0 failed/errors；312 必需 lane、十四组 1082 原版断言、50 双侧驱动、实际解压 Python 3.8.10 与原版浏览器全部通过。解压观察相同 78 组结果并验证新鲜原版摘要及七个提供模块 SHA。39 份有界任务验收与诊断归档于 `migration/evidence/artifacts/SESSION-TOOLS-20261005-ae2c1abe.zip`；见 `migration/reviews/SESSION-TOOLS-CLOSURE-20261005.md`。完整 malformed/plugin ABI、schema-19、竞争/长历史、B/C/D、未知启动取消和整体迁移继续开放，`accepted_upstream` 仍为空；实机 Win7 延期不变。
