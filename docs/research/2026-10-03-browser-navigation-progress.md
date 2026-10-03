# 原版浏览器导航代际复验

ACP 配置及 ordered output 候选 `155bacd3` 的完整 Python 3.8.10 回归为 **4926 passed、1 failed、6 skipped、1 warning**。唯一失败是 Host placement 的真实安装/升级/回退浏览器旅程：17 个业务步骤已执行，但回退后启动请求被取消，原版 inspect/inventory 的 console error 使验收失败。完整失败门禁保留于 `.goose/out/acp-config-clean-gate/`；浏览器原始 JSON 保存于 `.goose/out/acp-next/config-gate-browser-failure.json`。失败不归入原版 bug 例外。

观察器显式 Page.navigate 的旧条件只等待 URL 或 shell，缺少文档代际和加载完成检查；已存在的 reload 代际等待不覆盖它。共享 navigateOriginalPage 现要求 performance.timeOrigin 改变、目标文档 URL 正确且 readyState 为 complete，CDP 返回导航错误时立即失败。所有三个浏览器观察器使用同一条件，关闭业务页面也确认新 about:blank 文档后才允许更换 Host。原版前端、console error 断言与请求失败断言不变。

初次专项反例均通过，但真实五条 lane 失败于过严的完整 URL 比较。canonical BrowserAuth 会把含 token 的启动地址重定向到普通根地址，因此目标比较只移除协议定义的 token 参数；不任意忽略其他查询参数或目的地址。这个观察器错误与原始失败均保留原始日志，不删除失败再声称首次通过。

受控反例检查旧文档、错误目的地址、仍在加载、新文档完整加载、认证 token 重定向及 CDP 导航错误。专项日志为 `.goose/out/acp-next/navigation-auth.log` 与对应 JUnit；完整新干净候选门禁仍须复验，不能从一次专项通过推定原始间歇失败已完全消失，也不能签发全部 ACP、完整迁移或 Win7 认证。
