# C6 子代理与 Team 进度

固定目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。本页仅索引定向合同检查。

| 单元 | 已验证边界 | 记录 |
| --- | --- | --- |
| C6-A | 名称、兄弟预留、路径回退、目录 v0–v3/stateVersion 6 | [名称与目录](named-catalog-checks.json) |
| C6-K | 实际跨分支消息、离线创建者、异步读取后身份复查与容量变更 | [兄弟消息](sibling-messaging-checks.json) |
| C6-J | 公开服务、Provider 注册与替换、实际 spawn/fork 创建和冷恢复 | [公开服务](subagent-service-checks.json) |
| C6-I | 归档活动、停止扇出、模型步准入与可逆注册 | [归档联动](archive-admission-checks.json) |
| C6-H | 统一管理器、实际工厂/存储/查询创建与目标冷恢复 | [统一管理器](subagent-manager-checks.json) |
| C6-G | 子代理 preset 组合、权限快照、结构化输入关闭 | [子代理组合](child-composition-checks.json) |
| C6-F | 中断、共享关闭、驻留释放、待办输入和树关闭等待 | [执行生命周期](subagent-lifetime-checks.json) |
| C6-E | 容量身份、子代理串行锁、执行结果与命名通知 | [执行结果](activation-result-checks.json) |
| C6-D | 精确树成员、创建边验证、冷祖先观察和名称寻址 | [树成员](tree-membership-checks.json) |
| C6-C | 完成状态、身份重置、fork 一次性种子与实际工厂消费者 | [计时与 fork](subagent-timing-checks.json) |
| C6-B | 目录预序遍历、分支诊断、取消、名称路径解析 | [目录读取](catalog-walk-checks.json) |

后续推进创建/恢复、消息投递和中断权限，再对齐 Team、SDK/PTC/Remote 与 fork 种子消费者。基础库通过不代表完整服务或产品装配已通过。生产 pin 和 `accepted_upstream` 保持原状态；共享 Source/工具链保留到 C9，结束运行的可重建工作区已清理。
