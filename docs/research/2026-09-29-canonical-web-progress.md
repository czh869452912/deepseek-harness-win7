# 正式 Web 对齐实施记录

固定目标：`cd5ef8148158c3a752a658978873241fdf8e2bbc`。目标是直接使用原版 Web 前端，Python 后端按当前 Connection / Typert / Remote / WebSocket 契约提供能力。旧 ApiProxy、双 SSE 业务桥不作为实现后门。仅 Windows 7 / Python 3.8 的宿主适配可以偏离上游实现，必须保留行为验证。

## 已完成部分

- WebServer 激活等待真实 bind；OS 分配端口通过服务公开，绑定失败不发布服务。插件卸载关闭普通 HTTP 请求、升级连接并等待请求任务退出。
- 正式 `web-app` runtime：提供 bind 后的 `webRuntime`，挂载原版静态产物，提供 Web 提示和无 token 的 shell URL，在完整启动成功后公告认证 URL；SSH 抑制浏览器启动，提前卸载抑制公告。
- Windows LAN 地址通过兼容 Win7 的 IP Helper 枚举；浏览器交接使用脱敏环境中的 Python/ShellExecute，无 Node 运行依赖。POSIX 使用 getifaddrs。
- `cordis-client-runner` 的 host half 按原版为空；这是原版浏览器插件的装配登记，不是替代 host runner 的占位实现。
- 验证：模块注册 54 passed；runtime、真实 HTTP/WS、WebServer 定向 17 passed（已有 Windows asyncio transport 清理 warning）。本机原生网卡枚举已执行。

## 进行中 / 必须完成

1. client HMR 和 api-remotes 事件桥；所有异步资源随插件卸载。
2. Session / Workspace / Settings / Credentials controllers，真实类型 artifact、取消、错误及 projection 消费。
3. session-reference、session-log-export、动态 Cordis host runner。
4. 原版前端的可重复构建与来源校验；移除旧 Web carrier 及只证明旧入口的测试。
5. 正式 profile 的浏览器旅程：创建、响应流、工具、取消、问题/审批、历史恢复、断线重连；全量回归与便携包验证。

当前不是已验收的可用 Web 入口。migration check / ready 已运行；固定记录有效不等于本批次 parity 认证。不推进 accepted_upstream，不复用旧 acceptance 为新代码背书。Win7 真机与目标浏览器验证仍单列。

## 第二部分：前端 HMR 与应用事件桥

- 新增正式 api-remotes：按上游白名单转发事件；有 Agent scope 的问题/审批交给 Gateway，由客户端 result/next 决定返回或继续 waterfall。源在启动窗口卸载也会释放监听。
- 新增 client-hmr：按 artifact baseline stat polling；提供原版 `/plugins/events` 的 graph / rebuilt 帧，文件短暂缺失后重试；释放连接、路由、监听与轮询任务。
- 定向验证：事件桥、RemoteEvents、插件注册 61 passed；真实 SSE 与 client-modules 契约 31 passed。全量测试正在运行，最终结果另记。
- 这里没有证明 Web 全链路可用。模块表仍需从固定 roster 切换为 Loader 的活跃来源；业务 controllers 尚未接入。
