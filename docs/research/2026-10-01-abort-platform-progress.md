# 原生取消原因与 Inspect / Tools 消费者对齐

日期：2026-10-01；起始提交 `8bcf47b9`；固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。
本轮继续 Inspect 尚未验收的默认/显式 null 取消边界，并修复同一契约的消费者。
环境为 Windows / Python 3.8.10；Node v22.22.2 仅用于原版行为比较。

## 迁移版偏差与修复

原版 Inspect 直接调用平台 signal.throwIfAborted，Tools 的 fuseToolSignals
返回实际 AbortController.signal。此前 Python 的 abort 默认参数 None 抹平了
未传原因与 JS null；throw_if_aborted 总抛 RuntimeError；Inspect、extension prepare、
Session preparation、Terminal、Agent factory 和 Compaction 各自做了不同的部分转换。
原始 addEventListener 又被错误等同于会立即通知已取消状态的 Python 订阅助手。
这些均是迁移版偏差，本轮没有据此登记原版 bug。

- 未传原因或显式共享 UNDEFINED 产生新的 AbortError，name / message / code
  为原版 Node 平台的 AbortError / This operation was aborted / 20。
  重复取消保留首个原因；不同 signal 的默认异常实例互不共用。
- 显式 None、false、0、空字符串、对象和异常保留原值及身份。
  Python 不能抛任意值，因此使用已有 ThrownValueError.value / reason 携带非异常；
  BaseException 直接按同一实例抛出。未取消时 reason 的 Python 表示仍为 None。
- 原始 addEventListener 不重放旧事件，回调收到包含 type、target、currentTarget
  的事件；支持同 callback/capture 去重、once 和移除中的所有权。单次 dispatch
  期间移除后续原始 listener，不再调用已移除 listener。
- add_listener / subscribe_abort 保留 Python 订阅助手的已取消状态即时通知与 disposer，
  不再把该适配说明成原始平台事件语义；历史 asyncio.Event / 外部无 reason 信号仍
  保留显式适配，不把它们当成完整平台信号。
- 共用 abort_reason_error 修复 Inspect、extension prepare、Session preparation、
  Terminal、Agent factory、Compaction 的原因转换。Commands 保留原版独立规则：
  Error 直接抛，字符串转换为同文本错误，其他值规范化为 command aborted。
- Tools 融合信号补齐 throwIfAborted / throw_if_aborted，透传默认或原始原因；
  原始事件 target/currentTarget 指向工具实际收到的融合信号。Python wait 助手可
  观察它；一次取消后 caller/wrapper relay 清理。完整产品 dispatch 而非仅私有类
  单测覆盖原版超时策略所创建的融合信号。

## 原版双侧观察

`scripts/oracles/abort.spec.ts` 直接使用开发 Node 的平台 AbortController/AbortSignal，
并加载固定原版真实 Context、Inspect registry、SystemPrompt、Tools 和 timeout policy。
没有重新实现 JS signal 或原版消费者。`abort_python.py` 用原生 Context、产品服务
和同一输入运行另一侧；`abort_oracle.py` 校验 reference SHA/工作树、输入哈希和观察
相等，保存两侧原始数据与日志。source fixture 绑定源文件和 probe 配置哈希。

**56/56 精确匹配**：9 种原因 × 6 类旅程，加 2 个原始平台用例。

| 旅程 | 核心观察 |
| --- | --- |
| platform | 默认/undefined/null/false/0/空串/字符串/对象/Error；首原因、异常身份、一次事件、迟到 listener 不触发。 |
| Inspect Host before | 查询前取消，provider 不执行，直接抛原始原因。 |
| Inspect Host after | provider 返回时已取消，结果不覆盖取消原因。 |
| Inspect Client before | 不分配/发布查询，不产生等待任务。 |
| Inspect Client pending | 请求已广播后取消，使用原版业务取消结果并发布 resolved；不把原始原因误当成该业务结果。 |
| Tools fused | 真正 Tools dispatch + timeout policy；融合身份、原始事件目标、throwIfAborted 原因、迟到事件、最终 ABORTED 分类。 |
| 其他平台用例 | listener 去重与 dispatch 中移除；AbortSignal.abort(null)。 |

既有 Inspect oracle 重新执行，**42 matched + 1 reviewed-upstream-bug/INSPECT-001**，
没有其他差异。INSPECT-001 是此前已记录的 registry 卸载行为，本轮未新增例外。
不把这些有界观察认证成全部 EventTarget、DOMException、静态 any/timeout API、
浏览器默认取消文案或所有异步消费者的完整语义；原版 Node 平台文案也不冒充浏览器文案。

```powershell
.venv\Scripts\python.exe scripts/abort_oracle.py --output .goose/out/abort-paired.json
.venv\Scripts\python.exe scripts/inspect_oracle.py --output .goose/out/abort-inspect-final.json
.venv\Scripts\python.exe -m pytest tests/test_abort_platform_consumers.py tests/1to1/core/test_abort.py tests/1to1/interaction/test_commands.py tests/test_timeout_policy.py tests/1to1/llm/test_deepseek_api_extensions.py tests/test_session_preparations.py tests/test_compaction_transaction.py tests/test_cordis_inspect_registry.py tests/test_terminal_session.py -q
```

最终专项 **244 passed / 3.33 秒**，退出码 0；新增 45 个 Python 测试，其中一项
运行并比较完整的 56 组源观察，不能将 56 组计作 56 项新增 pytest。
修正旧 test_abort 中声称原始迟到 listener 会立即触发的错误断言；平台真实运行
证据证明该断言错误，没有为通过测试改变原版源码。
Python 3.8 py_compile 和 git diff --check 通过。

最终 `.venv\Scripts\python.exe -m pytest tests`（启用原版浏览器 lane）为
**4539 passed、2 skipped、1 warning / 386.98 秒**，退出码 0；JUnit
4541 tests，failures/errors 均为 0。日志与 JUnit 在
`.goose/out/abort-contract-final.log` / `.goose/out/abort-contract-final.xml`。
浏览器 lane 实际通过，两个 skip 为 Windows 不适用的既有 POSIX 场景。
warning 是既有 Windows transport 关闭后的析构诊断；保留 pytest-asyncio loop scope
提示与测试 HTTP ConnectionResetError 输出，不宣称零警告。此前过渡版本全量为
4538 passed、2 skipped、1 warning / 403.63 秒，不代替最终版本验证。

最终全量期间未修改产品、脚本、测试、source fixture 或浏览器输入；配对报告的
19 个输入哈希仍与当前文件一致。migration.py check / ready 退出码 0，reference
工作树无修改，git diff --check 通过。记录检查不认证全项目 parity。

## 剩余迁移与交付

本轮没有新增生产依赖、QuickJS、Node Host 或浏览器代码变更，没有发布、推送或
重建 Portable。继续原生 Python 3.8.10 / Win7 主线；Win7 真机和目标浏览器认证
维持用户暂缓状态。完整原版 JS Host/Workflow、experimental Inspector/CDP、
客户端 Inspect 联合旅程和其他未验收模块仍须迁移，accepted_upstream 未建立。

发布和插件获取沿用 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
Portable 固定运行时；用户插件经 profile/Loader；目录/ZIP 与源码升级回退已实现。
创造模式持久源码导出、依赖闭包、多来源获取、可选 Client 交付及最终发行继续实施。
本轮基础取消修复不能代替上述交付验收或声明全部迁移完成。
