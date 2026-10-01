# 原版 Client 与原生 Python Host 的实际浏览器联合旅程

后续真实 Tools → 原版 Client Inspect、双页面结果竞争、主题/Slot/Provider 清理
及冻结 JSON 边界修复见 [浏览器 Inspect 进展](2026-10-01-native-web-inspect-progress.md)。
下文保留本批次 minimal Session 与历史验证范围。

日期：2026-10-01；起始提交 `8ebb7e13`；固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。
继续 [Host 终止事务](2026-10-01-cordis-retirement-progress.md) 的客户端联合验收。
本轮补齐此前协议、原版源码和 Python Host 测试之外的实际浏览器证据。
没有修改产品 Host、原版 Web 源码、Client bundle 或依赖，没有加入 QuickJS。

## 实际链路

`scripts/native_web_host_fixture.py` 在独立进程建立临时 DSH_HOME 和工作区，
通过真实 `run_profile(web)`、随机端口、canonical Connection / Typert Gateway /
ClientModules / FrontendStatic 启动 Python 3.8.10 宿主，建立真实 minimal Session/Agent。
模型 continuation 的 `steer` 仅替换为记录 sink，不发出付费模型请求；Session、
Agents、Remote、runner、Guard、Fiber 和服务注册使用产品实现。因此本记录不认证
真实 LLM 生成插件或审批后的代理继续执行。

stdin 只负责定义源码、发出相当于模型 cordis_run 的请求、读取 Host 真值和关闭。
审批、Client 加载、版本授权、host.call、停止、重启、移除和拒绝，全部经真实页面
控件触发原版业务 Remote。没有直接调用 stop/undefine 代替页面操作，没有 mock
HTTP 路由或注入页面内部 Context。

`scripts/native_web_browser_oracle.mjs` 用开发机 Node v22.22.2 的 WebSocket/fetch
驱动独立 Chromium CDP，加载宿主认证 URL。鼠标点击检查目标可见且未被遮挡，
真实操作首次启动声明；测试插件只贡献可观察的 shell.overlay，不改写产品页面。
临时浏览器和宿主目录在结束后清理，认证 URL 不写入报告。
开发浏览器为 HeadlessChrome/149.0.7827.55；这些都是开发验证工具，不进入用户
Python Host 或 Portable 依赖。本轮不能代替 Win7 真机与目标浏览器认证。

## 通过的观察

最终旅程 17 个检查点（其中 4 次不同激活/页面上的 JSON 调用分别计数）：

- 原版应用启动与首次启动声明设置提交。
- 请求激活后、用户审批前，Host 服务与 Client DOM 都不存在。
- 用户仅授权首版后，两半运行，提交 currentPackageId，审批请求清空。
- Client 的 host.call 携带嵌套数组、null、布尔、中文与整数；Python handler
  回答版本和原值，真实页面渲染 JSON，与请求结构精确一致。
- 二版更新仍需审批；审批前首版继续运行。用户授权后续版本后，两半替换成二版。
- 三版故意在 Client apply 抛错；Host 撤销，无 activeRun，current 保留二版、
  next 保留三版；面板显示错误，审批请求清理。
- 在同一 Plugin 定义四版，复用后续版本授权，从故障恢复；pluginId 不变。
- 页面刷新后 Host 继续运行，Client 不自动执行，面板显示 client-pending。
- 用户点击运行，Client 挂载到已有 Host run，pluginRunId 不变。
- 停止撤销两半，保留定义和成功版本；重新运行产生新的 pluginRunId。
- 运行中移除定义，两半及 inventory 清理。
- 新插件被用户拒绝，两半未执行，状态 rejected，审批请求清空。

实际浏览器发出 runHostHalf 6 次、getClientCode 6 次、resolveRequestRun 5 次、
settleUserRun 2 次、invoke 4 次、stopFromPanel 1 次、undefineFromPanel 1 次。
首开和刷新分别建立 `/api/remote.mux`。原版 Connection 的 unary Remote 用 POST，
mux 承载订阅流；不把业务 RPC 都描述成 WebSocket 帧。

故意失败的 Client 仅产生一条预期 console.error，严格匹配指定
probe-1/pkg-3/run-3 和 fixture 错误前缀，其他错误不被豁免。
没有未捕获页面异常、HTTP 失败或宿主 stderr 诊断。本轮未发现新原版 bug。

## 输入和验证边界

核对 frontend-inputs 声明的 119 个 shell 文件哈希；从活动 Loader 来源派生实际
46 个 Client bundle，不固定插件数。bundle 和 map 保存 SHA-256；map 内 404 个
一方源码项（含重复引用）与 reference 原版源码逐项比较，仅归一 CRLF/LF。
vendor/node_modules 项记录嵌入源码哈希；原版缺少 lib 的编译输入与当前本地 lib
核对并单列 generated，不当成原版源码验收。相关脚本和 Host 输入哈希在运行期间
保持一致。报告在 `.goose/out/native-web-browser.json`，失败时保存截图和两端真值。

source map 匹配是来源证据，不是重新构建证明，也不单独证明生成代码必然一致。
行为证据来自实际浏览器执行。不认证全部 Client 测试、任意 JS Host/Workflow、
全部 Slot/Inspect/Guard、所有业务旅程或全项目 parity。

```powershell
node scripts/native_web_browser_oracle.mjs --browser <开发机 Chromium 路径> --output .goose/out/native-web-browser.json
$env:DSH_TEST_CHROMIUM = '<开发机 Chromium 路径>'
.venv\Scripts\python.exe -m pytest tests/test_native_web_browser.py tests/test_cordis_runner_state.py tests/test_cordis_retirement.py tests/test_canonical_web_runtime.py tests/test_typert_dispatch.py -q
```

专项 **48 passed / 28.53 秒**，包含实际浏览器 lane，退出码 0。
未设置 DSH_TEST_CHROMIUM 时该 lane 显式 skip；skip 不能当成浏览器通过。
Python 3.8 py_compile、Node syntax check 和 git diff --check 通过。
最终 `.venv\Scripts\python.exe -m pytest tests`（开启上述浏览器 lane）为
**4494 passed、2 skipped、1 warning / 434.49 秒**，退出码 0；JUnit
4496 tests，failures/errors 均为 0。原始日志和 JUnit 在
`.goose/out/native-web-browser-full.log` / `.goose/out/native-web-browser-full.xml`。
两项 skip 是 Windows 不适用的既有 POSIX 场景，新增浏览器 lane 实际通过。
warning 为既有 Windows transport 事件循环关闭后的析构诊断，另保留
pytest-asyncio loop scope 提示与测试 HTTP ConnectionResetError 输出，不宣称零警告。
全量运行期间未修改脚本、测试、产品源码或浏览器输入；最终 standalone oracle
再次通过 17 个检查点并保留 10 个相关输入哈希。migration.py check / ready
退出码 0，reference 工作树未修改；记录门禁不是全项目 parity 认证。

## 后续迁移与交付

通用原版 JS Host/Workflow 执行仍是完整目标内的缺口；更多客户端 Inspect/Guard、
并发页面、审批/停止竞争和业务联调继续。保持原生 Python 3.8.10 / Win7 主线。
发行沿用 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
固定 Python Portable 本体；Python 插件统一经 profile/Loader；本地目录/ZIP 和
[源码升级回退](2026-10-01-python-plugin-versions-progress.md) 已有实现。
创造模式源码导出、依赖闭包、多来源获取、可选 Client 插件交付与最终发行仍须实施。
内存插件旅程不能认证可安装第三方 Client 插件或新 Portable。本轮没有发布、推送、
重建 Portable 或推进 accepted_upstream。Win7 实机验证维持用户暂缓状态。
