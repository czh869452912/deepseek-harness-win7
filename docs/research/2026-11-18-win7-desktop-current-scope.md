# 当前基线的 Win7 Desktop 适配范围

目标原版为 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。当前原版已经将 Desktop 改为 v4 生命周期协议和 HTTP/WebSocket 应用；旧版 v3 管道及独立插件管理页面已经删除。

本轮 Win7 Desktop 保留 Electron22 外壳，通过既有 Python 适配层运行当前 canonical profile、Connection 所有的 owner Peer、授权 Remote、当前服务和原样 Web 前端。C8 的实际 Desktop 配置、遥测及策略流检查属于这个适配范围。它不等同于完整移植新版 Electron44 外壳、全部 IPC 控制、界面或升级生命周期。

来源分开记录：`apps/desktop/source-input.json` 绑定当前目标、原版 v4 协议元数据和当前前端输入；`compatibility-source-input.json` 原样保留旧版外壳资源、v3 管道和注入式完整安装器更新协调器的原始来源及摘要。后者继续作为 Win7 平台代码使用，不能改写成来自当前原版。构建器同时核验两组字节；当前原版协议为 4，并不意味着私有 Win7 管道也变成了 4。

统一候选门禁分别构建 x64/x86 Portable 和 Standard Desktop，检查各自包内 Node16/Python 的真实进程、原版浏览器应用和 Desktop 关闭。构建或运行通过仅证明这些具体行为；管理员安装、AIO 系统补丁/重启及 Win7 真机资格独立保存，也不改变 `accepted_upstream`。新版外壳的完整移植应采用额外合同与消费者，不能由这些兼容检查代替。

2026-11-25，Win7 私有管道增加了响应额度扩展。Electron 请求启用，Python 在启动回执中确认。每条响应初始可发四帧，Electron 接收一帧后返还相应额度。慢消费者耗尽本流额度时，其他流仍可通过共享管道。任一端使用旧载体时沿用原有帧与回压逻辑。原始 v3 帧样本、已固定的原版 JS 编解码器和前端构建仍是相同的输入。
