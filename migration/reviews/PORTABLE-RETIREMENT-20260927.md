# 旧发行物退役

按用户明确指令删除旧发行物，不保留失效启动入口作为技术债。
自动审批两次拒绝删除，用户已在资源管理器完成操作；随后 Test-Path 确认以下均不存在：

- dist/dsh-win7-portable
- dist/dsh-win7-portable-v0.1.0.zip

这些是 Git 忽略的构建产物，因此提交记录清理决策与验证，不伪造 Git 文件删除。
根目录 canonical 启动器保留；源码 CLI 的合法兼容参数不属于本次过期产物。
未修改 portable smoke 的断言：没有构建产物时按原有规则 skip。
这解决旧产物导致的基线失败，但不等于新 portable 或 Win7 已验收。
