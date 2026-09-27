# P1：公开 Agent 工厂事务闭包

目标上游不变。验收边界为 `CON-AGENT-FACTORY@1` 的公开 create/resume；不把官方四套件的 100 项执行结果等同于 100 项 Python 对齐。

最初三个 Python 失败观察确认：恢复在 setup 之前发布 session、setup 拒绝仍发出创建事件、Registry 丢失取消 signal。修复同时涉及 Registry 的 caller Context、Factory transaction、持久化 preparation 以及 Web create/workspace/fork 消费者。Web 不再先发布 session 再尝试创建 agent，也不再吞掉 factory 错误。

一个 preparation 对应一个准确的 Session 实例。setup 与 commit 成功后才进入两侧 registry，然后依次发送 session/created、agent/created、agent/session-start。调用者取消、owner 卸载、factory 卸载都能结束 load/setup 等待；迟到 preparation 仅释放，不再发布。销毁幂等并撤销 owner effect，同 ID 后续实例不会被旧事务清理。

Python observer Task 取消与业务 AbortSignal 分开：取消观察者不会强行取消持久化 provider 的异步操作；其迟到结果仍被消费和释放。Python 的异步 commit 回调兼容保留，并经过同一取消检查。

验证入口：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_agent_factory_transactions.py
.venv\Scripts\python.exe scripts/agent_factory_oracle.py
node --expose-internals scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.agent-lifecycle.config.mts
```

16 项本地边界探针；9 个 TS/Python 双侧场景直接比较事件顺序、发布前可见性、准确实例、释放次数、commit 次数和销毁后的 registry。场景覆盖成功、setup 拒绝、commit 拒绝，以及 caller/owner/factory 在 load/setup 两阶段取消。其余本地探针覆盖 observer 取消、seed/parent owner、同步 setup 中取消、并发 ID 竞争、effect 退休、ID 复用以及 Web 消费者共同发布。

四个原样上游套件为 resume、scope-lifecycle、config-session-id、agent，共 100 项。Windows 官方 JSONL runner 需要上游锁定的 `koffi@3.1.1`；依赖已加入开发 lockfile，不进入 Python portable。

后续仍需单独验证：配置驱动的启动/重载与 draining 身份、完整 Session replay/recovery、运行中 LLM/tool 的取消和所有 Web Gateway 消费者。它们分别进入 Profile、Session、Wire/Tools、Web 批次，不由当前公共工厂证据自动认证。
