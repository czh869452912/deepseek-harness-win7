# 新基线切换保留未完历史状态（C9-CA）

迁移 CLI 之前只允许 `integrated` 任务保留旧目标。直接更换 baseline 会拒绝旧版仍在 `ready/running/review` 的记录，而把这些记录改为 integrated 又会伪造完成状态。

现在允许明确标记 `historical: true` 的旧目标任务保留其原状态、原验收内容和未解决观察。它们不能出现在当前 ready 资格中，不能作为活动写者冲突阻塞新任务，也不能提供当前资格。当前目标禁止使用该标记绕过校验；历史 verified/queued 仍必须有自身原始合格证据，不自动提升或丢弃历史门槛。

36 项迁移工作流检查通过，包含 ready/running/review 状态不变、当前目标拒绝归档、历史 verified 精确证据仍必需，以及既有依赖/证据拒绝回归。自有测试工作区、tmp 和 home 已清理，命令、XML和日志保留。这是切换前记录工具准备，不是生产 pin 或任务验收状态变更。详见[检查回执](../../migration/candidates/rc022/migration-open-history-checks.json)。
