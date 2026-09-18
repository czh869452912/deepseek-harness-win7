# Goose 迁移效率检查（2026-09-18）

本次为只读诊断：核对 SQLite 任务库、阶段结果、progress.jsonl、当前控制器和角色提示。未恢复 worker，未修改任务状态、模型配置或迁移代码。任务库使用 SQLite mode=ro 读取。

## 当前状态

- scheduler=PAUSED；检查时未发现 goose.exe 或 project_runner.py run 进程。
- 最近任务事件为北京时间 2026-09-14 23:33:14；不是最近几天持续运行却没有产出。
- 289 条任务记录：READY 238，NEEDS_REVALIDATION 49，INTEGRATED 2。READY 不代表依赖均已满足；多条记录共享历史运行，不能简单相加轮数，也不能据此计算代码完成率。
- vendor/cosmokit：INTEGRATED，记录为第 21 轮。
- vendor/timer：INTEGRATED，第 7 轮，2026-09-14 23:21:33 完成集成。
- vendor/cordis：曾在第 11 轮通过，并随 dc0e0a19 发布；当前又为 READY，round=0，新运行目录时间为 2026-09-14 23:21:33。
- publication 与 pilot 元数据仍为 PUBLISHED，head=dc0e0a19。Timer 后续集成不能等同于已发布 master。
- 当前配置与 Timer 的 14 份阶段配置均为 deepseek-flash / gpt-5.6-luna / gpt-5.6-sol。配置只能证明请求的模型别名，不能独立证明代理后端对应的具体 DeepSeek 版本。

## 最有解释力的样本：Timer

运行目录：`.goose/runs/project/worktrees/57bfff223336/.goose/runs/20260914-202340-4951b57d/`。

从 20:23:41 开始到 23:21:33 集成，约 177.9 分钟。根据 progress.jsonl 配对同轮同阶段的 start/result：

| 阶段 | 累计分钟 |
|---|---:|
| migrate（包含阶段内读码、探测和测试） | 89.62 |
| review（包含阶段内读码、探测和测试） | 76.18 |
| 控制器 targeted | 2.27 |
| 控制器 compile | 0.01 |

其余约 9.8 分钟包括计划处理、集成门禁和阶段切换；不能把模型阶段时间全部称为纯推理时间。共 7 次 migrate、7 次 review，没有 judge 结果或 judge 启动记录。上游 Timer 主文件仅 147 行，但候选涉及 Context、Reflect、Service、Loader、HMR 和测试，实际不是孤立翻译 147 行。

## 已确认的主要原因

### 1. 重复问题识别失败，仲裁配置并没有保证仲裁参与

`.goose/project_runner.py:22` 的 repeated_issues 依赖模型生成的 issue ID：以 # 分隔路径和案例，要求路径相同且案例字符串相似度至少 0.8；只对比上一轮的开放问题。

Timer 第 1 轮和第 2 轮都指出服务被 Context 提前创建、生命周期未归属插件，但 ID 从 `reference/...:12-16::service-lifecycle-ownership` 变成 `vendor/...#plugin-owned-registration-lifecycle`。用当前函数重放这两个真实报告，返回 False；7 轮之间全部 6 次相邻比较均返回 False。

回调异常语义在第 1 轮是 open，第 3 轮变成 informational adaptation，第 4 轮又变成 open；第 5 轮进一步指出去掉 catch 后错误地停止 interval。模型之间需要裁定的适配边界没有被稳定升级到 Sol。已解决/降级后再出现的问题也不在当前相邻开放问题比较范围内。

### 2. 每轮重新全量盲审，缺少稳定的验收事实和裁决记忆

`.goose/project_runner.py:520` 每轮调用 review，不传上一轮反馈；`.goose/parity_runner.py:583` 明确排除向普通 reviewer 传 feedback。角色提示要求重建源码和测试映射，禁止参考历史结论。

这保证了独立性，但也使每轮重新发现边界、重复查消费者，并允许适配分类漂移。保留独立首审是有价值的；后续修复验收应使用源码支持的条款、回归测试与已裁定的边界，不能仅靠再做一次无记忆审查来收敛。

### 3. 宽泛契约失效触发已完成核心模块重跑

当前 contract:cordis-runtime 的 paths 包含整个 `dsh/cordis`，包括 timer.py。Store.integrate 按文件变化更新匹配契约，Store.invalidate 把 owner 及传递消费者中的 INTEGRATED/VERIFIED 改为 NEEDS_REVALIDATION。

随后 task_runner 对 NEEDS_REVALIDATION 清空 run_dir 和 round，而 execute 仍从 migrate 开始，没有专门的依赖变化重验路径。Timer 集成之后立即重新领取 Cordis 并创建 round=0 的运行，与这一代码路径一致。即使需要重验，也不应自动把它当成新一轮完整迁移。

### 4. 真实实现缺陷与逐轮补丁同时存在

Timer 真实报告包含零延迟线程回调在 dispose 变量赋值前执行、interval 抛错后不再调度、已 dispose 的无事件循环 timeout 在截止时间之后才 await 时错误地成功返回等可复现问题。不能仅通过放宽 PASS 或删除审查解决。

DeepSeek 修一个现象后未一次覆盖相关状态组合；Luna 也未在第一轮发现完整边界。适配层应该有统一的“创建—触发—异常—取消—晚 await—卸载”行为矩阵，模型按矩阵实现和审查，而不是每轮临时补一个边界案例。

### 5. 部分迁移实际承担了 JS 宿主运行时兼容

Cosmokit 的第 9～17 轮 review 连续 PASS，但 migrator 仍报告或发现语义差异；第 15～17 轮为 INCOMPLETE。第 17 轮 judge 明确要求继续修复 V8 legacy date grammar。因此这些轮次不能全部归为 reviewer 挑刺。

上游 time.ts:60 的 `new Date(date)` 在 Python 中没有直接等价物；日志已深入到 `12:Z0` 等旧式日期字符串、历史时区偏移、负零、undefined、属性键顺序等 JS 行为。此类工作需要明确且共享的运行时兼容契约。严格完整等价若仍是目标，应按独立兼容模块建设和验证，不能按普通工具函数翻译估工。

### 6. 历史基础设施故障放大轮数，部分已经修复

Cosmokit 事件包含 submodule 初始化失败、只读审查生成 `$null` 文件、Windows status.json 替换被拒绝、缺少结构化最终结果、集成测试失败。Cordis 试点文档记录了计划重放、裁决状态错误分流、恢复后 JSON schema 不一致等已修问题。

这些是历史成本，不应一概称为当前仍存在的缺陷；但最近 Timer 的盲审、ID 漂移和宽泛失效问题在当前实现中仍可核实。

## 建议的修改顺序

1. 先修失效和重验：缩小契约路径；保留已验收候选；让依赖变化进入 REVALIDATE，执行受影响测试和必要增量审查，证实失败后才回到 migrate。最终组合候选仍跑全套门禁。
2. 让控制器维护稳定条款/问题 ID 和源码证据账本。相同语义再次失败、分类翻转、已有裁决被否定，应触发 Sol；不能只比较模型自由生成的 ID。裁决要落为条款和回归测试。
3. 首轮独立完整审查，后续审核变更、未决条款和受影响消费者；保留范围扩张规则。避免把迁移模型的自述当证据，但允许复用已核实的事实。
4. 对 timer、Date、undefined/对象键、Promise/asyncio、取消/卸载先建立共享兼容契约。复杂边界由 Sol 早期裁定，Flash 实现，Luna 验证。
5. 达到约 3 轮仍未收敛时切入根因诊断/仲裁，而不是直接失败或强行 PASS；区分“新缺陷”“旧缺陷未修复”“审查反转”“协议修复”“依赖重验”。不要增加一轮轮泛化的全项目规划。
6. 用 Timer 这类小模块评估新流程，记录首审通过率、每轮新增缺陷、重复缺陷、仲裁次数和阶段耗时，再恢复批量迁移。当前证据不足以承诺固定两轮完成或量化模型替换收益。

## 验证说明

已用真实 Timer 报告重放 repeated_issues，6 次相邻比较均未命中。按 AGENTS.md 执行 `.venv/Scripts/python.exe -m pytest tests`，结果为 1816 passed、1 failed、1 warning，耗时 127.15 秒。失败项为 tests/test_portable_smoke.py::test_smoke_dist_portable_directory：本地 portable 目录启动器不识别 `--profile minimal`，与试点记录的旧发行包现象一致。日志位于 `.goose/runs/efficiency-audit-tests.log`。本报告未实施上述调度器修改，未处理发行包问题。
