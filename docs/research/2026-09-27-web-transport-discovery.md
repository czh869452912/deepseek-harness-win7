# 当前目标的 Web 传输归属

固定目标：`cd5ef8148158c3a752a658978873241fdf8e2bbc`。这是源码盘点与官方基准，不是 Python Web 对齐验收。

## 已确认的依赖链

`WebServer + Credentials → Connection → Typert Registry/Gateway → Remote controllers → Session/Workspace projections → browser clients`

| 层 | 当前上游 | 本地现状 | 下一闭包 |
|---|---|---|---|
| HTTP owner | [Connection apply](../../reference/packages/client/connection/src/index.ts) 注册 `/api`，先 Host/Origin fence，再浏览器认证，再 bridge | [ConnectionService](../../dsh/host/connection/connection.py) 已有 trust、cookie/token 和 URL；路由仍由 ApiProxy 注册 | 保留已有认证语义，迁移路由所有权和 body limit |
| 通用 RPC / Fetch | [rpc-host](../../reference/packages/client/connection/src/rpc-host.ts) 的 `rpc.handle`、`rpc.intercept`、`fetch.register` 属于读取服务的 caller fiber | 本地 Connection 没有这些注册接口 | 先定义 owner、重复注册、卸载、错误及精确路由优先级，再接消费者 |
| Unary envelope | [rpc.ts](../../reference/packages/client/connection/src/rpc.ts) 使用 client-request/type/rpcId/method/payload 与 server-response/result | 旧 ApiProxy 已使用类似 envelope | 相同外壳不证明 endpoint、参数或取消等价；逐个匹配 Typert Remote schema |
| Gateway | [gateway/index.ts](../../reference/packages/api/gateway/src/index.ts) 通过 Connection 在 `/api` 拦截声明端点 | 本地仅有局部 Typert lookup registry，未找到对应完整 Gateway | 与 Remote、类型注册和 controller 共同交付，不能单加 HTTP 转发别名 |
| Stream | [stream-protocol.ts](../../reference/packages/api/gateway/src/stream-protocol.ts) 指定 `/api/remote.mux` WebSocket | 本地 WebServer 有 upgrade 注册基础；旧 ApiProxy 仍使用双 SSE | 对齐 open/item/end/error/cancel、代际和重连，再迁移前端；不能仅替换 URL |
| Host→Client invocation | 同一协议的 `$events`、`$events/result`；ready 带 clientId/host，waterfall 带 eventId/agentId | 旧 `/api/respond` 是另一套集中式应答路径 | 问题、审批等消费者随事件关联和取消契约迁移；不预先认定两者等价 |
| 装配 / 浏览器 | [web-app patch](../../reference/packages/bundle/web-app/cordis.patch.yml) 包含 session-controller、workspace-controller、settings-controller 等 | 固定的已入库前端与大量旧域处理器仍在使用 | 依赖上述 Host 服务后，从目标源码重建前端并做浏览器真实流程 |

在当前 `reference/packages` 中搜索旧 `events/mux`、`events/host`、`/api/respond` 没有发现它们作为当前传输端点的实现。因此旧文档中“双 SSE + respond 就是一比一”的结论不能继续用于本目标验收。保留旧消费者期间，只能称为本地兼容面。

## 已运行的官方基准

```powershell
node --expose-internals scripts/oracles/official/node_modules/vitest/vitest.mjs run --config scripts/oracles/vitest.web-protocol.config.mts
```

4 个原样上游套件、71 项通过：Connection `api-request-trust.host.spec.ts`、`rpc-schema.host.spec.ts`，Gateway `stream-protocol.host.spec.ts`、`remote-event-protocol.host.spec.ts`。这是确定性协议和信任基准；没有运行整个 Gateway、浏览器、真实 WebSocket 或 Python 双侧对照。

## 实施顺序与退出条件

1. 先闭合 Connection 的 caller ownership、注册/卸载和 HTTP bridge 契约；一起修改 WebServer、认证和直接注册消费者。
2. 再闭合 Typert Registry / Gateway / Remote controller 的类型、identity lookup、unary 和 stream 契约。Session 端依赖 Agent factory 与后续 Session replay/projection，不先按旧 handler 逐个翻译。
3. 用真实 HTTP/WebSocket 和受控中断证明鉴权、取消、重连、代际隔离、错误 envelope；输出双侧原始观察。
4. 最后重建目标前端，跑创建、提交、工具、取消、问题/审批、恢复与重连；同一流程再跑 portable。

连接层可以先做源码和 fixture 工作，不能把“已定义协议”标成“已实现 Gateway”。预编译前端的固定字节门禁继续有效，但不替代这里的目标源码构建与浏览器验证。Win7 真机验证仍单列暂缓。
