# C7 Connection、Gateway 与授权进度

固定目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。本页索引定向合同检查，不表示生产基线切换或完整发行资格。

| 单元 | 已验证边界 | 记录 |
| --- | --- | --- |
| C7-A | 调用与事件资源解析、优先级、Context/lookup 资源 | [资源解析](access-resource-checks.json) |
| C7-B | Remote 标记与资源读取器元数据 | [Remote 标记](remote-marker-checks.json) |
| C7-C | RemoteAccess 决策、快照、过滤与增量流 | [访问控制](remote-access-checks.json) |
| C7-D | 解析前授权、可信 Peer 与调用者上下文 | [调用授权](authorized-call-checks.json) |
| C7-E | 调用信号、严格 uplink、消费与取消 | [调用生命周期](gateway-invocation-checks.json) |
| C7-F | RPC 结果物化与二进制附件 | [结果编码](rpc-result-checks.json) |
| C7-G | HTTP RPC multipart 与可信 Peer 传递 | [HTTP RPC](rpc-http-checks.json) |
| C7-H | Host、Origin、监听地址与端口信任 | [请求信任](connection-trust-checks.json) |
| C7-I | 浏览器/API 分离认证与签名 Cookie | [认证](connection-auth-checks.json) |
| C7-J | Peer 准入、单 API 连接与路由卸载 | [Peer 准入](connection-peer-checks.json) |
| C7-K | Connection 插件、迟挂载与真实 HTTP | [插件组合](connection-plugin-checks.json) |
| C7-L | 帧语法、单消费者与 uplink 字节预算 | [帧与队列](uplink-inbox-checks.json) |
| C7-M | 实际双向 WebSocket、心跳、压缩与关闭 | [双向载体](duplex-mux-checks.json) |
| C7-N | 实际 Gateway HTTP/WS、严格调用和物理关闭撤权 | [Gateway 组合](gateway-transport-checks.json) |
| C7-O | 客户端帧负零拒绝与 IEEE754 整数解析，修正 C7-L | [数值边界](frame-number-checks.json) |
| C7-P | 事件授权、同 Peer 答复、重连补投与取消/卸载 | [事件转发](authorized-events-checks.json) |
| C7-Q | 完整应用事件清单、会话资源声明、实际 WS 与 HTTP 答复/卸载重载 | [应用事件组合](event-composition-checks.json) |
| C7-R | 实际 Peer 的首页注入与访问快照、动态更新和注入方兼容 | [首页 Peer 注入](peer-index-checks.json) |
| C7-S | HTTP/进程内资源共用路由、HEAD、gzip、响应头与断开取消 | [资源载体](web-resource-checks.json) |
| C7-T | 认证首页资源、浏览器/调用者 Peer、ETag/304 和静态文件 | [静态首页](frontend-resource-checks.json) |

| C7-U | 具体 IP 绑定、IPv6、TLS 证书加载、独立握手与卸载收敛 | [监听与 TLS](web-tls-checks.json) |

| C7-V | 会话资源默认识别、预设选择和目标子代理控制的实际 Gateway 授权 | [应用资源声明](application-resource-checks.json) |

| C7-W | 非所有者列表/搜索过滤、v4 投影实时流、权限变化与取消 | [会话读取过滤](session-access-checks.json) |

| C7-X | 消息调用者、时区、持久去重与真实失败后的显式空提交重试 | [消息提交与重试](session-prompt-checks.json) |

| C7-Y | 普通会话串行复用、空白预设切换、冷恢复、动态默认模型与后台保存 | [会话激活](session-activation-checks.json) |

| C7-Z | 被动精确历史、轮次分页、助手输出、投影读取与会话头缓存提示 | [历史读取](history-reads-checks.json) |

| C7-AA | 被动事件/投影订阅、创建补帧与去重、单消费者、取消和卸载 | [被动订阅](session-listeners-checks.json) |

| C7-AB | 助手重连基线、每连接到达游标、生成取消结束帧与生命周期清理 | [助手重连](assistant-reconnect-checks.json) |

| C7-AC | 精确打开快照、混合事件增量、显式冷激活与独立租约生命周期 | [Web follow](session-follow-checks.json) |

| C7-AD | 被动状态、合并订阅、版本与所有权复核、等待超时及调用取消 | [状态与等待](session-state-checks.json) |

| C7-AE | 列表投影句柄、摘要排除、冷缓存提示、格式状态与分片工作预算 | [列表摘要](session-summary-checks.json) |

| C7-AF | 完整控制器初始化顺序、可用性事件、归档准入与失败/卸载清理 | [控制器组合](session-composition-checks.json) |

| C7-AG | Host 路径校验、原生应用目录/指定打开、关联打开与实际 Windows Shell | [文件应用](file-applications-checks.json) |

| C7-AH | 精确事件分叉、继承标记、开放工具/回合补全与迁移前置检查 | [会话分叉](session-fork-checks.json) |

后续：目录和技能消费者、生成物与原版客户端整体接入。上传提供方已另记 C8-A。最终资格使用 C9 冻结候选的完整门禁；当前生产 pin 与 `accepted_upstream` 不提升。
