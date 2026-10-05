# 测试浏览器扩展隔离

完整候选 `6b82aebba5fd4cad42b778ce518ea0bfa0aba912` 被拒绝：Python3.8.10 全量6890 passed、1 failed、6既有 skipped、1既有 Proactor warning，1688.90秒。唯一失败为原版浏览器安装 Python Web 包旅程；十二个业务步骤、六条严格 RPC 回复通过，宿主错误及失败请求为空，但 CDP 捕获外部 Zotero Connector 的 Runtime 和 console 错误。

执行上下文为 `chrome-extension://nmhdhpibnnopknkmonacoephklnflpho`，名称 Zotero Connector，isolated world。异常来自其 `inject/inject.js:96`，console 指向 `zotero.js:291` 的 “Could not establish connection. Receiving end does not exist.”。证据证明外部脚本执行，不证明此前升级启动取消、普通 ReplaceFileW1175 或 Zotero 进入私有 profile 的安装来源。

确切拒绝 ZIP SHA256 `fef703b79a29db409281f64b3ebaae51ca88df46abd8f3980bda4df982d80a8a`，输入 SHA256 `2ba056bbafdc0d8fe090ffbcc67bc0fd90eef02d0fd4f26066411b0a8349e0b8`。产物、XML、日志、原始浏览器/网络观测保留于 `.goose/out/session-storage-clean-6b82aebb/`。独立 Source、配对和实际解压阶段没有执行；没有重跑未改候选或签收。

受控真实 Edge 实验在独立临时 profile 加载自己的 Manifest V3 扩展，让 content script 设置 DOM 标记、console.error 并抛出异常。原启动条件确认扩展 ENABLED、标记和两种错误均真实出现；仅添加 `--disable-extensions` 后扩展 inventory 为空、无标记/扩展 context。两种条件下，页面自身的 console.error 和抛出异常仍被 CDP 捕获。首次预检回执为 `.goose/out/acp-a4-work/browser-extension-isolation-preview-v1.json`，不是产品验收。

三个原版/Portable 验收浏览器统一使用 `isolatedBrowserArguments`。扩展隔离只影响各自新建的测试浏览器进程，不修改用户 profile、注册表或原版前端。新的真实浏览器 lane 重做扩展启用/禁用和应用错误实验，实际核对进程命令行、inventory、context、DOM、console 和 Runtime；没有按 URL 过滤报错，既有业务零错误断言不变。

下一完整冻结门禁增加到444必需 lane，仍为十八组1237原样 Source 断言及54实际配对驱动。通过全量、新鲜 Source、配对与真实隔离解压之前，031/032/只读差分/033仍未签收，整体 `accepted_upstream` 为空。

定向验证：真实扩展隔离、三种原版 Native lifecycle、原版 Python 安装包和导航/关闭回归25项通过，61.39秒；门禁拒绝规则及创意包 build/host/session 升级回滚571项通过，343.76秒。日志分别为 `.goose/out/acp-a4-work/browser-isolation-focused-v1.log` 与 `browser-isolation-gate-v1.log`。迁移 check 有效、ready 无待领取项，均不等同完整验收。

修改后的新干净候选 `1f180e40` 完整门禁通过：6892 passed、6既有 skipped、1既有 warning、0失败，444必需lane/十八组1237断言/54配对/真实解压和原版浏览器均通过。扩展隔离有实际门禁证据，且不归因旧启动取消或1175；完整存储/并发批次的有界签收见 `migration/reviews/SESSION-STORAGE-CLOSURE-20261005.md`。
