# 压缩事务不变量迁移进展

日期：2026-10-01。产品基线 `05c6c1fa`；固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。运行环境为当前 Windows、
原生 Python 3.8.10。本文记录 companion 实施及其验证，不认证全部压缩、
全项目、实际浏览器交互或 Win7。

## 实施

`dsh/compaction/invariant.py` 移植原版 compaction 的跨事件不变量：

- 开始、摘要和结束必须有非空事务身份，保持可选 sourceCommandId 一致。
- 独立压缩只能位于回合之间；带编号的压缩必须属于当前回合。未关闭的事务
  不可跨越 turn/start 或 turn/end，也不可开始嵌套事务。
- 每个成功事务恰有一份摘要。摘要的 shadowedSeqs 非空，首尾与 shadowedRange
  一致；shadowedTokenCount 是非负 JS safe integer，布尔值不作为整数接受。
- 只有替换表面且来源为 plugin/compact 的 user/message 才检查压缩检查点身份。
  普通消息和其他插件的替换不会被误判。检查点必须关联当前事务和发起命令。
- 缺少 error 的结束是成功；显式 JSON null 仍是存在的 error 字段，与原版
  undefined 判断一致。错误信息区分 undefined、null 和数字，不采用 Python None 文本。
- 加载时重建已存在 Session 的轨迹。end-seed 清理继承的未闭合事务；仅当后续
  end-seed 确认该开始仍是 orphan 时，才允许此前的继承修复回合边界。已经关闭
  却跨回合的非法历史仍在安装时拒绝。

internal/dispatch 校验只暂存候选转换，session/event 发布时才提交。后续监听器
否决开始、摘要、结束、回合边界或检查点时，日志、表面代次和已提交校验轨迹
不提前推进；合法重试可以继续。Session 按对象身份隔离，不能因为 durable id
相同而共享轨迹。

Session 轨迹使用 WeakKeyDictionary；原生 append 的 FrozenDict 候选新增 weakref
支持，按弱身份暂存，避免失败候选长期留在 companion。FrozenDict 的 JSON、不可变、
复制和序列化行为保留。SurfaceManager 仍按既有契约缓存一个待验证候选；测试证明
多次否决不累积候选，下一次提交之后最后一个候选也释放。显式 emit 的普通 Python
dict 不能直接 weakref，使用事件身份保留到发布或卸载；它不是原生 append 的路径。

原版另三个 companion 没有独立跨事件状态。本轮只移植其包归属登记与可逆释放：
compaction-basic、command-compact、compaction-tool-result-pruner。四个 `/invariant`
入口均进入安装自带解析表，并通过真实 Loader 装载和卸载。installer 的 sessions
依赖按原版独立注入；先存在 invariants、后提供 sessions 的场景能够完成激活。
未更改原版 profile 来强制启用这些诊断 companion。

## 验证

共享输入为 `scripts/oracles/compaction-invariant-cases.json`，57 个场景。
TypeScript producer 装载固定原版 SessionStore、InvariantRegistry 和原版 companion；
Python producer 装载真实原生对应实现。比较每次接受/拒绝、完整错误消息和 code、
拒绝前后的日志/表面原子性，以及最终完整事件 payload、序号、表面节点和代次。
仅排除时钟字段；没有排除 identity、accounting、错误或替换来源差异。

```powershell
.venv\Scripts\python.exe scripts/compaction_oracle.py --output .goose/out/compaction-invariant-paired.json
```

新增 **57/57 匹配**。连同先前配置、策略、事务和命令场景，累计 **104 个场景：
102 matched、2 reviewed-upstream-bug**。两处已有原版 bug 仍以固定 SHA、完整配方和
完整输出签名审核，不扩大差异豁免。本轮未发现可复现的新原版 bug。

原版断言：

```powershell
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.compaction.config.mts
```

**197 passed，12 个文件**。这建立原版行为基线，不能将其计为 197 个 Python 对齐测试。

Python 专项：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_compaction_invariant.py tests/test_command_compact.py tests/1to1/core/session/test_invariant.py -q
```

**98 passed，14.78 秒**。其中包括 Loader 生命周期、全局归属、卸载/重载、相同 id
不同 Session、依赖延迟提供，以及弱引用释放。三个正式 Web profile 预设 standard、
ptc、cordis 的手动命令压缩和冷启动读取测试显式安装诊断 companion，执行真实原生
压缩后 flush，排空 projection cache，再关闭和重启；不将其描述为浏览器或真实付费
远程模型验证。

首轮完整回归 **1 failed、4002 passed、2 skipped、1 warning，318.36 秒，退出码 1**。
失败为既有 `test_extension_request_idle_watchdog_tracks_partial_wire_activity` 的
250ms 本机 HTTP 空闲时序超时；单独复查 **1 passed，2.02 秒**。未因此修改生产
超时策略或降低该断言。失败日志与 JUnit 保留在
`.goose/out/compaction-invariant-final.log` 与 `.goose/out/compaction-invariant-final.xml`。
同一实现完整复跑 **4003 passed、2 skipped、1 warning，317.99 秒，退出码 0**。
JUnit 共 4005 项，failures/errors 均为 0，时间 317.914 秒；完整日志和 JUnit 为
`.goose/out/compaction-invariant-reviewed.log` 与 `.goose/out/compaction-invariant-reviewed.xml`。
warning 是既有 WebServer 注入行测试的 Windows Proactor transport 在已关闭事件循环
上的析构诊断；pytest-asyncio 默认 fixture loop scope 提示也保留。未以通过的复跑
抹去首轮失败，也未宣称解决了 HTTP 250ms 时序敏感性或零警告通过。
Python 3.8 compileall、七个变更 Python 文件的 3.8 AST 解析已通过；固定 reference
无修改。migration check/ready 只验证迁移记录，不认证全项目完成。

## 剩余迁移与交付

压缩错误链持久化仍需对齐：原版 region.ts 使用 errorChain(error)，Python transaction
当前使用 str(error)。完整取消/maintenance/关闭顺序、client 历史展示和浏览器联合
旅程也须继续审计。通用原版 JS Workflow、动态 JS Host、Inspect、其他未验收模块
及最终发行验证仍在完整目标内，不以本次 companion 收窄完成条件。

继续采用 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)
和 [本地交付实施](2026-09-30-python-plugin-local-delivery.md) 的方案：固定 Python
3.8.10 Portable，本体与第三方 Python Host 插件共享 profile/Loader 装配，本地目录和
ZIP 已实现，专用前端按需携带预构建 client。创造模式源码导出、升级/回退、离线
锁定依赖闭包及 client 联合验证、GitHub Release/npm/PyPI 获取归一化仍需实施。
本轮未新增生产依赖、QuickJS、Node Host 或浏览器源码变更；未重建或发布 Portable。
Win7 实机及目标浏览器验证保留用户暂缓状态。
