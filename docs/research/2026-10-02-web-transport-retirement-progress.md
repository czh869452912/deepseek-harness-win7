# 旧 Web carrier 退役与原生问题／审批作用域修复

日期：2026-10-02。产品起点 `8a551f374c977eef319abf4a59544e177b8170c6`，
固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。
本轮遵循原生 Python 3.8.10／Win7 目标，不引入 QuickJS、Node Host 或生产依赖，
不修改原版浏览器源码或预构建资源。

## 实际退役范围

固定参考的 manifest 没有 `dsh-apiproxy` 包，正式 `web` profile 已采用
WebServer → Connection → Typert Gateway → application Remote 的装配。
删除旧 `ApiProxyPlugin` 实现、安装自带的包名映射、`dsh.host` 导出，以及旧
Fetch dispatcher／in-process client。`dsh.host.apiproxy` 不再导出可挂载的插件。
旧 `/api/respond`、`/api/events/mux`、`/api/events/host` 和相关本地桥接 URL
不再有运行时提供端。客户端 HMR 的 `/plugins/events` SSE 保留；它与业务传输不同。

`tests/test_web_transport_retirement.py` 使用真实 canonical profile、实际监听端口、
launch-token／cookie 交换，验证未认证 Remote 请求被拒绝，认证后的
`/api/pluginInventory/list` 正常返回，而九个代表性旧 URL 返回 404。
同时核对 Gateway 的 `/api/remote.mux` upgrade 注册和 HMR 路由仍存在。
这里没有把“匹配 `/api` prefix”误认为旧业务 endpoint 仍有提供端。

剩余 `dsh.host.apiproxy.api` 历史域适配器及两个旧工具函数仍被历史单元测试直接引用；
它们不在正式启动路径上，也不作为本目标 Web parity 证据。整个历史 helper 包及
旧 Connection authentication facade 的后续退役仍须迁移必要测试，不能据此宣称
所有旧 Web 代码均已删除。已有历史报告／验收快照不改写。

## 问题／审批迁移偏差

原版 `interaction/user-questions/src/index.ts:138` 和
`interaction/user-approval/src/index.ts:284` 的 waterfall 都使用
`scopeTarget(agent, agent)`。迁移版此前直接通过普通 Context 派发，丢失
Agent carrier identity；正式 `api-remotes` 因没有主体而继续 waterfall，
问题落入 `NO_PROVIDER`，审批返回 `unavailable`，Web 收不到 scoped 请求。

修复这两个原生 Python 服务，通过 `scope_target(agent, agent)` 携带 caller identity。
不带 Agent 的合法 question 调用仍沿用全局 answerer 路径。
这是迁移版偏差修复，原版在这两处已有正确行为，本轮不登记为原版 bug。

正式 profile 的新增验证覆盖直接 question service、实际 preset 中的
`ask_user_question` tool handler 和 approval service。Gateway `$events` 流必须收到
准确的 Agent id 和去掉 Agent／signal 对象后的 JSON 请求；真实认证 HTTP
`POST /api/$events/result` 完成应答。取消释放 pending，question 报 `ASK_ABORTED`，
approval 返回 `cancelled`；后者的 `approval/asked`／`approval/decided` 审计对
携带同一 id，记录在实际 turn 内。

同一组直接 question／approval 应答和取消测试，用 `git show 8a551f37` 取出的
原服务源码执行：**4 failed**，均在等待 Gateway waterfall frame 时超时。
修复后四项通过。原始 before XML／日志在
`.goose/out/web-retirement-before.xml`／`web-retirement-before.log`；这份记录是
迁移版修复前后比较，不是原版 Node 与 Python 的完整双侧 oracle。

## 测试替换与验证

退役 21 个旧桥接专用 test function，新增 9 个 canonical profile 测试实例。
不保留固定 58 个旧 unary 名称作为当前 Remote 清单。旧测试的一些返回形状也
不是当前契约：例如 canonical preset copy／delete 返回 undefined，fork 需要实际
completed turn 边界，不能继续断言旧桥接的占位返回。

- 旧路由／广播格式和集中 respond 测试由真实 Connection／Gateway 测试替代。
- preset 作者操作和选中 Session projection 通过真实 `agentPresets` Remote 验证。
- Session create、Workspace attach、anchored fork 的 Agent 原子发布转到正式 profile；
  无效 preset 不发布 Session／Agent。
- 现有 WebServer 源码契约测试、DirectoryPicker、Settings、LLM、Goal／Plan、
  Session history／tool／cold restart、MessageFeedback 实际 socket transcript 和
  Gateway mux 生命周期测试继续保留。删除旧 tests 不代表这些功能取消。

专项：**33 passed，21.12 秒，退出码 0**；日志／JUnit 为
`.goose/out/web-retirement-focused.log`／`web-retirement-focused.xml`。
全量 `.venv\Scripts\python.exe -m pytest tests`：
**4702 passed、2 skipped、1 warning，675.55 秒，退出码 0**。
JUnit 记录 4704 项、0 failures、0 errors。已设置 `DSH_TEST_CHROMIUM`，
两个原版浏览器 lifecycle／inspect 测试均实际执行，通过而非 skip。
日志／JUnit 为 `.goose/out/web-retirement-full.log`／`web-retirement-full.xml`。
仍有既有 Proactor transport 析构 warning、pytest-asyncio fixture 提示和
测试 HTTP 连接中止诊断，不宣称零警告。`migration.py check`／`ready` 返回 0，
没有推进全项目 accepted_upstream；reference 和原版前端目录无修改。

## 后续范围与交付

保持 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)
的发布方向：固定 Python 3.8.10 Portable，本体和 Python Host 插件共用
profile／Loader，插件通过目录、ZIP 或指定哈希的 HTTPS ZIP 进入同一 store，
可选 Client 在开发端构建，用户运行不需要 Node／pnpm。

本轮新增问题／审批证据为原生 Gateway／HTTP 联合验证，尚不替代实际原版
question／approval widget 的浏览器旅程。Source 审查还发现 approval 对任意
answerer 的 signal race／迟到结果丢弃仍需补齐，不能把 Gateway 自己的取消
验证扩大为整个 approval service 的取消契约已完成。

完整 helper 退役、通用 JS Workflow／Host、完整 SDK 动态治理、任意 wheel／原生
依赖、版本范围求解、npm／PyPI 获取及完整上游迁移仍未认证。
Win7 真机与目标浏览器保留用户暂缓状态。新的源码回归不自动更新旧 Portable。
本批次的独立候选与实际解压门禁使用以下命令；通过状态、准确 producer commit、
clean 标记、ZIP／运行时／前端哈希及 13 个 runtime、5 个 browser 检查均以
生成的 `web-retirement-extracted.json` 收据为准：

```powershell
.venv\Scripts\python.exe scripts/build_portable.py --output-dir dist/candidate-web-retirement-20261002 --ripgrep-source scripts/oracles/official/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe
.venv\Scripts\python.exe scripts/verify_portable.py --archive dist/candidate-web-retirement-20261002/dsh-win7-portable-v0.1.0.zip --output .goose/out/web-retirement-extracted.json --expected-commit <完整干净提交SHA> --browser <Chromium绝对路径>
```

该候选不覆盖默认 dist、旧候选或真实用户 profile；公开发布、授权审计和软件更新
保留用户资产仍须单独验收。
