# Win7 运行时性能与前后端传输审查

日期为 2026-11-25。原版固定在 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。Win7 审查基于 `199ef548` 及工作区已有的 JSONL、终端分页和本地测试修改。实测使用本机较新 Windows 的 Python 3.8.10 x64。本机对照覆盖实际 Python WebServer、Electron 22.3.27 的 Node 16.17.1 与现有 v3 管道实现，以及兼容 JSON 编码环节。完整上游应用与 Win7 目标机的端到端数据仍待采集。

## 传输架构

| 场景 | 固定上游 | Win7 实现 |
| --- | --- | --- |
| Web 的一次性 RPC | Node HTTP → Connection → Gateway → Remote | Python asyncio HTTP → Connection → Gateway → Remote。每个普通 HTTP 请求关闭连接 |
| Web 的 Remote 订阅与双工流 | 共享 `/api/remote.mux` WebSocket，逐逻辑流取消，入站按字节限额，异步压缩大帧 | 同一协议与限额模式。wsproto 在 Host 事件循环内运行，JSON 投影与压缩也在该循环 |
| Desktop 普通资源与 RPC | Electron 主进程直接服务启动 HTML 和主要静态资源。其他请求转发至有认证的 loopback HTTP Host | `dsh-app:` 经 Electron 22 主进程把应用资源和 RPC 转成 v3 管道帧，由独立 Python Host 作答 |
| Desktop Remote 流 | 渲染器按 `streamBaseUrl` 建立一个经认证的 loopback mux WebSocket | 注入的 `openStream` 被原版 Connection 采用。每个逻辑流通过一次 `POST /.dsh/remote-stream` 接收 NDJSON。物理传输仍集中在同一对子进程管道 |

Web 的 `/plugins/events` 是客户端 HMR SSE。Win7 Desktop 关闭 WebServer 和客户端 HMR，沿用私有管道。原版 Gateway 同时保留本地流扩展口和 WebSocket，Connection 在存在 `openStream` 时从本地扩展口打开流。Win7 注入只接收 endpoint、payload 和 signal，Python 路由明确传入空 uplink。当前 Desktop 正常的下行订阅由这个扩展口提供。需要独立 uplink、窗口或完整双工生命周期的调用应单独验收。 [原版 Desktop 主进程](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/apps/desktop/src/main.ts#L797) · [原版 Connection 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/client/connection/src/client/index.ts#L233) · [原版 Gateway 流选择](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/api/gateway/src/client/index.ts#L233) · [Win7 Desktop 注入](../../apps/desktop-host/transport.js) · [Win7 Desktop 路由](../../dsh/host/desktop/runtime.py#L72)

### 版本限制与实现选择

- **Win7 / Electron 22。** Electron 23 起停止支持 Win7。原版较新的 Electron 外壳、`protocol.handle` 接口及 Node Host 布局与这里的兼容载体有关。独立子进程在原版也存在。Windows 7 上的旧 Electron 并未排除浏览器建立 loopback WebSocket 的技术可能性。若考虑统一 Desktop 和 Web 的 Remote 载体，需要在真实 Electron 22 验证 origin、cookie、端口所有权、断线恢复与关闭。 [Electron 23 支持范围](https://www.electronjs.org/blog/electron-23-0#dropping-windows-7881-support) · [原版 Desktop 转发和鉴权](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/apps/desktop/src/main.ts#L797) · [Win7 适配来源](2026-11-18-win7-desktop-current-scope.md)
- **CPython 3.8.10。** Windows 默认 Proactor，支持异步 TCP、子进程和相应的管道连接。Windows 的 Selector 事件循环缺少管道和子进程支持。当前 Python 进程对自身继承的同步 stdin/stdout 用执行器桥接，这是当前描述符和适配实现的选择。复用 HTTP 连接、使用更快的 JSON 编码、拆分回压、引入事件驱动的文件监听都可在 3.8 条件内设计。将同步阻塞 I/O 送进执行器能够隔离大部分等待，但执行器调度、共享线程池和 Python CPU 热点仍需单独测量。 [CPython 3.8.10 Windows asyncio](https://github.com/python/cpython/blob/v3.8.10/Doc/library/asyncio-platforms.rst) · [Proactor 实现](https://github.com/python/cpython/blob/v3.8.10/Lib/asyncio/windows_events.py) · [Win7 管道进程](../../dsh/host/desktop/process.py)
- **原版合同的成本。** 两侧都保留请求信封、Peer 权限、结果检查以及流的背压与取消。上游也会对常规 RPC 聚合有上限的请求体，Web 静态文件也使用整文件内容生成弱 ETag，慢 WebSocket 客户端也共享同一 TCP 连接。下面的优先级集中在当前实现额外付出的成本和已有复现。 [原版 HTTP bridge](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/client/connection/src/http-bridge.ts#L54) · [原版 FrontendStatic](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/host/frontend-static/src/index.ts#L90) · [原版 WebSocket 回压](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/api/gateway/src/stream-server.ts#L315)

## 主要发现

### 高优先级 · Desktop 共享管道造成跨请求阻塞

Node 接收每个流的 data 后写入该流的 64 KiB `PassThrough`。任意一个返回回压，Node 将暂停整个子进程 stdout。与此同时 Python 的所有响应帧共用一把锁，每帧经一次执行器提交执行 `write + flush`。流间只有流 ID，同一物理管道上的 header、data、end 和 error 都会排在受阻数据后面。请求方向还有所有流共享的串行写链，单流请求体队列为 16 项。传输为二进制，普通管道帧没有 Base64 膨胀。 [Electron v3 读写](../../apps/desktop/host-process.cjs#L55) · [Python v3 读写](../../dsh/host/desktop/process.py#L47) · [帧格式](../../dsh/host/desktop/wire.py)

使用真实 Electron 22 Node 模式运行生产 `DesktopHostProcess` 和 Python `serve`，以合成业务处理器替代 profile 启动。2 字节请求热态中位数 **0.465 ms**，P95 **0.656 ms**。让 4 MiB 响应暂停消费直到子进程 stdout 实际暂停，发出独立小请求，200 ms 后恢复消费。五次独立请求均在恢复后才完成，耗时 **204.5–209.4 ms**。这是共享流控引发的队头阻塞，普通小请求的平均管道延迟很低。

短期优先验证按流的有界额度或暂停机制。只把 `resume()` 提前会把阻塞转换为内存增长。已进入物理管道的大块数据仍会占据队首，因此还需要有界帧、调度和公平性。若要与原版收敛，单独验证 Electron 22 下的认证 loopback mux 方案，并用同一慢消费者场景比较。最小验收覆盖慢下载与独立 RPC/控制事件并发、取消、内存峰值和双向流。

### 高优先级 · Host 同步兼容 JSON 编码拉长事件循环

Remote WebSocket 普通项先经 `json_projection` 递归投影，再经 `stringify_json` 递归编码。后者逐字符串处理 UTF-16、UTF-8 和代理项，逐字典处理 JS 数字键排序，逐数字使用 JS 兼容格式。Web 的普通 JSON RPC 回包也使用这对函数。Desktop NDJSON 路径直接调用 `stringify_json`，其实际耗时需要按投影后的真实值另测。原版仍做数据验证与投影，最后交给引擎的 `JSON.stringify`。 [投影](../../dsh/typert/rpc_result.py#L75) · [兼容编码](../../dsh/cordis/json_text.py#L11) · [RPC 回包](../../dsh/host/connection/rpc_current.py#L10) · [原版 WebSocket 发送](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/api/gateway/src/stream-server.ts#L315)

同一 Python 3.8 进程对三组合成 Remote 事件各计时 40 次。对照在这三个输入上与当前路径产生逐字节相同的结果，计时含最终 UTF-8 编码。

| 帧字节数 | 投影与兼容编码 P50 / P95 | 紧凑标准库编码 P50 / P95 |
| ---: | ---: | ---: |
| 670 | 0.177 / 0.311 ms | 0.012 / 0.031 ms |
| 16,018 | 5.840 / 6.361 ms | 0.203 / 0.293 ms |
| 325,818 | 107.708 / 118.865 ms | 5.067 / 5.577 ms |

约 318 KiB 的单帧会占用该 Host 循环约 108 ms。这个量级足以推迟同期 RPC、心跳和后续流项。实际分位数还取决于生产帧类型和大小。可优先做有证明的快速路径或单次遍历，只复用通过类型和编码同值门槛的数据。差异测试需覆盖整数键排序、非有限数字、负零、安全整数之外的值、缺省与 null、代理项、二进制附件和规范日志。把不停持有 GIL 的 Python 工作简单移到线程会引入并发调度，收益需要复测。

### 高优先级 · Web 每请求建立 TCP 连接

当前 HTTP writer 强制 `Connection: close`，处理器和 socket 服务的上层均有关闭收尾。每次响应只处理一个请求，方法和 URL 的解析、路由匹配也有重复。原版用 Node HTTP server 管理连接，原版 bridge 在流式请求体未读完时才显式关闭。普通 Web 页面冷启动会并发拉取资源和 API，代理或 TLS 场景的重连代价需单独量化。WebSocket mux 在升级之后继续保持连接。 [Python HTTP 请求](../../dsh/host/webserver/webserver.py#L518) · [强制关闭](../../dsh/host/webserver/webserver.py#L719) · [原版 HTTP 服务](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/host/webserver/src/index.ts#L557) · [原版 bridge 的未读请求收尾](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/client/connection/src/http-bridge.ts#L97)

同一 Python 客户端顺序请求 180 次，预热 20 次，业务处理器只回 2 字节。当前 Python WebServer 使用 **180 个 TCP 本地端口**，P50/P95 **2.00/23.85 ms**。同机最小 Node HTTP keep-alive 使用 **1 个端口**，P50/P95 **0.084/0.270 ms**。Node 强制关闭对照同样使用 **180 个端口**，P50/P95 **15.26/16.32 ms**。三组数字反映这次 Windows 短连接实验，各端的关闭行为和尾部调度有差别，适合验证连接数量和尾延迟风险。完整浏览器的端到端速度比仍待测定。

启用 keep-alive 需要重做 HTTP 请求所有权边界。当前非流式 API 的断连监视会读到 EOF，可能读走下一请求。流式上传则通过 Python 3.8 `StreamReader._eof` 每 10 ms 探测，与业务 reader 保持单一读者。应先让 socket 生命周期独立通知，再针对完整读取、边界合法的请求分步复用连接。应校验完整 body、chunked、响应长度、429/413、取消、升级、idle timeout 与 SSL 关闭。 [Python bridge](../../dsh/host/connection/http_current.py#L66) · [现有重连回归](../../tests/test_webserver_connection_lifetime.py)

## 其他运行时路径

| 路径与证据 | 影响与验证重点 |
| --- | --- |
| **Web 压缩与流调度。** Python 在 loop 内逐帧压缩，发送前后的逻辑还重复计算 UTF-16 长度，入站文本也要重新编码以计算字节数。HTTP gzip 同步执行。原版 `ws` 大帧经过异步 deflate，HTTP 用 Node 压缩流。 | 长帧、连续会话快照和同一 loop 上的 RPC 会互相争用。用同一真实帧分布比较编码、压缩、压缩率、事件循环延迟和 WAN 带宽。合并长度计算时保持 JS UTF-16 阈值及心跳的活动语义。 [Python mux](../../dsh/typert/duplex_mux.py#L23) · [HTTP gzip](../../dsh/host/webserver/webserver.py#L735) · [原版流服务器](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/api/gateway/src/stream-server.ts#L315) |
| **Desktop 启动资源和大响应。** 原版主进程直接异步读前端 HTML 和主要静态资源。Win7 Desktop 把这些资源并入业务管道，部分静态文件在 Python 主 loop 同步整读。JSON RPC 二进制附件使用 multipart 字节，Python 组包把所有片段拼成单个 `bytes`，原版用 FormData Response 及流式 bridge。 | 把首屏资源、主题字体、大预览与普通输入并列记录。优先移出同步磁盘读取，测试大输出分页或流式组包，并保留路径归属、HEAD、内容类型和注入顺序。x86 需要同时看私有内存和峰值。 [Win7 资源读取](../../dsh/host/desktop/runtime.py#L105) · [Python multipart](../../dsh/host/connection/rpc_current.py#L10) · [原版 Desktop 文档](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/apps/desktop/src/web-document.ts) · [原版 multipart](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/client/connection/src/rpc-host.ts#L376) |
| **慢订阅与内存。** Python Remote events 的每个订阅者队列没有显式容量，WebSocket 的 uplink 有字节上限。原版浏览器 mux 也有逐流 Deque。 | 用挂起渲染页和多订阅测试积压量。状态快照可评估合并，事件日志、请求/回答和须分页回放的序列要保持顺序及完整性。 [Python events 队列](../../dsh/typert/remote_events.py#L48) · [Python WebSocket uplink](../../dsh/typert/duplex_mux.py#L141) · [原版浏览器队列](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/api/gateway/src/client/stream-client.ts#L397) |
| **旧 Chromium 的渲染。** 锚点 polyfill 的文档级 MutationObserver 触发签名扫描，命中变化时重建定位。颜色 fallback 从文档元素读取计算样式。能力齐备的浏览器可以绕过 fallback。 | Issue #14 的侧栏「更多」可作为无 Remote 往返的对照。以同一工作区记录点击到 React 菜单挂载和首次正确绘制，同时统计 compat refresh、节点数和长帧。将 Host RPC 作为另外一个同机对照。 [锚点兼容](../../dsh/host/browser_compat/anchor-runtime.js#L50) · [颜色兼容](../../dsh/host/browser_compat/compat.js#L289) · [Issue #14](https://github.com/czh869452912/deepseek-harness-win7/issues/14) |
| **HMR 空闲 I/O 和终端。** Python Host 配置 watcher 每 20 ms 轮询，每轮同步 stat，并为保留同尺寸同时间戳更新而读配置内容。递归观察也进行同步目录和元数据操作。原版用 Chokidar 文件事件。WinPTY 通过 10 ms 轮询等退出。 | 先采样空闲一分钟的每进程 CPU、文件打开次数、循环延迟。可评估 Win7 的目录变更通知和低频复核，保留原子替换、短暂删除、相同元数据修改和卸载。最近的滚屏小页优化已验证，本轮重点是持续唤醒。 [Python HMR](../../dsh/cordis/hmr.py#L485) · [根目录扫描](../../dsh/cordis/hmr_root_watch.py#L71) · [原版 watcher](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/boot/hmr/src/watch-config.ts#L47) · [WinPTY](../../dsh/subprocess/winpty.py#L133) |
| **会话冷读、热读与迁移。** 当前 cold scan 已减少字节复制。完整读仍包括解压、JSON 解析、事件验证和不可变对象构造，部分工作在 Host loop。按修订的缓存和分批让步已经存在。原版也解析及验证事件，迁移验证有 Worker 隔离。 | 用同一长会话测内容读取、恢复对象、投影、回包和浏览器渲染各段。分别记录 zstd/普通、缓存命中、会话列表元数据成本和与另一 RPC 并发的延迟。避免把不同路径的缓存读和 cold scan 混在一个数字里。 [Python JSONL 后端](../../dsh/session/jsonl_backend_current.py#L687) · [准备会话缓存](../../dsh/session/observation_current.py#L62) · [原版迁移验证](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/session/session-persistence-jsonl/src/migration-verifier.ts#L108) |
| **模型流与 Office。** Python 模型 HTTP 使用受控阻塞 I/O、读线程、按需单槽队列和跨线程唤醒，取消观察和部分 DNS 另有线程。原版 DeepSeek 使用原生异步 Fetch。Office 回退按调用启动浏览器进程和本地 HTTP 服务，部分二进制结果经 Base64 JSON，原版 Kit 按 slot 复用 converter。 | 模型测固定本地模拟服务的首帧、连续间隔和并发线程数，避免把远程模型延迟算进 Host。Office 测首转换、第二次转换、完全缓存命中、峰值内存及同时小 RPC。即使仅考虑 ASCII Base64，编码体积约为原字节的 4/3，实际内存还包含 JSON、解码副本及浏览器进程。 [Python 模型桥](../../dsh/llm/stream_bridge.py#L68) · [原版模型 Fetch](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/llm/llm-deepseek/src/adapter.ts#L142) · [Python Office carrier](../../dsh/office/browser_carrier.py#L131) · [原版 Office slots](https://github.com/deepseek-ai/deepseek-harness/blob/38a6a5c965aa99ab525161efb7cc5cf1fe62fced/packages/document/office-kit/src/index.ts#L366) |

## 分阶段验收

1. 在 Desktop 固定做一组慢流加互不相关的小 RPC 和业务事件。记录每流首字节、P95、排队字节、取消结算和进程私有内存。这组用例可直接判定流控改动是否解决共享队头阻塞。
2. 在 Web 和 Desktop 记录真实交互的 frame 大小、编码、压缩、写入、客户端解析和显示间隔。选两种典型 workload，长会话恢复和连续模型增量。统计 P50/P95/P99，借此选择编码快速路径的上限和必须保留的回退。
3. 在实验性 HTTP 连接复用前后，对比首屏连接数、资源完成时间、普通 RPC 尾延迟和上传的取消/EOF。用相同测试同时跑回环与 TLS。最终仍配置目标机旧 Chromium 和 Electron 22 的同机对照。
4. 以真实菜单点击和空闲一分钟对照为 Win7 验收入口，分别采集渲染主线程、Electron 主进程、Python Host 的 CPU/私有内存、文件打开、长任务和 loop 延迟。覆盖 x86 的大回执与预览峰值。首次启动、后续启动和首次会话冷读分别计时。

本轮定向合同验证 109 项通过，覆盖 Desktop 运行时和 v3 帧、真实 mux sockets、HTTP 连接生命周期。测量脚本、原始记录、Node/Electron 身份和 JUnit 保存在独立输出目录。
