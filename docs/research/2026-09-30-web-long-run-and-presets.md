# 长运行压缩、预设共存和工作区修复（2026-09-30）

## 用户导出日志核查

检查用户提供的 Session ZIP 中的 `session.jsonl`，未执行日志里的任务或指令，未把完整会话内容、凭据或模型输出加入仓库。

日志含 74,955 行：2 个 turn、60 个 step，10 次 compaction start/end 配对。5 次摘要成功；4 次失败为 `IncompleteRead(0 bytes read)`；最后一次为 cancelled，紧随其后的 turn/end 明确是用户中止。

| compaction/end seq | 耗时（秒） | 结果 |
| --- | ---: | --- |
| 29137 | 47.0 | 成功 |
| 45080 | 43.5 | 成功 |
| 50176 | 53.5 | 成功 |
| 60622 | 31.7 | HTTP 读取中断 |
| 61473 | 41.5 | HTTP 读取中断 |
| 61564 | 71.2 | 成功恢复 |
| 68626 | 76.4 | 成功 |
| 72877 | 44.9 | HTTP 读取中断 |
| 73264 | 38.0 | HTTP 读取中断 |
| 74952 | 34.0 | 用户中止期间取消 |

失败的压缩没有 compaction/summary，未把不完整摘要写成成功检查点。日志可以确认响应流不完整，不能单凭它归因于服务端、代理或网络，也不能声称本地补丁能消除远端中断。

`60453f25` 将 HTTP 分块读取异常归入 `TRANSPORT`，保留取消优先级，不接受部分摘要、不隐藏重试。固定上游 compaction summarizer 每次辅助调用只执行一次 `llm.stream`，没有增加不属于该契约的内部重试。真实 HTTP 回归先发送不完整 chunked SSE，再恢复正常响应，验证失败不替换历史、结束事件可持久化，下一次压缩成功。压缩/线协议专项 21 项通过。

## PTC / 创造模式挂载错误

原版 `reference/vendor/loader/src/config/isolate.ts` 用 `Symbol(description)` 作为隔离身份。旧迁移代码用描述字符串作 key，不同预设里的同名 `delegation` 等组因此碰撞；单独启动某个预设的测试无法发现这一问题。

`19b2832e` 为新隔离标识分配唯一 token，同时保持同一 Realm 已注册 key 的身份稳定。删除后重建与非创建探测也保持原版 Symbol 语义，显式同标签共享仍通过 Loader 的同一个 GlobalRealm 实现。没有修改上游预设来绕开核心错误。

正式 Web 测试同时创建 standard、ptc、cordis、minimal 会话，验证 workflowEngine 为独立实例、宿主无泄漏，PTC 只向模型暴露 run_code、标准模式不受影响。真实 Python 子进程执行 run_code → tools.read 返回文件内容；未开始的会话在三个预设间切换，复用各自 standing mount。隔离/预设专项 18 项通过。

原版浏览器（3082，本地模拟模型）已在同一 Host 切换 PTC、创造模式并分别完成一轮回复，无浏览器 error 日志。截图在忽略目录 `.venv/web-ptc-acceptance.png` 与 `.venv/web-creative-acceptance.png`。

## 长运行日志中的文件工具问题

会话 cwd 指向用户项目，但 read/write/edit 没把 cwd 传给 fs，也没给写入传递会话 sandbox policy。相对路径落在 Host 启动目录，绝对项目路径又被宿主 workspace-write 根拒绝。用户工作树中的 `probe.txt` 是既有未跟踪文件，本次未修改或提交。

`aa30e26f` 对照原版 tool-fs 的 session-cwd 与 sandbox 调用边界，将路径解析和写入策略都绑定调用会话；涉及父路径时先规范 cwd 的文件系统身份，保留取消、观察版本和原子修改检查。没有更改进程 cwd 或放宽沙箱。

正式 Web 回归验证两个会话对同名相对文件分别创建、读取、编辑，并验证跨工作区和只读拒绝。测试中收窄平台临时目录的默认授权，以免 pytest 位于系统 temp 下掩盖错误根；生产临时目录授权保持原版行为。文件专项 18 项通过。

## 未被此次验收覆盖的差距

模式可进入、聊天及 Python PTC 可执行，不代表全部动态运行能力已对齐。当前 codeRuntime 是 Win7 Python process 适配，原版 PTC 预设文案仍描述 TypeScript；原版 JavaScript Cordis Host 半部、完整工作流执行及 Inspect/Guard 等仍有差距。没有修改原版前端，也没有将工作流旧实现的占位成功当成真实工作流验收。

多会话快速关闭仍可能出现 projection-cache 与 storageDomain 关闭竞争警告，既有记录继续有效。真实远程模型的长时网络稳定性、Win7 真机和重新制作 portable 包未在本次认证。

## 最终回归

首次全量回归暴露两处旧断言把 Symbol 身份等同于描述字符串，按原版语义修正后，相关 16 项专项通过。再次执行 `.venv\Scripts\python.exe -m pytest tests`：**3620 passed, 11 skipped, 1 warning**，359.43 秒，退出码 0。日志为 `.venv/web-modes-suite-final.log`。仍有既有 Windows Proactor 管道析构的事件循环关闭警告；不宣称无警告通过。

`scripts/migration.py check` 在最终测试修正后通过；`ready` 无就绪任务输出。它们只校验迁移记录，不代表上述完整 parity 差距已消除。
