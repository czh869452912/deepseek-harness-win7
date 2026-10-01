# 创造模式 Client 源码构建与 Python Host 联合交付

日期：2026-10-01。起点提交 `3194f7f2`；固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。环境为原生 Python 3.8.10、
当前 Windows 与开发机 Chromium。本记录推进插件交付评估的创造模式持久源码
交付，不认证完整动态运行时、全部 C 阶段、全项目迁移或 Win7。

## 实际交付路径

真实 `cordis_export` 产生用户项目后，可以执行：

```text
dsh plugin --profile web build <project>
dsh plugin --profile web pack <project> <output.zip>
dsh plugin --profile web add <project-or-zip>
```

`build` 使用 Python 标准库封装导出的 plain JavaScript 函数体，保留准确源字节与
原始来源记录；生成 ModuleLoader Client、Source Map v3、共享 JSON Remote 合同、
Python Typert artifact 与 SDK 入口。它不编译 TS/JSX、不引入 Node/pnpm/pip。
JS 语法和 evaluator 约束由原版浏览器激活时验证，构建成功不是 JS 执行成功。

浏览器 SDK 使用固定原版 `evaluateClientHalf`、`dynamicCordisContext` 与
`DynamicCordisStyles`，复用 React、slots、受限 Context 与 `host.call`。原版 Web
和 client bundle 均未修改。Python SDK 在 guarded Host 激活的子 Context 中提供
属于该包的 Remote，参数、结果走既有 Connection / Typert 严格 JSON 边界。
Client-only 项目可以安装，不伪造 Host handler；调用未知 handler 明确失败。

源码和生成文件的 SHA-256 均写入 Web receipt。修改 Host/Client 源码后必须
重建。原始 `sourceSha256` 保留导出来源，`clientBuild` 记录当前构建输入和目标。
安装器拒绝只修改 `requiresClientBuild` 而缺少 Client 声明与 receipt 的项目。

构建先在独立临时目录准备显式发行集合，验证描述、Python 语法、路径、文件和
哈希，再发布作者目录的生成文件；包描述最后写入。候选验证失败不修改已有
构建输出。此流程没有承诺任意磁盘故障下作者目录的全文件原子更新；安装仍须
通过完整 receipt 校验，不能把中断的构建当成可用发行物。

Host handler 捕获激活代次。卸载或者依赖停用再恢复后，旧代次开始的调用不能
迟到返回成功。可信 Python callback 可能继续执行至自身完成；这是结果有效性
和生命周期约束，不是任意代码抢占或安全沙箱。

## 真实原版浏览器证据

测试在私有 `DSH_HOME` 下启动正式 `run_profile(web)`，创建真实 Cordis Agent，
经真实 Tools 导出指定版本，运行原生 CLI build/pack/add，再打开原版 shell。
Host 不依赖 Node/pnpm；Node/CDP 仅用于开发机浏览器验证。

17 步全部通过，包括安装、中文参数调用、非法 JSON、快照、两次真正 HMR、页面
刷新、Host 卸载、profile 重启、2.0.0 升级、1.0.0 回退和移除。观察到 9 个真实
Remote request/response：8 个成功、1 个卸载后拒绝。六类无损 JSON 违规在 Client
侧拒绝，未增加 RPC 或 Host 计数；非枚举 `toJSON` 在快照后不会被序列化调用。

HMR 重建与还原源码均保持页面 timeOrigin 和 Host 计数，旧 style/子 fiber 被释放，
只保留一个新 style。原版 HMR 忽略 graph frame、boot graph 保留至 reload 的既有
语义继续保留；Host 卸载后保留的 Client 调用严格失败，不能退回 SRC。

最终全量 `.venv\Scripts\python.exe -m pytest tests`，启用
`DSH_TEST_CHROMIUM`：**4629 passed、2 skipped、1 warning，546.31 秒，退出码 0**。
JUnit 共 4631 项，failure/error 均为 0，四个真实浏览器用例均执行通过。新增文件
含 8 项测试：真实导出安装、Session 拒绝、Client-only、候选失败与源码重建、CLI
参数、两种激活中断、浏览器联合旅程。

日志与 JUnit 为 `.goose/out/python-client-final.log` / `python-client-final.xml`。
全量浏览器报告复制为 `python-export-browser-final.json`：119 个固定前端输入、
21 个实现/示例输入均匹配；全量开始的 11 个变更输入快照
`python-client-final-inputs.json` 在结束后核对，0 漂移。浏览器 Runtime/console/
network 错误为空，Host stderr 为空、退出码 0。这些本地诊断不是全项目 acceptance。

两个 skip 为 Windows 不适用的 POSIX 路径/权限检查。保留既有 Windows Proactor
transport 析构 warning、pytest-asyncio fixture loop scope 提示及测试 HTTP 连接
中止诊断，不宣称零警告。Python 3.8 compileall、Node syntax、diff whitespace、
migration check/ready 均通过，reference checkout 未修改。

## 明确剩余范围与发行方向

本次只支持 Host placement。Session placement 在写入前明确拒绝，不能提升到
全局 Host；仍需实现 selected Agent 的 Remote scope、preset 和 Client 所有权。
安装后的 SDK 不持有原始动态 Agent，也未加入动态 runner 的 AgentRun/card 管理；
局部 claim/priority/诊断不能据此认证完整动态运行时治理或跨插件顺序。

复杂 Remote 类型生成、依赖闭包与冲突诊断、GitHub Release/npm/PyPI 获取归一化、
最新 Portable 的实际解压验证继续实施。任意 JS Workflow、JS Host 与 Inspector/CDP
等原版表面仍须分别迁移，不能用 plain JS Client 构建替代。Win7 真机和目标浏览器
验证保留用户暂缓决定，当前 Windows/Chromium 不能代替它们。

发布继续采用固定 Python 3.8.10 Portable 本体、统一 profile/Loader 的 Python 插件、
可选预构建 client、本地目录/ZIP 优先。此次没有新增生产依赖、QuickJS、Node Host，
没有发布、推送或重建 Portable；修正的是迁移版实现问题，未登记新的原版 bug。
