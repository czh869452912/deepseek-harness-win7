# Cordis Inspect 注册、查询与原生 Schema 迁移进展

后续默认/显式 null 取消原因与平台事件偏差修复、真实 Tools 融合信号双侧观察见
[取消契约进展](2026-10-01-abort-platform-progress.md)。下文取消边界说明保留为历史范围。

后续工具 prompt/presentation、自检、引用与真实 Python Host 更新旅程的实施见
[Cordis 工具进展](2026-10-01-cordis-tools-progress.md)。下文保留本批次历史范围。

日期：2026-10-01。产品起点 `81377bb3`；固定参考版本
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为当前 Windows / 原生 Python
3.8.10。本记录覆盖 Cordis 工具使用的 Inspect registry、Provider 目录和查询协议，
不认证全部 Inspect、动态 JS Host、全项目迁移或 Win7 发行。

## 实际迁移

旧 `cordis_manager.py` 返回固定 Provider 目录，以 `dir()` 等简化信息代替查询。
旧 runner 将 Client manifest 和 Future 直接放在自身，响应没有输入/输出 Schema 校验，
请求身份使用随机 UUID，取消靠轮询。现在按原版 `inspect-registry.ts` 接通：

- 独立 `cordisInspect` 服务维护可逆 Host 注册，以及原子替换的 Client manifest。
  校验空白身份、描述、重复方法和 Schema；冻结 manifest/method 行，保留 Schema
  对象的原版浅层借用语义。Host 目录在 Client 目录之前，注册 disposer 幂等且按身份判断。
- Host 查询先校验输入，再检查 signal，执行真实 handler，之后再次检查 signal；
  输出必须能无损转换为 JSON，快照脱离提供者，再校验输出 Schema。省略和 null 输入
  均以空对象验证，但 handler 仍收到调用者原来的输入。
- Client 请求使用递增 `inspect-N`，只在实际提供 input 时发送这个字段，携带
  请求 Agent 身份。外来会话、失败响应、非 JSON 或不符合 Schema 的输出均不结算。
  第一个有效响应先移除 pending 再发布关闭事件；重复、迟到和关闭事件内的重入响应被拒绝。
- 取消通过共享 signal 的订阅触发，移除 pending、结算等待者并发送原版关闭事件；
  in-flight 查询捕获自己的方法 Schema，不因新的 Client manifest 替换而改用另一契约。
  Python awaiter 取消也会撤销请求和监听，这是 Python 任务取消的显式适配。
- `DynamicCordisRunner.syncInspectManifest` / `resolveInspectQuery` 的 Remote 方法
  委托该服务；模型工具也委托同一服务，不再保留第二套固定目录与查询逻辑。

Service/Event Provider 读取从固定原版生成的 JSON 数据，生产端不执行 TypeScript。
开发脚本 `export-inspect-catalog.mjs --check` 校验固定 SHA、reference tracked-clean 和
生成物的完整内容。原版目录包含 68 个 Service、65 个 Event、682 个类型声明；
源目录/fixture 的固定源码哈希使用 UTF-8/LF，允许 Git 在 Windows 检出时改变文本
换行；本次运行报告另保存实际输入文件的原始字节哈希，观察数据不做换行清洗。
Host Event 过滤 `cordis/`，逐项查询只附带对应签名的传递类型闭包，顺序与原版一致。
这些数量是静态目录，不是原生服务已实现数量。TS 签名描述固定原版协议，不能直接
当成 Python 插件的函数签名或以此认证所有服务提供端。

Tool Provider 查询实际 `tools.schemas(requestingAgent)`，包含该 Agent 可见的动态和
作用域注册。Builtin Provider 明确描述当前 Python Host 的 `plugin(ctx)`、`harness`
和 Python builtins；没有宣称 Node VM 的 JS globals 可用。Builtin 的语言适配不在
Service/Event/Tool 目录的等价比较范围内，也不代表动态 JS Host 已迁移。

## 共用 JSON Schema

`dsh/core/json_schema.py` 移植原版 Tools 的校验子集，Tools 和 Inspect 共用同一实现，
公开 `JsonSchemaError`、`assertSupportedJsonSchema`、`assertObjectJsonSchema` 和
`validateJsonSchemaValue`。保留 Python 的 snake_case 入口；错误同时可由历史
`TypeError` 消费者捕获，公开 name/code/message/violations 对齐原版。

实现 annotation-only JSON、单类型、对象、数组、标量 enum/const、exact-one oneOf；
不支持的关键词和不合法组合被明确拒绝。显式帧保持深层 Schema/值检查无需递归，
循环与共享 DAG 分开判断；缺失字段、子节点、额外属性的诊断顺序按原版执行。
补齐有限数值、负零、整数浮点值、binary64 标量枚举比较、UTF-16 字符串比较和
JSON 错误文本中的配对/孤立 surrogate。被篡改的未知类型保留闭集 backstop，嵌套
异常归属最近的可处理帧。Tools 参数诊断采用原版隐式根，不额外添加 `arguments.`。

这不是整个 Tools author DSL、PTC、类型生成器或运行时契约的完成声明；原版
跨 realm / Proxy 机制也不能由 Python 原生容器测试直接认证。

## UPSTREAM-CORDIS-INSPECT-001

固定原版 `inspect-registry.ts` 构造器只注册 Service，没有登记 pending 查询清理。
实际复现：注册 Client Provider，发起查询并确认已广播，释放所属 Context fiber，
再观察 pending 和等待者。原版仍有 1 个 pending，等待者尚未结算；之后需要额外
abort 才结束。持有此 promise 的消费者在 Host 卸载时可能持续等待。

迁移版登记 registry 清理 effect，Host runner 的关闭也调用同一幂等清理。卸载后
pending 为 0、等待者已结算，结果为原版 Client 取消错误。监听已随 Context 释放，
这个整体卸载场景的外部关闭事件计数两边都是 0；不伪造仍存在的浏览器监听者。

`scripts/inspect_oracle.py` 只接受 `registry/disposal` 的完整精确双侧输出：

```json
{"upstream":{"pending":1,"settled":false,"closed":0},"python":{"pending":0,"settled":true,"closed":0}}
```

两边最终取消错误都必须是
`client.read: Client inspect query client.read was cancelled`。改变 case 身份、任一字段、
最终错误或添加字段都会失败。对应 pytest 验证门禁不会吞掉其他差异。

## 已执行验证

- `scripts/inspect_oracle.py --output .goose/out/inspect-final-paired.json`：43 组，
  **42 matched + 1 reviewed-upstream-bug/INSPECT-001**。运行实际固定源码，比较
  完整配方输出，包括错误 message、Schema 错误的 name/code/violations、目录、数据、
  响应、输入、事件和取消结果；目录场景逐项比较全部 Service
  与 Host Event 契约/类型闭包。source receipts 与输入 SHA 均保存，门禁重新验证
  checked-in fixture 与本次实际原版输出一致。没有通用错误文本清洗或差异忽略。
  普通 Python exception 类名、跨语言 stack 和所有 Remote 错误编码不由这组探针认证。
- 原版源码 `vitest.inspect-source.config.mts`：**127 passed / 7 files**，涵盖
  JSON Schema、Host runner 的五个原样文件及 Cordis 工具生命周期文件。该结果是
  原版行为基线，不能把 127 项计入 Python parity。日志 `.goose/out/inspect-source.log`。
- Python 专项：Inspect registry、Cordis tools、Tools、Ralph/Workflow 合计
  **166 passed**，13.74 秒，退出码 0；`.goose/out/inspect-final-focused.log`。
  包含 5000 层 union、Schema 借用、取消监听释放和真实 Tools 隐式根诊断。
- canonical `run_profile(web)` 下创建两个 cordis 会话，实际查询作用域工具，确认
  私有工具不泄漏；经 RemoteDispatcher 同步 Client manifest，使用真实 `agentId`
  lookup，拒绝外来会话与无效输出，接受首个有效响应并返回模型工具结果。这里使用
  正式 Host composition，未执行真实浏览器 UI，不能据此认证客户端联合旅程。
- 中间版本完整回归为 **4147 passed、2 skipped、1 warning**，335.62 秒，退出码 0，
  JUnit failures/errors 均为 0；`.goose/out/inspect-interim.log` / `.xml`。
  它发生在最后的测试与 Schema 边界调整之前，不能代替最终代码的全量结果。
- 另一轮过渡完整回归为 **4193 passed、2 skipped、1 warning**，336.52 秒，退出码 0；
  `.goose/out/inspect-complete.log` / `.xml`。运行期间继续补充了 Unicode/数值边界配方，
  所以同样不作为最终稳定输入的验收。
- 稳定输入的首轮完整回归为 **1 failed、4196 passed、2 skipped、1 warning**，
  357.28 秒，退出码 1；`.goose/out/inspect-final.log` / `.xml`。失败为已有
  `test_headless_retry_http.py` 的连续 503 场景：正式 headless 子进程超过测试自身
  25 秒限时。该 fixture 的持久日志已出现第一次 retry/retry-started，但没有完成 turn，
  不能将其解释为正常完成后仅清理缓慢。原进程由 subprocess.run 的超时分支终止，
  本轮没有延长限时、删除断言或修改请求代码以使其通过。
  原样单独执行该文件为 **4 passed**，5.96 秒，退出码 0，日志
  `.goose/out/inspect-headless-diagnostic.log`。这只证明单独复跑通过，根因尚未确认，
  不登记为原版 bug，也不代替全量复跑。
- 相同稳定输入的下一轮全量为 **1 failed、4196 passed、2 skipped、1 warning**，
  330.63 秒，退出码 1；`.goose/out/inspect-reviewed.log` / `.xml`。前一个 headless
  场景通过，失败转为已有 `test_extension_request_idle_watchdog_tracks_partial_wire_activity`：
  250ms idle watchdog 在 HTTP 连接建立阶段触发，未到 fixture 的持续字节发送阶段。
  原样单独执行其完整文件为 **13 passed**，9.02 秒，退出码 0；
  `.goose/out/inspect-image-diagnostic.log`。未修改 HTTP adapter、限时或断言；两次
  不同限时失败的根因仍未确认，保留记录，不以单文件通过覆盖全量失败。

最终相同稳定输入完整执行：

```powershell
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/inspect-stable.xml
```

**4197 passed、2 skipped、1 warning**，331.16 秒，退出码 0。JUnit 共 4199 项，
failures/errors 均为 0；`.goose/out/inspect-stable.log` / `.xml`。此前两项失败在本轮
均通过；这不是对间歇性网络限时失败根因的修复声明。没有删掉失败历史或改变断言。
warning 为既有 Windows Proactor transport 在事件循环关闭后的析构诊断，
pytest-asyncio 默认 fixture loop scope 提示与本机 HTTP 中止/重置诊断保留，
不宣称零 warning 通过。

原有 pruner 的 41 组双侧观察重新运行全部 matched，日志
`.goose/out/inspect-pruner-paired.json`。10 个新增/修改 Python 文件的 Python 3.8 AST
解析和 compileall 通过；migration check 通过，ready 退出码 0 且无就绪任务输出，
reference tracked-clean，git diff --check 通过。这些记录检查不认证全项目迁移完成。

## 剩余范围与交付

默认/None AbortSignal 的 Python 表示仍没有完全区分 DOMException 默认原因与
显式 null；目前只认证配方中的显式取消值与 Client 取消结果，不宣布全部平台 abort
等价。Client Inspect manifest/主题/Slot 查询的真实浏览器联合旅程、完整 Cordis
工具 prompt/presentation、原版 inspector/CDP 子系统、通用 JS Workflow、动态 JS
Host 和其他未验收模块仍须继续迁移。全项目 accepted_upstream 仍未建立。

继续采用 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
固定 Python 3.8.10 Portable、profile/Loader 所有的 Python 插件，按需携带预构建
client。本地目录/ZIP 和实验 API 已有实现；创造模式持久源码导出、升级回退、锁定
离线传递依赖闭包、client 联合安装验证，以及 GitHub Release/npm/PyPI 获取归一化
仍待实施。本轮没有新增生产依赖、QuickJS、Node Host 或浏览器源码修改，未重新
构建或发布 Portable。Win7 实机与目标浏览器验证继续保留用户暂缓状态。
