# 错误链诊断与压缩失败持久化进展

日期：2026-10-01。产品基线 `bf0344cb`，固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。当前 Windows / 原生 Python
3.8.10；本文记录限定范围的实施和验证，不认证全项目迁移或 Win7。

## 实施范围

移植原版 LLM 的 `errorChain`：显式 cause、AggregateError 成员、当前路径的循环
检测、共享子图重复呈现、空 message 的 name 回退、重复 cause 文本消除，以及无法
读取或转换的值。非 Error 的 own message 数据字段与 Error 属性读取分别处理，
保留源表达式的 getter 读取顺序。Python 原生异常没有 `.cause` 时采用显式
`raise ... from ...` 的 `__cause__`，不采用隐式 `__context__`；显式 null cause
优先于原生 cause。这是明确的 Python 适配。

Cordis 事件总线、Loader 和 LoaderGroup 的聚合异常继承同一基础表示，保留成员
身份。旧 Python `str` 展示保持其格式，并容纳成员字符串转换异常；构造聚合异常
不再提前转换成员，避免在汇集失败时再次抛错而丢失成员。

压缩事务失败的 `compaction/end.error` 使用完整错误链。配置 Agent 启动日志、
AgentLoop 通用失败、Session Remote 错误通知，以及子代理 setup/continuation
释放失败也采用共享诊断。AgentLoop 对实际 LlmError 保留其结构化 failure 字段，
其他 turn 失败继续使用 UNKNOWN 分类。这项工作不改变压缩策略或正常提交流程。

真实失败事务验证摘要失败、关闭失败和主要失败后 flush 失败：失败摘要只尝试
一次关闭，正常失败关闭后 flush，关闭失败保留未闭合事务供 invariant 检测，
flush 失败不替换主要错误。正式 Web profile 的可控 LLM 场景观察 Remote 事件、
命令错误、真实持久化记录、关闭和冷启动读取；它不是浏览器或真实付费模型验收。

## 双侧验证

新增 32 组错误图与 19 组真实失败事务。fixture 仅构造图，TypeScript 侧调用固定
原版 renderer / compaction，Python 侧调用实际迁移实现；没有另写参考 renderer。
比较完整错误文本、失败身份、关闭尝试数、flush、事件归属和记录关联。

```powershell
.venv\Scripts\python.exe scripts/compaction_oracle.py --output .goose/out/error-chain-paired.json
```

155 组门禁通过：153 matched 与此前已审核的 POLICY-001、SUMMARY-001 两个精确
原版 bug 签名。新增 51 组全部 matched，没有新增排除、错误文本归一化或原版 bug。
这不把此前两个精确差异扩大为宽松白名单。

```powershell
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.error-chain.config.mts
```

原版源基线 282 passed / 13 files，4.47 秒：LLM service 的 85 个断言与 compaction
的 197 个断言。源基线不是 282 个 Python parity 场景。输出为
`.goose/out/error-chain-source.log`。

Python 专项 145 passed，6.44 秒，覆盖 renderer、真实压缩事务、配置 Agent、
AgentLoop、子代理释放、Cordis 事件总线及 Loader 事务。

## 验证与后续边界

完整回归：

```powershell
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/error-chain-final.xml
```

4069 passed、2 skipped、1 warning，329.51 秒，退出码 0。JUnit 共 4071 项，
failures/errors 均为 0；日志和 JUnit 为 `.goose/out/error-chain-final.log` /
`.goose/out/error-chain-final.xml`。warning 为既有 WebServer 注入行测试的 Windows
Proactor transport 在已关闭事件循环上的析构诊断。pytest-asyncio 默认 fixture
loop scope 提示与本机 HTTP 中止连接诊断保留，不宣称零警告通过。

18 个变更或新增 Python 文件通过 Python 3.8 AST 解析，compileall 通过；固定
reference 无修改。migration check 通过，ready 退出码 0 且无就绪任务输出，
git diff --check 通过。这些记录检查不认证全项目完成。生产代码仍为 Python 3.8，
未新增生产依赖、QuickJS、Node Host 或浏览器源码变更。

后续维护等待、取消原因与真实压缩关闭已继续修复，具体双侧观察和范围见
[Agent 维护进展](2026-10-01-agent-maintenance-progress.md)。下文待办保留原始基线。

此 renderer 的测试范围不认证任意跨 realm JS 对象、恶意重写 AggregateError
成员容器、无限深错误链或所有未迁移消费者。Session promote 的完整行为、ACP /
Webhook 等消费者、压缩取消和 maintenance 生命周期、client 历史展示及浏览器
联合旅程仍须继续审计。通用原版 JS Workflow、动态 JS Host、Inspect 和其他未
验收模块仍在完整迁移目标内。

交付继续遵循 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
固定 Python 3.8.10 Portable、本体与第三方插件共享 profile / Loader。本地目录与
ZIP 已有实验实现；创造模式源码导出、升级回退、锁定离线依赖闭包、可选 client
联合验证及 GitHub Release / npm / PyPI 获取归一化仍需实施。本轮未重建或发布
Portable，Win7 实机及目标浏览器验证保留用户暂缓状态。
