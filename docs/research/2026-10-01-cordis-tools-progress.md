# Cordis 工具提示、结果、自检与引用迁移

日期：2026-10-01。产品从 `09c0c5c4` 继续，固定原版为
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为当前 Windows / 原生
Python 3.8.10。本记录覆盖工具消费者、读取视图和真实 Python Host 旅程，
不认证整个动态 runner、浏览器、Win7 或全项目迁移完成。

## 实施

七个正式工具现在采用原版实际 `apply()` → `defineTool()` 注册所得的参数、
说明与输出 schema。`cordis_contracts.json` 保存固定源码生成的原始合同；
门禁重新执行原版注册，逐字段验证产物。JSON 根输出保留原版编译后的 `{}`，
define/stop/undefine 保留原版必需字段和额外字段规则。客户端源码没有修改。

`cordis_tools.py` 移植调用卡片、输出文本、展示 metadata、结果投影、自检和引用：

- 七个调用卡片使用原版 generic/read/execute/delete intent，define 展示两半源码，
  run/update 区分操作。历史参数的展示校验仍由 Tools 完成。
- define 明确尚未激活；run 返回 awaiting-approval / starting / running 的模型合同，
  running 投影 Host 提供/等待服务与 Client 等待状态，失败回执抛错。
- stop 将 already-stopped 视为幂等成功，只返回 pluginId；undefine 返回 pluginId
  与 wasRunning。模型结果不再直接泄漏内部 ok/reason 回执。
- inspect_self 无 ID 只返回摘要；pluginId 返回版本指针和各 Package 的 isCurrent /
  isNext；精确两 ID 才返回源码、两半状态、错误、handlers 和 renderFailure。
  packageId 单独使用明确报错。
- 引用只解析原始输入中 source.kind=user 的文本，使用原版 ASCII 数字 ID 与
  ECMAScript 空白规则，并按首次出现去重。先等待后续中间件，保留 reject 和其他
  decision 字段；有引用时才检查取消，追加带身份的 tool-cordis instructions 消息。
- 上下文选择 next → current → 最后定义的 Package，不带源码或 Package 全表。
  跨 Session、删除或不存在的引用报告 unavailable，不生成替代 Plugin。

提示从四句占位换成完整操作指引，段落顺序从 700 修正为原版 2500。
`cordis_prompt.py` 明确适配 Python Host：10 个提示片段、2 个 define 描述片段、
1 个 Host 参数描述。原始片段必须各出现一次，否则拒绝生成结果。Host 声明
callable plugin，依赖写在 plugin.inject；Client 仍为普通 JavaScript 函数体。
原版 Skill 的 JS Host 示例需要翻译，不要求模型直接提交给 Python。Host 具有
Python builtins/imports，不宣称 VM 或安全沙箱；不冒充 JS Host 源码兼容。

## 提供端修复

旧 runner 只有可序列化 inventory。本轮同时补齐工具所需的 Host-rich snapshot，
保留实际 Fiber/handlers/renderFailure；reference、inspectPlugin、inspectPackage
返回原版对应的所有权限定视图。Remote inventory 保持独立的可序列化边界。
不存在的读取和已知 run/update 计划使用原版错误消息。

原版引用只能识别 prefix-number，旧 UUID 使实际创建结果无法被协议识别。现用
runner 所有的四个单调序列分配 Plugin、Package、Run、Approval；删除不重用序号，
不同语义前缀共享 Plugin 序列。这些对象本来就是进程内临时定义，不作为持久
插件发行身份。

正式 Web profile 的真实旅程发现并修复两处迁移版偏差：

1. `ctx.plugin()` 返回 FiberHandle；旧 activate 丢弃 await 的原始 Fiber 返回值，
   导致服务所有权比较失败。现保存 awaited Fiber，自检实际提供服务正确。
2. 旧 plan 拒绝任何已有 run，要求先 stop，阻断原版直接 update/restart。
   现只拒绝正在启动的转换，更新按原流程撤销旧效果再激活新 Package。

原版对应实现已有正确行为，本轮未登记新原版 bug。上一轮 INSPECT-001 精确例外
仍保留，未扩大允许差异范围。

## 验证

```powershell
.venv\Scripts\python.exe scripts/cordis_tools_oracle.py --output .goose/out/cordis-tools-paired-final.json
```

结果 **92 matched，0 different**，绑定固定源码、参考 tracked-clean、输入哈希、
原样注册和最新 source observations。比较覆盖实际工具 callback、展示、渲染、
状态、错误、引用来源/去重/空白/替换/reject/取消、四类 mints、所有权读取及
17 组激活计划。消费者 fixture 使用合法 Fiber 树；读取和 plan 使用原版实际
runner 方法及 Registry。受控回执不认证完整异步 activation/approval，也不执行
通用 JS Host。提示语言适配单独审查，不宣称逐字一致。

`tests/test_cordis_tool_contracts.py` 校验实际 native 注册/执行、读取、计划及固定
原版证据哈希。正式 Web profile 旅程验证真实定义、服务提供、源码不可变、直接
update、停止与幂等停止、删除、ID 不重用、实际 waterfall 注入和跨 Session 的
unavailable。链中包含 Skill 等其他上下文，断言计数 tool-cordis 消息，不假定
整个 middleware 链只产生一条消息。

专项五个文件 **261 passed，15.37 秒，退出码 0**：
`.goose/out/cordis-tools-focused-final.log`。Web 旅程单文件 **4 passed**：
`.goose/out/cordis-tools-web.log`。早期失败保留于 `cordis-tools-focused.log` /
`cordis-tools-contracts.log`，包括真实服务漏报和测试错误假定根参数为 closed；
最终保留原版 schema，没有收紧规则。

原版七个相关测试文件原样运行 **127 passed，2.75 秒**：
`.goose/out/cordis-tools-source-baseline.log`。这是原版基线，不等于 127 个 Python
parity 用例。Inspect 门禁重跑 **42 matched + 1 精确 INSPECT-001 例外**：
`.goose/out/cordis-tools-inspect-paired.json`。

额外正式 Web profile 检查读取实际 Agent 可见的七个工具，其说明、参数和输出
schema 与 native 合同完整相等；按 agent-loop 的正式 Agent scope 组装提示，
完整 Python 适配段确实存在。记录为 `cordis-tools-registration.json`。首次诊断
未传 scope，因而只组装全局层；修正诊断载体后通过。该独立诊断保留一次既有
projection-cache 在 domain 关闭后的警告，不把它宣布为本轮已解决。

完整执行 `.venv\Scripts\python.exe -m pytest tests
--junitxml=.goose/out/cordis-tools-full.xml`：**4292 passed、2 skipped、1 warning，
336.20 秒，退出码 0**。JUnit 4294 项，failures/errors 均为 0；输出在
`.goose/out/cordis-tools-full.log` / `.xml`。生产与测试代码在该运行期间保持固定。
本轮新增 95 项测试。两个 skip 保留 Windows 不适用的 POSIX 语义；warning 为
既有 Proactor transport 在事件循环关闭后的析构诊断。pytest-asyncio 默认
fixture loop scope 提示与测试 HTTP 10053/10054 重置诊断保留，不宣称零警告。

8 个新增/修改 Python 文件的 Python 3.8 AST 与 compileall 通过。Migration check
通过，ready 退出码 0 且无就绪任务输出；reference tracked-clean，git diff --check
通过。这些检查不认证全项目 parity。

## 剩余迁移与交付

完整动态 runner 的审批、异步激活、错误、Client steering/恢复仍须继续校验和
迁移；原版 JS Host 与通用 JS Workflow 输入不能由 Python 翻译冒充。Client
manifest/Slot/主题与原版浏览器联合旅程、完整 inspector/CDP 和其他未验收模块
尚未完成。默认/显式 null 的平台 abort 原因区别未由本轮解决。
全项目 accepted_upstream 未建立；Win7 实机与目标浏览器验证保留用户暂缓状态。

发行方向按 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
固定 Python 3.8.10 Portable 本体，插件经 profile / Loader 装配，按需携带开发端
预构建 client。标准库插件本地目录/ZIP 与实验 API 1 已实现；创造模式持久源码
导出、版本升级/回退、哈希锁定的离线传递依赖、原生依赖 Win7 与 client 联合
验证，以及 GitHub Release/npm/PyPI 获取源归一化仍须实施。
本轮无新生产依赖、QuickJS、Node Host 或浏览器源码变更，未重建/发布 Portable。
合同 JSON 在 dsh 内，现有 Portable copytree 会包含它，但不替代当前提交的
重建、解压运行及浏览器发行验收。
