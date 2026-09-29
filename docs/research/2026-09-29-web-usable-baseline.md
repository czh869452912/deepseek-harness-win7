# Web 最小可用链路验收（2026-09-29）

## 结论

正式 `dsh --profile web` 已具备可验证的工作区、会话、模型请求、真实工具执行、历史恢复、分支、反馈和日志导出链路。本次使用 Python 3.8.10、当前 Windows 与 Codex 内置浏览器；模型和 OTLP 接收端均为本机测试服务，没有调用付费模型或发送真实遥测。

这是核心可用性验收，不是全部上游架构/业务模块的 parity 认证，也不是 Win7 真机或新 portable 发行认证。

后续专项：[设置目录与配置持久化](2026-09-30-web-settings-acceptance.md)、[长运行压缩、PTC/创造模式共存与文件工作区](2026-09-30-web-long-run-and-presets.md)。后续记录补充实际发现与回归，不覆盖下文仍未完成的完整对齐范围。

## 提交与验证

- `ebb52cd7`：反馈和插件列表接入正式 Typert Remote；错误边界对齐固定上游。相关 53 项专项测试通过。
- `78edcb8c`：正式 Session Remote、历史流、搜索、引用、导出、预设隔离、工作区指令、OTel 及 Cordis 运行器连接；退役 `dsh/harness.py` 平铺入口并迁移测试。
- 完整命令：`.venv\Scripts\python.exe -m pytest tests -q --tb=short`。结果：**3614 passed, 11 skipped, 1 warning**，447.14 秒。警告为 Windows Proactor 管道析构时事件循环已关闭；日志另有测试 HTTP 客户端断开后的连接重置输出，没有描述为无警告通过。
- `scripts/migration.py check` 通过，`ready` 无可领取输出；它们校验记录/固定 inventory，不证明新业务 parity。没有重新签发历史迁移证据。
- `apps/web` 的 183 个非构建文件、`packages/client` 的 1277 个非构建文件与固定 reference 比较，除 CRLF/LF 外无差异；119 个版本化 Web 构建产物 SHA-256 全部匹配既有清单。没有宣称进行了新的上游源码构建。

## 实际验收

原版网页目录选择器选择仓库目录、创建工作区和标准模式会话、发送消息、显示回复；刷新与服务重启后恢复工作区和对话；创建会话分支；标记正向反馈并在刷新/重启后的聚焦读取中恢复；下载 Session ZIP、校验 CRC，并确认包含实际测试内容。原版反馈控件在悬停/聚焦时延迟读取，因此刷新后的初始未选中样式不能作为丢失反馈的判断依据。

自动测试另覆盖：极简/标准/Cordis 预设通过正式 Remote 创建并请求模型，极简 prompt 完整覆盖且不混入工作区指令，标准/Cordis 的 AGENTS.md 进入实际模型请求；模型提出 `read` 调用后执行真实文件读取并把结果送回模型；持久化后在新 Host 恢复；跨会话引用和可选全文搜索；导出原始 JSONL 内容一致；真实 Cordis Host 插件挂载、撤销及跨会话拒绝；包含 Client 半部时等待浏览器批准/结算；OTLP protobuf 实际发送到本地接收端，DISABLED 不发送，FEEDBACK_ONLY 仅在真实持久化反馈事件后发送。

## 启动

源码虚拟环境已配置。正常模型使用前仍须配置自己的 API Key/Base URL：

```powershell
.\dsh-web.bat
```

使用终端打印的带一次性 token 的 URL。需要避开系统文件夹选择框时：

```powershell
.\dsh.bat --profile web --patch examples/web-browse.patch.yml --no-open
```

补丁禁用自动目录选择器，并装配上游 Host browse 与 Client browse 两个插件；没有替换原版 UI，也没有绕过认证。自动化未能控制系统窗口不等于产品原生目录选择功能失败。

本次演示目录 `.web-acceptance-home`、本地模型脚本、截图和日志位于忽略的测试目录，未提交测试凭据或用户会话。3080 演示服务使用模拟模型，不是实际 DeepSeek 对话。

## 完整对齐仍需完成的验收/实现

1. 当前 Cordis 动态 Host 代码使用 Python，尚不具备原版 JavaScript Host 半部语义；Inspect Provider 的完整类型契约、Guard、热更新状态机及前后端联合失败恢复仍需专项对齐。普通 Cordis 预设聊天通过不等于完整自修改能力对齐。
2. 工作区指令已接入持久化 pre-step，但原版文件版本缓存、预算排除集、执行祖先/step 提交边界的即时 inbox 投影尚未逐场景认证；目前在下一步重新读取/合成。全文搜索使用可重建 FTS 索引，尚未认证原版增量索引和大历史性能。
3. 审批、提问、附件、取消/steer、后台 jobs、子代理、工作流和全部设置面板仍需原版浏览器旅程专项验收，不能由模块存在或全量旧测试推定完成。
4. 关闭多会话 Host 时观察到可重建 projection cache 写入与 storageDomain 关闭竞争的日志，需要收紧消费者关闭顺序；Session 日志及重启恢复已通过，但这不免除缓存生命周期问题。
5. 真实远程模型、Win7 SP1/Win7 浏览器、新增 OTel 依赖的 Win7 原生轮子，以及基于当前提交重新制作的 portable 包均未验收。ACP provider 仍缺失，不属于本次 Web 核心链路。

后续应按真实契约和旅程推进，不把这些差距标记为已对齐，也不通过更换前端或恢复旧入口掩盖问题。
