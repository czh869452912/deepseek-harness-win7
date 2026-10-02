# 当前迁移门禁补齐：2026-10-02

## 范围与边界

- 固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，产品基线 `1d5d965de1c7e08c00cbd1fd5227d2503d28444f`。
- 本轮推进审查中的 P0：无凭据原版浏览器验收、当前统一发行门禁、证据与正式任务记录。未授权提交，不创建分支或提交。
- 原版 React/TSX/CSS 和 frontend-inputs 固定资产保持不变；不以修改浏览器业务代码适配 Host。
- `MIG-CURRENT-RELEASE-GATE-003` 当前 running，无 clean-candidate passing acceptance；旧 integrated 记录保留历史范围。

## 实施

- 共享浏览器引导助手剥离继承 API/OAuth 凭据及用户 DSH_HOME/PYTHONPATH，只通过可见“Configure later / 稍后配置”按钮推迟配置。首次启动仍必须出现并真实关闭弹窗；重复加载在有限网络请求收尾后允许原版合法无弹窗，但要求根应用可交互。
- 插件旅程在主动重载、关闭页面及 Host 重启前等待有限请求收尾，不过滤 console/error，也不将取消导致的错误伪造成通过。
- 门禁要求 Windows/Python 3.8.10、Node 22.22.2、真实 Chromium、完整测试中五条原版浏览器及五个已构建 Portable profile 不跳过。
- 新鲜执行四组原版 Vitest 配置、24 个已选双侧驱动及原始 Cordis / 精确 C58 适配验收；范围是所选契约，不是所有上游测试 parity。
- 构建实际 ZIP，再用 ZIP 内独立 Python 和原版浏览器验收；源码快照、固定原版、候选提交、回执及 ZIP 哈希绑定同一运行。
- 默认拒绝 dirty candidate；`--allow-dirty` 即使验证通过也仅 development-preview / publishable=false。失败替换旧 summary，CI 校验通过且哈希相同才上传回执指定的 ZIP。

## 验证记录

原版浏览器 / 引导助手 / 发行门禁专项回归：**82 passed，0 skipped，0 failed，186.98 秒**，包含五条真实浏览器旅程；见 `.goose/out/p0-browser-settled.xml` 和 `.log`。首次无凭据弹窗检查保留，合法的重复加载无弹窗不再被误判；请求收尾后仍要求 errors / consoleErrors / requests 为空，未过滤错误。

2026-10-03 完成冻结输入统一门禁：

```powershell
.venv\Scripts\python.exe scripts/verify_release.py --allow-dirty --browser "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --output-dir .goose/out/p0-current-gate
```

- 完整回归 **4775 passed、6 skipped、1 warning，1050.09 秒**。五个原版浏览器和五个 Portable profile 必需用例全部执行；六个跳过只涉及四个 Windows 符号链接权限及两个 POSIX 语义用例。
- 四组固定原版 Vitest：consumers 80、agent-lifecycle 100、session-recovery 197、session-projection 100，合计 **477 passed**；这是原样源码基线，不等于 477 个 Python parity 场景。
- **24 个双侧驱动全部通过其既有精确门禁**；未扩大原版 bug 例外。Cordis raw 保留 **66 matched + C58 原生语言差异**，独立 exact-signature acceptance 通过。
- 实际 ZIP 在中文/空格临时路径解压，以 ZIP 内 Python **3.8.10** 运行 **13 步**隔离旅程；原版浏览器 **5 步**通过，使用 `/api/remote.mux`，runtimeStderr / Host errors / browser exceptions / consoleErrors 均为空；校验 **119 个前端文件**。
- 回执 `.goose/out/p0-current-gate/summary.json` 为 **development-preview / publishable=false / worktree_dirty=true**。候选仍是基线提交加未提交修改，没有 clean-candidate 发行证书。
- ZIP：`dist/dsh-win7-portable-v0.1.0.zip`，SHA256 `2ca39d22a3a1c77712a32471fbd5d9bbd7fefde12591f047fe06111a2843a3eb`。它是本轮开发验证产物，未发布。
- 门禁结束时源码输入快照、产品 HEAD、固定原版 HEAD/工作树检查均通过。本节及任务 next_action 在运行结束后补记；不可把随后补记的文档冒充该运行已冻结的输入。程序、测试和原版资产未再修改。

诊断仍需诚实保留：完整 pytest 有一个 Python 3.8 Proactor 析构 `Event loop is closed` warning；pytest 结束后还有两个 HTTP 测试线程 `WinError 10054` 连接重置诊断，退出码为 0，未导致测试失败，具体归属/根因仍待调查。这不等于所有关闭诊断已清除，也不应误写为原版 bug。解压 Portable 专项自身的 Host/runtime/browser 错误字段为空。

此前审查日志和本轮失败日志保留在 `.goose/out/migration-audit-*`、`.goose/out/p0-browser-*`；本轮通过日志、原始观察、JUnit、输入清单及产物回执在 `.goose/out/p0-current-gate/`。这些诊断与开发预览不是干净发行候选验收。

## 后续验收

2026-10-03 用户授权按完成部分提交；P0 初版为 `134a6fd6`。首次 clean gate 的全量结果 **4774 passed、1 failed、6 skipped、1 warning**（1065.09 秒），Host export 浏览器出现 inspect/inventory 的 `Failed to fetch`；回执为 failed / publishable=false，保留 `.goose/out/p0-clean-gate/`。不能把此前绿色 preview 视为 clean 发行验收。

复现诊断 `.goose/out/p0-host-trace-3.json` 记录了 API abort 与失败阶段；新观察器保留网络取消、页面代际和 console 上下文，不过滤错误。重载助手新增 performance.timeOrigin 变化检查，避免用旧文档 DOM/交互性当成已重载；对应正反单测通过。最终稳定性与完整门禁需重新验证，不能仅凭三次局部成功宣称根因全部消除。

进一步复跑仍出现启动期 abort，因此没有仅靠 observer 等待宣布修复。已确认另一项 transport 根因：WebServer 每个普通请求后关闭 socket，而 identity/Content-Length 响应没有宣告 Connection: close（甚至能保留 keep-alive），HTTP/1.1 客户端会复用正在关闭的连接。新增三项头部用例及真实 GET→POST→POST 标准客户端探针，修复前 **4 failed**，真实客户端复现 WinError 10053。现在普通响应统一声明 close 并去除大小写重复项；SSE 仍按 body 生命周期保持打开，WebSocket upgrade 使用自己的原始 writer，不受此处修改。Node 式持久连接/pipelining 性能不据此宣布迁移完成；该单请求 carrier 的合法关闭语义单立 `CON-WEB-HTTP-RESPONSE-LIFETIME@1`。

关闭语义修复后的专项 `.goose/out/p0-acp-root-fixed.xml`：**121 passed，0 skipped，1 个既存 Proactor warning，245.61 秒**，含五条原版浏览器、HTTP finite/upgrade/socket journey、发行 helper 与 ACP/原版例外索引。准备执行冻结输入完整预览，随后逐部分提交，再对干净候选重跑正式本地门禁；正式回执未产生前不改 task 为 verified/integrated。

原版八类 bug 精确索引已回填 `migration/upstream-bug-exceptions.json`；ACP prompt 归属修复的实际进展另见 `2026-10-03-acp-prompt-ownership-progress.md`。下列原始计划保留为当时状态，不替代本节后续实测。

2026-10-03 根因修复后的冻结预览 `.goose/out/p0-acp-final-preview/summary.json`：**4800 passed、6 skipped、1 warning，1029.59 秒**；十条必需浏览器/Portable lane 全部执行，四组原样测试合计 **477 passed**，24 个双侧驱动和 Cordis 精确 C58 适配门禁通过。实际解压 Python 3.8.10 和原版浏览器旅程通过，前端资产未修改。状态仍为 **development-preview / publishable=false**；ZIP SHA256 为 `2cdcd8a07a32c96aa7fd640f0ab4fcac96b75e212db5a19b7a1cf0aa6ab8fa79`。既存 Proactor warning 和 pytest 结束后的 HTTP 测试连接重置诊断未清零，不列入原版例外。本段是运行后补记；随后按用户授权分部分提交，再冻结干净候选验收。

随后按部分提交：HTTP/观察器 `b15aff84`、ACP `b85e03f8`、例外索引 `623a615a`。干净产品候选 `623a615a34d6e81a0d6fc9230c836a12017ba65c` 的统一门禁 **passed / publishable=true / worktree_dirty=false**：全量 **4800 passed、6 skipped、1 warning，1042.57 秒**；十条 lane、477 项原样源码测试、24 个双侧驱动、Cordis 精确适配及实际解压旅程通过。实际 ZIP SHA256 `b6fe79ebf2cf427669976d36988a1feb3002062408cc4f353cf36f02ce61c889`；收据 `.goose/out/p0-acp-clean-gate/summary.json` 与版本化证据包绑定该候选，未发布。当前门禁/HTTP 范围和 ACP 归属任务已集成；完整报告见 `2026-10-03-current-candidate-closure.md`。后补台账不伪装成本次冻结输入，也不触发重建旧 ZIP。

1. 本地完整预览通过后，由用户授权提交，干净检出重跑统一门禁与远程 Actions，绑定该候选正式验收；本轮不自动提交。
2. 下一闭包优先 ACP 多 Session turn/end 归属缺陷，双侧复现、修复并纳入契约回归。此缺陷本轮尚未修复。
3. 逐个收敛 Session/Web 正式契约与已实现代码的记录差距；建立原版 bug 的精确例外台账，不扩大既有绕过范围。
4. JS package/OAuth 完整迁移和 Win7 真机/浏览器验证独立推进；当前 Windows 浏览器与 extracted Portable 成功均不能证明这些项目完成。
