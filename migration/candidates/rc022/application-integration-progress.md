# 应用提供方与组合接入

固定目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。本页记录定向检查；生产 pin 和 `accepted_upstream` 尚未提升。

| 单元 | 已验证边界 | 记录 |
| --- | --- | --- |
| C8-A | 带类型的上传回执、已存图片准入、混合图片预算和取消/卸载 | [上传](upload-checks.json) |
| C8-B | 工作目录状态、串行变更、丢失恢复、系统提示词和卸载等待 | [工作目录](working-directory-checks.json) |
| C8-C | 由 volatile 配置推导表单、密钥默认值清除与表达式保留 | [设置表单](settings-schema-checks.json) |

后续继续设置及完整应用组合；最终资格使用 C9 冻结候选的完整门禁。
