# HTTP 重定向边界

本部分固定原版 `cd5ef8148158c3a752a658978873241fdf8e2bbc` 和开发观察 Node22.22.2。任务 `MIG-HTTP-REDIRECT-035` 仍 running；没有认证完整 HTTP、TLS、URL、代理或全项目。

## 实际差异

两个自有 loopback 服务通过真实 DeepSeekAdapter 观察同源/跨源301、302、303、307、308，20/21跳、重复URL、跨源后返回及改写后保留，共15组。原生默认 urllib redirect 把跨源 Authorization 带给目标，拒绝 POST307/308，并使用不同跳数/HTTP错误分类。修改前只有4组与实际原版相同，修改后15组完整请求和终态一致。

再补14组真实 pinned Fetch 与共享 HTTP carrier 观察：Cookie/Proxy-Authorization/Host、body headers、PUT/HEAD、URL credentials、非HTTP协议、相对路径/空格/query/fragment、跟随后取消及未结束的redirect响应体。观察发现原生初始Host override与带userinfo目标也不一致；修复后29组完整对象匹配。局部错误文字不比较，raw Fetch 的网络失败按同一 carrier 分类记录，不用异常过滤豁免业务失败。

最初 Source 诊断缺少必需 prepareExtensions，只得到零请求 REQUEST_EXTENSION；该 `source-v1` 不是 HTTP 对齐证据，原始记录保留。修正后 `source-v2` 实际15组、`source-v3` 实际29组；对应原生 before/after 记录在 `.goose/out/acp-a4-work/http-redirect-*.json`。

## 实现与验证

新的 Fetch redirect handler 保留307/308 body、按方法改写301/302/303、清理跨源敏感头、拒绝已观察不支持的目标并统一20跳预算；跟随前关闭旧响应，不读取可能永不完成的旧body。初始 Request 使用私有复制，不修改调用者的头部。既有 owned socket/DNS/idle/cancellation 管理负责每条后续连接。

正式双侧驱动29项 matched；84项 Source/DeepSeek/Pi/文件/图像定向回归通过，日志/XML为 `http-redirect-focused-v1.*`。全部29配对回归、8损坏回执拒绝及7解压来源拒绝均进入mandatory，下一门禁496 lane、十八组1237原样 Source断言、55配对。实际解压通过选定root的Python-I运行并校验完整导入模块哈希；不能以宿主输出代替解压运行。

门禁及调度/settings/首错排空消费者607项通过（226.63秒），记录为 `http-redirect-gate-v1.*`；migration check通过。新干净完整候选和解压/原版浏览器仍待执行。完整 WHATWG URL/Unicode/IDNA、TLS/proxy/compression/framing和其他provider全部实例继续独立开放，没有新增 Source bug 绕过；Win7实机仍按用户决定延期。
