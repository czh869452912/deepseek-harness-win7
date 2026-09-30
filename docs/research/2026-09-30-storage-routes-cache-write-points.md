# Storage 路由依赖与缓存写入时刻对齐

日期：2026-09-30。产品基线：`73242f88`；固定上游：`cd5ef8148158c3a752a658978873241fdf8e2bbc`。
本文对应基线之后的 Python 修复，承接 [Host 发布与关闭修复记录](2026-09-30-python-host-release-decisions.md)。

## 实际修复

### 按配置注入 backend

原版 `reference/packages/storage/storage-domain/src/index.ts` 的外层插件只注入 `storage`；内层按 `backend` 和 `routes` 的去重集合等待 `storageBackend:<name>` 服务。facility 的挂载、domain 的排空和服务提供都归属该内层 fiber。

旧 Python 插件固定依赖 `storageBackend:json`。这使不使用 JSON 的组合无法激活，也使配置中的其他 provider 退出时不能正确撤销 facility。现在使用同样的两层注入和 Schemastery 配置，要求显式字符串 backend，routes 缺省为空；所有配置 provider 到齐后挂载，相关 provider 退出后排空并卸载，重新出现时创建新 facility。无关 JSON provider 不控制非 JSON facility。

回归通过真实插件注册和两个独立 JSON 介质目录验证按名字路由，不依赖固定内置包映射。provider 的装配和撤销仍通过 Context 服务与可逆 effect 完成。

### 缓存检查点在调用时捕获

原版 `SessionProjectionCache.write` 的 JS async 函数在调用时同步读取 checkpoint、重置脏计数，再等待 Session flush。旧 Python async 函数直到任务开始执行才做这些工作：创建检查点会吸收后续事件，连续事件达到阈值后会重复排队写入，无法保持原版的写入时刻。

现在调用 `write(session)` 即捕获分离状态并重置计数，返回进入事件循环的 Python Task；实际提交仍先等待 Session flush，再写入 domain。Task 在调用时排队，避免直接 await 的新写入超过此前 fire-and-forget 的创建写入。现有 await 调用方式保留；需要再调度返回对象的调用者使用 `asyncio.ensure_future`，而不是要求参数必须是 coroutine 的 `create_task`。

专项验证创建、显式调用、连续事件阈值、延迟 flush 屏障和独立 cache 插件卸载。六个连续事件、阈值三的实际 domain 变更为：

```json
[{"ver":1,"seq":2,"val":3},{"ver":1,"seq":5,"val":6}]
```

### 非 JSON 状态不再伪装成 null

旧 registry checkpoint 调用 `snapshot_json_value` 时，非法状态和合法 null 都可能得到 `None`，使 cache 把非法状态作为 null 持久化。

现在通过该现有 API 的 default sentinel 区分失败；合法 JSON 仍走不依赖 Python 递归栈的原有分离路径，非法状态保留为分离副本，交给 cache 的 lossless JSON 边界拒绝。Set 的双侧观察验证拒绝、旧磁盘记录不被污染和移除非法投影后的下一次写入恢复。Python deepcopy 的非法状态分支不声称实现所有 JS structuredClone 的扩展类型；本轮观察只覆盖这个拒绝场景。

上述均是迁移版偏差。原版已有对应逻辑，本轮没有确认新的原版 bug。

## 关闭警告的边界

原版 cache 的 `installWritePath` 和 `flushSoft` 明确说明：domain 关闭排空已入队写入；尚在等待 flush 的晚到写入可能收到 `closed`，记录警告并保持缓存陈旧。这是可重建缓存的 fail-soft 约定，不能仅凭该诊断推断原版存在 bug，也不能通过静默吞掉错误声称修复。

迁移版 cache 自己的卸载仍会等待其调度任务，再关闭 domain，回归验证延迟 flush 后的检查点可重新打开。整个 Host 同时关闭 storage/provider 和 cache 时仍可能有晚到写入失败；本轮没有改变 Cordis 核心并发卸载语义或引入跨插件关闭顺序。

Windows Proactor transport 析构诊断属于另一问题，不能混同为 checkpoint 写入失败。本轮全量仍观察到该既有 warning，未认证关闭完全无警告。

## 验证证据

以下命令均退出码 0：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_storage_domain_routes.py tests/test_projection_cache_write_points.py tests/test_storage_domain_lifecycle.py tests/test_projection_cache_durability.py tests/test_storage_and_workspace.py tests/test_session_projection_registry.py tests/test_cordis_injection_service_upstream_parity.py -q
node --expose-internals scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.storage-cache.config.mts
.venv\Scripts\python.exe scripts/storage_cache_oracle.py
.venv\Scripts\python.exe scripts/session_projection_oracle.py --output .goose/out/storage-cache-projection-regression.json
.venv\Scripts\python.exe -m pytest tests --junitxml=.venv/storage-cache-suite.xml
.venv\Scripts\python.exe scripts/migration.py check
.venv\Scripts\python.exe scripts/migration.py ready
```

| 验证 | 实际结果与范围 |
| --- | --- |
| Python 专项 | 58 passed，包含本次 10 个新增测试及既有相关消费者。 |
| 原样原版断言 | 3 个文件、46 passed；domain、domain invariant 和 cache 源码测试。仅证明原版基准通过，不当作 46 个 Python parity 场景。 |
| 本次双侧运行 | routing、call-cut、threshold、non-json 四组真实源码/介质观察全部 matched。字段包括 provider 激活门槛、路由持久值/重开值、捕获水位和状态、实际写入次数/顺序、非法状态拒绝与恢复。 |
| Registry 既有双侧回归 | 九组观察全部 matched，防止 checkpoint 提供端改动破坏已有 registry 范围。 |
| 全量 Python 回归 | 3647 passed、2 skipped、1 warning，311.69 秒。Python 3.8.10，当前 Windows；既有 Proactor warning、pytest-asyncio 默认 loop scope 提示及测试 HTTP 连接中止诊断保留。 |
| 迁移记录 | check 通过；ready 退出码 0，无就绪任务输出。它们不认证全项目 parity。 |

本地原始产物：`.goose/out/storage-cache-paired.json`、对应 `.ts.json` / `.python.json` 和 `.0.log` / `.1.log`；registry 回归使用 `storage-cache-projection-regression` 同名组；全量 JUnit 为 `.venv/storage-cache-suite.xml`。这些本地忽略目录产物可由提交的 runner 复现，不是新增、绑定候选提交及输入哈希的正式 migration acceptance。

未修改原版 Web、未新增运行时依赖。原版执行器使用 Node 仅作为开发验证工具。本轮没有执行 Win7 真机、真实远程模型长运行、重新构建 Portable、第三方 ZIP 安装或 Workflow 完整执行验收。完整迁移目标和这些验收项继续保留。
