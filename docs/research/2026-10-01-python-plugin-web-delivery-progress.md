# Python 插件预编译 Web / Remote 联合交付进展

日期：2026-10-01。起点产品提交 `4acef102`；固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。原生 Python 3.8.10、当前 Windows
与开发机 Chromium。本记录落实插件交付评估的 C 阶段中预编译 Client / Remote
部分，不认证整个 C 阶段、完整 JS 运行时、全项目迁移或 Win7。

## 交付路径

新增 opt-in `examples/python-web-echo`：作者维护 Python Host 服务、Client 源码和
共享 JSON Remote 合同，附原版 ModuleLoader 格式的预构建 JS 与 Source Map v3。
普通用户通过原有 `dsh plugin --profile web` 的 `pack`、`add`、`upgrade`、
`rollback`、`remove` 使用同一 profile / Loader 生命周期，不执行 Node、pnpm、
pip 或包脚本。开发机浏览器 oracle 的 Node/CDP 仅属于验证工具。

Python API 1 增加现有 `Remote`、`RemoteScope`、`TypertRemoteService` 的薄导出和
`JsonSchemaCodec`，后者复用 Host 已支持的 JSON Schema 子集与不可变 JSON 快照。
Python Typert artifact 和 Client descriptor 来自同一 `remote/contract.json`。
浏览器仍通过原版 Connection / Typert Remote 调用服务，未加入自定义业务桥或
改变任何原版 frontend 输入。

安装前检查 `dsh.client`、相对 `exports["./client"]`、固定目标和
`dsh.webArtifacts = {formatVersion: 1, targetUpstream, files}`。每个 runtime artifact
须存在、留在包内且匹配 SHA-256；Client 不得为空，存在的 source map 必须列入
receipt 并满足既有 v3 validator。导出的 Typert artifact 必须列入 receipt；Python
artifact 在安装前做语法解析，既不执行包代码，也不把哈希当成信任证明。

作者手写项目使用 `dsh.release = {formatVersion: 1, files}` 声明显式发行文件集；
创造模式导出项目继续使用其 `dsh.sourceExport` 来源记录，二者不可同时声明。
`pack` 和目录安装复制显式文件，ZIP 安装拒绝额外文件。发行集合须包括描述、
bundle patch、全部 Python 源码、全部 Web receipt artifact、README 和 LICENSE。
这让普通作者可以打包 Client/Host 联合插件，同时保留导出项目来源信息。

示例开发构建器只封装提供的 plain JS，不是 TS/TSX 编译器。所有 receipt 输入保持
LF，Git 属性保持这些字节；Windows 自动换行不能让新检出的发行文件失配。

## 原版卸载语义与真实浏览器

原版 `packages/client/hmr/src/client/index.ts` 对 `graph` frame 明确忽略；boot graph
保留至页面 reload，`rebuilt` 才执行具体 Client reload。Python HMR 与此保持一致。
Host 卸载不会自动撤销已打开页面的 overlay，不应以一个不存在的 HMR 删除协议
作为验收要求。

真实浏览器验证顺序为：安装 ZIP → 自动加载 Client → 按钮通过 `/api/remote.mux`
调用 Python → 页面刷新后 Host 计数继续 → Host fiber 卸载 → 已打开 Client 仍在，
其 Remote 调用被拒绝且不得退回 SRC → 页面刷新后已撤销 Client 不再出现在 boot
graph → profile 重启 → ZIP 升级至 2.0.0 → 回退至 1.0.0 → 移除后重新启动。
这属于原版有意定义的边界，不据此登记原版 bug。

测试私有 Host 使用正式 `run_profile`、原生 CLI 打包与安装、实际 Loader fiber
卸载和持久文件版本回退。浏览器用真实鼠标事件操作原版 shell 的首次使用确认与
插件按钮，记录实际 Connection RPC request/response，不伪造 browser services。
五个成功调用和一个卸载后拒绝、12 个步骤必须全部通过；同时检查前端 119 个锁定
输入及本轮 provider/consumer 输入哈希未变，浏览器异常和 Host teardown 必须为空。

## 验证与剩余范围

启用 `DSH_TEST_CHROMIUM` 后，专项三个文件（联合交付、源码导出、已有原版浏览器）
为 **50 passed，76.00 秒**。随后新增 null release 拒绝用例，最终完整执行
`.venv\Scripts\python.exe -m pytest tests`：**4621 passed、2 skipped、1 warning，
491.47 秒，退出码 0**。JUnit 共 4623 项，failure/error 均为 0，三个实际浏览器
用例全部执行通过。两个跳过项仍为 Windows 不适用的 POSIX 路径/权限检查。

全量仍保留既有 Proactor transport 析构 warning、pytest-asyncio fixture loop scope
弃用提示和测试 HTTP 连接中止诊断，不宣称零警告。浏览器联合示例报告自身没有
Runtime/console/network 错误，Host stderr 为空且退出码 0。

日志为 `.goose/out/python-web-focus.log`、`python-web-final.log` 与对应 JUnit XML；
最终实际浏览器报告为 `.goose/out/python-web-browser-final.json`，12 步、6 个实际
RPC request/response。报告的 16 个实现输入在回归后重新核对，0 漂移；全量运行
的 21 个产品/测试/示例输入快照为 `python-web-final-inputs.json`，同样 0 漂移。
这些本地诊断文件不是新的全项目正式 acceptance。

Python 3.8 compileall、Node syntax check、git diff --check 通过；migration check /
ready 通过，reference checkout 未修改。这些记录门禁不替代全项目或平台认证。

发行方向继续遵循 2026-09-30 插件交付评估：固定 Python 3.8.10 的 Portable 本体，
用户插件由 profile 管理，本地目录/ZIP 优先，GitHub Release 交付版本化 ZIP，
npm/PyPI 等获取来源后续归一到同一安装流程。本轮未发布、推送或重建 Portable。

通用动态 Client source 转为可安装项目、复杂 Remote 类型生成、离线 Python 依赖
闭包与冲突诊断、多来源获取、最新 Portable 解压验收均仍需实施。任意 JS Workflow、
完整 JS Host 与 Inspector/CDP 等剩余原版表面不能由这个示例替代。Win7 真机和目标
浏览器验证按既有暂缓决定保留；当前 Windows/Chromium 不替代它们。本轮不引入
QuickJS、Node Host 或新生产依赖，也没有发现可确认的新原版 bug。
