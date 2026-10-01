# 原版浏览器 Inspect 与原生冻结参数边界

日期：2026-10-01；起始提交 `bc2af7ad`；固定参考版本
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。
本轮继续 [Inspect 提供端](2026-10-01-cordis-inspect-progress.md) 与
[原版 Client / 原生 Host 联合旅程](2026-10-01-native-web-cordis-browser-progress.md)，
完成下列实际浏览器场景及其共享边界修复，不认证全项目或 Win7 发行。

## 实际产品链路

`native_web_browser_oracle.mjs --inspect true` 启动隔离的 canonical `run_profile(web)`，
建立真实 `cordis` Session/Agent。stdin 只安排输入、读取结果和触发调用方取消；
`cordis_inspect_query` 经真实 Tools dispatch 执行，参数由产品冻结。
Host registry 经应用事件源、Gateway 和 `/api/remote.mux` 广播查询；原版浏览器
Client registry 运行提供者，经真实 Connection POST
`dynamicCordisRunner/resolveInspectQuery` 回传。记录实际 RPC 请求/响应。

浏览器仍使用原版 shell、46 个实际 Loader Client bundle 和 Remote 类型产物；
shell 的 119 个已锁定输入核验未改，bundle source map 的第一方源码与固定 reference
核对。动态试验源码经原版审批和 Client evaluator 执行，未改产品浏览器源码、资源或
协议，未模拟 Client registry 或其服务。Modern Node / Chromium 只作开发验证工具。

模型 continuation `owner.steer` 保留为记录 sink，没有调用付费 LLM；这不认证模型
实际生成插件、完整 Agent turn 或审批后的模型继续执行。默认不传 `--inspect` 时，
既有 minimal Session 生命周期 lane 继续运行。

## 修复的迁移版偏差

第一轮对象参数查询失败：`forwarded host event "cordis/inspect-query" argument 0
is not lossless JSON data`。只省略 input 的查询已经成功，但 Tools 将显式对象参数
冻结成 `FrozenDict`，Gateway 共用的 `assert_json` 仅接受精确 dict/list，错误拒绝
内部冻结 JSON。原版 Object.freeze 不改变普通对象/数组的 prototype。

`dsh/typert/dispatch.py` 现接受精确 `FrozenDict` / `FrozenList` 及其递归 JSON 内容。
仍拒绝任意 dict/list 子类、内部冻结类的子类、非 JSON 值、非有限数和循环；事件
lossless 校验继续拒绝负零。没有把所有 Mapping 或任意 Python 对象视作 JSON。
同一边界的真实 SRC Remote 冻结输出也有覆盖。这是迁移版偏差，没有新增原版 bug。

`remote-frozen.spec.ts` 直接运行原版 Session `isJsonValue` 和 Gateway
`isRemoteJsonValue`，输入为真实 Object.freeze 的对象/数组、共享子树、负零、Infinity、
NaN、undefined、自定义对象/数组和循环。两侧原版验证器的 **16 组观察一致**；Python
lossless 对同一配方匹配。fixture 记录固定 SHA、Node 版本和 7 个源码/配置哈希；
pytest 比较观察与核验哈希，不以手写 JS 验证器代替原版。

## 真实浏览器覆盖

保留原版 UI 审批、更新、Client apply 失败后恢复、刷新重附着、停止、重启、移除与
拒绝的既有旅程，新增 Inspect 后共 32 个命名检查：

- 原版 Client 发布 Service、Event、Builtin、Slots、Theme 五种 Provider。
  完整 manifest 来自实际浏览器；这不是项目 Client 插件数量或固定 Loader 行数。
- Service / Event 紧凑目录及精确契约，Builtin 闭包符号，主题 token 和 light/dark
  要求；Slot 实际 topology、选中契约/occupants 与不存在的 root。
- Host 输入 schema 拒绝未知字段，未向浏览器发送该查询。
- 两个真实页面独立回答同一 Theme 查询；实际 Remote 请求/响应显示一份 accepted
  true、一份 accepted false，相同 requestId，只结算一次。
- 审批后的动态 Client 注册 Provider、主题覆盖和 overlay Slot；查询返回真实当前
  版本和调用 Session。v1 → v2 → 失败版本 → v4，对各代次和卸载后 live 目录核验。
- 等待中的实际 Client Provider 收到 Host resolved/cancel 广播，触发自己的 abort
  listener，不提交迟到结果；Host pending 与调用方 signal relay 清空。
- 返回不符合 outputSchema 的数据或抛出异常，浏览器发出相应结果，但 Host 不接受
  为有效答案；查询继续 pending，显式取消后清理。按原版保留 Inspect 业务取消文案，
  不将已抛出的业务错误强改成 Tools 的成功后取消分类 ABORTED。
- 页面刷新后 Host 存活，页面局部动态 Provider / 主题覆盖 / Slot 消失；原版 UI
  重附着后恢复，停止和移除后再次清理。所有发布查询各有一次 resolved。

## 验证与历史失败

```powershell
$env:FROZEN_OUTPUT='tests/fixtures/remote-frozen-source-observations.json'
node scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.remote-frozen.config.mts
node scripts/native_web_browser_oracle.mjs --browser <development-chromium.exe> --output .goose/out/native-inspect-browser-stable.json --inspect true
$env:DSH_TEST_CHROMIUM='<development-chromium.exe>'
.venv\Scripts\python.exe -m pytest tests/test_native_web_browser.py tests/test_typert_dispatch.py tests/test_remote_events.py tests/test_cordis_inspect_registry.py tests/test_cordis_tools_full.py -q
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/native-inspect-final.xml
```

原版冻结容器 probe 为 1 个 Vitest / 16 个观察，退出码 0；日志
`.goose/out/remote-frozen-source.log`。最终专项 **98 passed / 27.21 秒**，退出码 0；
`.goose/out/native-inspect-focused-final.log`。其中两个浏览器 lane 实际运行，不能算成
32 个新增 pytest；新增 32 项冻结边界/源观察测试与一个额外浏览器参数化实例。

首次故障证据保留在 `.goose/out/native-inspect-browser-first.json`。随后两个探针
断言错误（Slot register 在源目录为属性签名、Inspect 取消保留业务错误）按实际
源码和运行结果修正；未修改产品以满足错误断言。原始输出仍保留。

一次早期双页面报告在运行检查阶段标记 passed，却在随后 Host 关闭时产生 CPython
3.8 Proactor accept/_attach 与 fail-loud 错误；该报告不作为最终通过证据。
探针现先关闭测试浏览器，避免活跃 Client 在 Host 退役时继续重连；然后正常关闭
Host，并将其退出码与最终 stderr 纳入 passed 判定。最终专项的两个 lane 均正常
退出且无 Host stderr。这是验证器清理与结果判定修复，不声称修复 CPython 或产品
全部网络关闭竞争；未隐藏诊断或切换事件循环实现。

最终独立浏览器 `.goose/out/native-inspect-browser-stable.json` 为 **32/32 passed**，
Host exit 0，无 Host stderr、两个页面的非预期 browser exception 或主页面 HTTP 失败；仅保留既有
故意失败的 Client apply 的一条预期 console.error。35 个实际广播查询均结算一次。
主页面捕获的 Inspect Remote POST 为 syncInspectManifest 13 次、resolveInspectQuery
34 次；两页面合计记录 35 份实际 resolve 请求/响应，其中 32 份接受、3 份拒绝
（迟到页面、无效输出和提供者失败），等待取消不发送迟到响应。
另有一次输入拒绝发生在广播之前，因此不计为 35 个已发布查询。

浏览器报告绑定的 15 个输入哈希、冻结源 fixture 的 7 个输入哈希均与最终文件一致。
Python 3.8 py_compile、Node --check、git diff --check 和 migration check / ready
通过，reference 无修改。运行环境仍为当前 Windows / Python 3.8.10；原版 probe
使用 Node v22.22.2。记录检查与哈希核验不认证全部产品语义。

最终全量为 **4572 passed、2 skipped、1 warning / 426.59 秒**，退出码 0；JUnit
4574 tests，failures/errors 均为 0。日志与 JUnit 为
`.goose/out/native-inspect-final.log` / `.xml`。两个原版浏览器 lane 均实际通过。
两个 skip 为既有 Windows 不适用 POSIX 场景，warning 为既有 Windows Proactor
transport 的事件循环关闭后析构诊断；pytest-asyncio fixture loop scope 提示与测试
HTTP 连接中止/重置诊断保留，不宣称零 warning。回归期间保持产品/脚本/测试/fixture
与浏览器输入稳定，仅补充文档；最终哈希再次核对一致。

## 交付与剩余迁移

继续 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：固定
Python 3.8.10 Portable，Host 插件由 profile/Loader 装配，目录/ZIP、源码升级回退
已有实现。创造模式源码导出、依赖闭包、可选 Client 联合安装、多来源获取和最终
发行仍须实施。本轮未加生产依赖、QuickJS 或 Node Host，未发布或重建 Portable。

本轮真实浏览器 Inspect 覆盖上述场景，未认证所有并发断线/HMR竞争、完整 Client
Guard、experimental Inspector/CDP、任意原版 JS Host/Workflow 或其他未验收模块。
Win7 真机与目标浏览器验证保留用户暂缓状态，accepted_upstream 未建立。
