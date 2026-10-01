# 原生审批取消、服务所有权与审计契约迁移

日期：2026-10-02。工作从 `b8fa46df` 继续，固定上游为
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。本轮保持 Python 3.8.10／Win7
目标，无新增生产依赖、QuickJS、Node Host 或浏览器资源变更。

这是审批能力的有界实施与运行证据，不是全项目迁移完成、Win7 认证或实际原版
question／approval widget 浏览器旅程的验收。

## 原版依据与迁移版修复

对照固定原版 `packages/interaction/user-approval/src/index.ts`：

- 原版先检查已取消 signal，再应用 `never` 策略，随后将 answerer 的应答与 abort
  竞速。迁移版原来直接等待 waterfall，只在结束后检查 abort；永久等待的 answerer
  会阻止请求取消。现在取消可以先返回 `cancelled`，即刻写入唯一决定；迟到的成功
  或异常被消费并丢弃，不改变已记录的决定。
- 原版借用同一请求、Agent 与 signal，并以实际 Agent 为 dispatch carrier。
  保留上一轮的 carrier 修复，不复制请求或将对象变成仅含 ID 的 JSON。
- 原版 Promise 在取消后仍允许 answerer 结束。Python 用强引用集合保留未结束的
  answer task，完成回调消费结果并释放引用；不以取消审批为由强制取消借用的
  answerer。signal 监听在取消、应答和 Python 调用 task 退出时解除。
- 原版 `ApprovalService` 是 Cordis `Service`，通过延迟 `inject(['systemPrompt'])`
  注册可逆动态 context。迁移版原来仅检查构造时已有的 prompt，且返回普通对象。
  现在采用 Service 所有权和依赖注入，支持 prompt 后到、卸载及重新加载；审批
  插件退出后 `approval:policy` 与服务一起撤销。
- 原版策略切换通过 `createUserMessage` 发布消息。迁移版原来的手写字典没有
  message ID；现在使用正式构造器，重复切换到相同策略不重复发送。
- 原版审批 ID 是完整 `randomUUID()`。迁移版原来使用 8 位十六进制短 ID，现改为
  Python `uuid.uuid4()` 的完整字符串。插件 Config 增加原版 ask／never 闭集及 ask
  默认值。

这些问题均为迁移版偏差；固定原版在相应位置已有正确实现，本轮不登记原版 bug。

## 审批审计 companion

原版另行导出 `@deepseek-ai/dsh-user-approval/invariant`，之前本地包解析未注册它。
本轮增加 `dsh/interaction/approval_invariant.py` 和 canonical Loader 入口映射：

- 包通过 `invariants.register` 保留独立所有权，等待 `sessions` 提供方，卸载可逆。
- asked／decided 必须位于 open turn；asked 的工具名必须非空，未决 ID 不可重复，
  decided 必须对应未决请求并使用四种正式 outcome；policy 限于 ask／never。
- 按实际 Session 对象保存 trace，即使两个对象拥有相同 durable ID 也不混用状态。
  从已有日志、后来创建的 Session 和 bare publication 恢复配对状态。
- 在 `internal/dispatch` 中验证并暂存候选，正式 `session/event` 发布后才推进未决
  集合。后续 precommit listener 否决候选不预先占用请求 ID，非法 outcome 不消费
  有效未决请求。native append 的候选使用弱引用，释放的 Session 不被 trace 保留。

未改动原版 profile composition 来强制启用 companion；它沿用原版独立包入口和
invariants 服务配置。正式 Loader mount／unmount 与错误回放的注册回滚有专项覆盖。

## 验证与证据边界

修复前以 `b8fa46df` 的产品代码执行新增的 20 项行为断言：**8 failed、12 passed**，
退出码 1，JUnit failures 8／errors 0。失败分别是迟到 grant／reject／error 三种取消、
falsey 已取消 signal、prompt 后到／重载、策略消息身份及 UUID。日志与 JUnit 为
`.goose/out/approval-contract-before.log`／`approval-contract-before.xml`，保留失败历史。

修复后专项：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_approval_contract.py tests/test_approval_invariant.py tests/test_reference_user_approval_specs.py tests/test_approval_and_commands.py tests/test_acp_approval_and_mcp_parity.py tests/test_web_transport_retirement.py -q --junitxml=.goose/out/approval-contract-focused.xml
```

**56 passed，27.65 秒，退出码 0**。这包含真实 Web profile／Gateway 的原有专项，
不是 56 项原版断言都已翻译并等价证明。pytest-asyncio 默认 fixture scope 提示仍保留。

双侧命令：

```powershell
.venv\Scripts\python.exe scripts/approval_oracle.py --output .goose/out/approval-paired.json
```

该命令在干净固定 reference checkout 中原样执行官方 `approval.spec.ts` 的 32 项、
`invariant.spec.ts` 的 6 项断言，并额外执行独立 source observer。开发端 Node
v22.22.2 不是产品运行时。Python 3.8.10 直接调用实际本地服务。**9／9 运行观察
一致**：已取消、never、取消后迟到 grant／exception、应答后取消、缺少 answerer、
prompt 后到／重载／卸载、唯一策略消息、审计 precommit veto 与未匹配决定。

比较保留实际工具名、消息内容／source、调用次数、借用请求与 carrier 身份、
取消前后日志、veto 错误及合法事件顺序。随机 UUID／message ID 归一为占位值；
UUID 格式和 asked／decided ID 相等性另行观察，未删掉身份检查。报告记录上游 SHA、
产品 HEAD／tracked dirty、观察器与枚举实现文件的 SHA-256，以及原样 source suite
收据；比较前后输入哈希必须一致。这不是全模块或全部 transitive 输入的发行认证。

全量 `.venv\Scripts\python.exe -m pytest tests` 已启用 `DSH_TEST_CHROMIUM`，
结果为 **4739 passed、2 skipped、1 warning，682.54 秒，退出码 0**。
JUnit 记录 4741 项、0 failures、0 errors；两个原版浏览器 lifecycle／inspect
用例均实际执行通过。日志／JUnit 为 `.goose/out/approval-contract-full.log`／
`approval-contract-full.xml`。既有 Proactor transport 析构 warning、pytest-asyncio
fixture 提示及测试 HTTP reset 诊断仍保留，不宣称无警告。

`scripts/migration.py check`／`ready` 返回 0，没有就绪任务输出；这不是全项目
parity 认证，未推进 accepted_upstream。reference／原版前端目录没有修改。

## 交付和后续范围

发布继续遵循 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
原生 Python Host，单目录 Portable；插件经目录、ZIP 或指定哈希的 HTTPS ZIP
进入相同 store，专用 Client 在开发端构建，用户运行不要求 Node／pnpm。

本轮源码不自动更新此前 `b8fa46df` 的候选 ZIP；如重建独立候选，准确 producer、
clean 标记及解压后的实际运行结果以本轮收据为准。公开发布、授权审计、软件更新
保留用户资产、wheel／原生依赖、版本范围求解、npm／PyPI 获取仍须分别验收。

本轮独立候选命令与收据位置如下；准确 product commit、archive SHA-256、
运行时／前端输入及每项成功状态由实际门禁写入 `approval-extracted.json`，
本段不以命令存在代替执行结果：

```powershell
.venv\Scripts\python.exe scripts/build_portable.py --output-dir dist/candidate-approval-20261002 --ripgrep-source scripts/oracles/official/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe
.venv\Scripts\python.exe scripts/verify_portable.py --archive dist/candidate-approval-20261002/dsh-win7-portable-v0.1.0.zip --output .goose/out/approval-extracted.json --expected-commit <完整干净提交SHA> --browser <Chromium绝对路径>
```

实际原版 question／approval widget 交互、历史 domain helper 退役、通用 JS
Workflow／Host、完整 SDK 动态治理和全部上游迁移继续实施。Win7 真机与其浏览器
保留用户暂缓状态；当前 Windows／Python 3.8 测试不能替代该认证。
