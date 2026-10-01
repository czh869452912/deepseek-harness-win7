# 创造模式 Python 源码项目导出与交付

日期：2026-10-01。修改前产品提交 `066a9b72`；固定参考版本
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。

这是 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)
阶段 B 的原生 Python 实施，沿用已有目录/ZIP 安装、Loader、profile、源码升级
和回退。它不是新增 JS 引擎，也不认证任意原版 JS Host/Workflow 的执行。

## 实际行为

原先动态 runner 的定义仅驻留内存。新增创造模式工具 `cordis_export`，通过真实
runner 的 `inspectPackage(agent, pluginId, packageId)` 检查所有权并读取指定版本，
可以导出旧版本，不自动改用最新版本。原版 `native_contracts()` 的定义和提示保持
不变，导出是迁移版的显式附加工具，复用原版通用工具卡片和内容展示。

必填参数为 `pluginId`、`packageId`、`directory`、`name`、`version`、`placement`、
`license` 和 `licenseText`；`isolateServices` 可选。`directory` 是当前会话工作区
内不存在的相对目录；`placement` 为 `host` 或 `session`。`name` 使用作者自己的
稳定包身份，发行版本与动态 `packageId` 分开。许可证及正文须由作者明确提供，
导出器不替作者授予 MIT 或其他再分发许可。

生成项目包含：

```text
package.json                     # dsh.python / dsh.sourceExport
dsh-export.json                  # 原始动态身份、版本及两半源码 SHA-256
cordis.patch.yml                 # Host 安装补丁，或 session 的空补丁
preset.fragment.yml             # 用户预设贡献，Host 项目为空
python/exported/plugin.py        # 公共 SDK 入口
python/exported/host.body.py     # 指定版本的原始 Python 源码（如有）
client/source.js                 # 原始 Client 源码（如有）
README.md
LICENSE
tests/README.md                  # 作者应补充的行为测试说明
```

保存 Host/Client 字符串的原始 UTF-8 内容，包括行结束符。来源记录只包含所选
动态身份、名称、用途、源码哈希及装配类型，不收集 Agent 身份、环境凭据、会话
记录或本机路径。作者后续编辑源码时，原始哈希仍表示导出来源；安装代次中的
实际文件哈希由已有安装器记录，二者不混用。

## 装配与生命周期

Host 项目的 bundle patch 插入包入口。Session 项目的 patch 为空，安装只提供
包解析能力；作者将 fragment 中的行追加到自己的 `agent.cordis.yml`。导出器和
安装器不改写任何内置预设，导出还拒绝安装自带代码与预设目录。

Session fragment 自动隔离 `pythonPlugin:<packageName>`，并隔离作者在
`isolateServices` 中列出的额外服务。遗漏的全局服务贡献仍由正式预设挂载的
泄漏检查拒绝。同一个预设的会话按原版规则共用 standing preset；不同预设的
实例、工具和隔离服务独立。这里没有把原版所有权改成每个会话重建插件。

实验 Plugin API 1 新增 `python_host_source` 和 `host_handler_service`。SDK 在每次
Loader 挂载时重新读取 Host 源码、创建独立 globals 和处理器集合，并挂载真实
Cordis 子插件。复用既有 Guard 以及 `harness.defineTool`、`registerTool`、`handle`
合同，保留原生插件的 inject/config 和返回的清理函数。源码求值保留 Python trace
检查的 5 秒预算，不能抢占阻塞的原生调用。
缺少初始依赖明确激活失败，依赖消失撤销子插件的工具、服务和处理器可用性；
失败或卸载时清理部分注册。已取出的处理器服务在卸载后也拒绝调用。

`harness.handle` 不被丢弃，安装后通过
`ctx.get(host_handler_service(name)).call(method, args)` 调用。它是 Python SDK
服务，没有冒充原版动态 Client 的 Remote provider。Python 代码仍是受信任的
进程内代码，Guard 与 realm 不提供恶意代码隔离。

## 文件交付与失败边界

导出使用活动 `fs` 服务的 resolve/lstat/writeText 和会话 sandboxPolicy；每个
文件使用 createIfAbsent，保留取消信号，逐文件检查项目内的实际解析目标。
先创建来源记录作为认领点，最后创建 `package.json` 作为可安装提交点。
取消或碰撞不会覆盖已有文件，提交前失败可能留下不完整源码目录；没有描述
文件的目录不能安装。该目录须由作者检查后清理或改用新目录，不宣称多文件
导出具备数据库级自动回滚。

新增本地 CLI，不调用 Node、pnpm、pip 或包安装脚本：

```powershell
dsh plugin --profile web pack .\my-plugin .\my-plugin-1.0.0.zip
dsh plugin --profile web add .\my-plugin-1.0.0.zip
dsh plugin --profile web upgrade .\my-plugin-2.0.0.zip
dsh plugin --profile web rollback @author/my-plugin 1.0.0
```

`pack` 使用明确的 `dsh.sourceExport.files` 清单；源码项目的目录安装也使用同一
清单。项目中未列入的开发环境、`.env` 等文件不自动进入发行物或安装代次。
作者新增测试/资源后须明确加入清单。检查包内路径、Windows 文件别名、链接、
大小、源码语法及必要文件，拒绝原生依赖，ZIP 输出必须在项目外且不覆盖。
含 sourceExport 的 ZIP 若夹带清单外文件，安装和升级拒绝，保留现有 profile。
清单表示作者选择的文件，不代表代码可信，也不替代作者检查源码中的凭据。

安装/升级/回退继续使用既有 stopped-profile lease 和事务，不新增运行时注册表。
源码项目可编辑，发行版本须更新，具体配置与业务数据的迁移仍由插件作者负责。

Client 源码完整保留，并写入 `requiresClientBuild: true`。当前这类项目的 pack、
安装及加载明确拒绝，避免半部未交付却报告成功。预编译 Client、Remote 产物与
离线依赖闭包仍属于阶段 C 的待实施工作。

## 验证

新增 19 项回归，覆盖真实创造模式 Tools 的所有权与旧版本选择、实际目录和
ZIP 安装、SDK 工具与处理器、卸载、重新启动、编辑源码升级和指定版本回退，
以及两个正式用户预设的隔离、相同预设共享、无贡献的 minimal 预设。
另外覆盖只读 FS、路径越界、安装目录保护、提交前取消、文件碰撞、Client
拒绝、显式文件清单、私有文件排除/ZIP 夹带拒绝、缺失依赖、依赖消失和失败清理。

最终专项执行 source-export、distribution、versions、Cordis tools/guard 与 CLI
参数测试：**225 passed / 52.40 秒**，退出码 0。日志及 JUnit 为
`.goose/out/python-export-focused.log` / `.xml`。

最终全量 `.venv\Scripts\python.exe -m pytest tests` 为 **4591 passed、2 skipped、
1 warning / 418.33 秒**，退出码 0；JUnit 4593 tests，failures/errors 均为 0。
日志及 JUnit 为 `.goose/out/python-export-final.log` / `.xml`。配置
`DSH_TEST_CHROMIUM` 后，两个原版浏览器 lifecycle/inspect lane 都实际通过。
两个 skip 为既有 Windows 不适用 POSIX 场景；保留 Windows Proactor 析构 warning、
pytest-asyncio fixture loop scope 提示和测试 HTTP 连接重置诊断，不宣称零警告。

Python 3.8.10 py_compile、git diff --check、migration check / ready 通过，reference
无修改。`.goose/out/python-export-inputs.json` 绑定 11 个产品/测试文件的 SHA-256，
全量前后差异为 0。回归期间仅补充文档。记录门禁和测试数量不认证全项目 parity，
运行环境为当前 Windows / 原生 Python 3.8.10，没有执行 Win7 真机认证。

## 剩余目标

本轮未修改浏览器源码、引入运行时依赖或 QuickJS，没有新增可确认的原版 bug。
目录/ZIP、来源导出、源码升级回退在本轮范围内联通；作者自己的功能测试、
Client 完整交付、Python 依赖闭包、多来源获取归一化和最新 Portable 发行仍须
继续实施。任意原版 JS Host/Workflow、experimental Inspector/CDP 及其他未验收
模块仍未认证；Win7 真机与目标浏览器验证保留用户暂缓状态，accepted_upstream
仍未建立，完整迁移目标保持进行中。
