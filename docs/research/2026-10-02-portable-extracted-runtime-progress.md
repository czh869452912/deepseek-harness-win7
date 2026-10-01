# Portable 候选构建与实际解压验证

日期：2026-10-02。产品起点 `ab9883b2`，固定原版
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。本批次落实
[Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md) 的实际发行物门禁。
保持原生 Python 3.8.10，没有引入生产依赖、QuickJS、Node Host 或浏览器代码修改。
候选构建和本机验证不代表公开发布、完整上游迁移或 Win7 认证。

## 构建行为

`scripts/build_portable.py --output-dir <directory>` 可生成独立候选，默认路径和
两个 launcher 保持已有产品约定。先在目标卷的临时目录完整组装和压缩，再替换
目标目录与 ZIP。组装、压缩、备份及两次发布操作的进程内失败恢复旧产物。
恢复也失败时保留 `previous-*` 备份并输出位置，避免删除最后可恢复内容。
拒绝覆盖构建输入、链接/junction 输出及错误的文件类型。

这不是目录/ZIP 的跨文件原子提交，不保证强制终止、断电和并发构建时自动恢复。
本轮不向默认 `dist/dsh-win7-portable` 写入候选，也不更新真实用户 profile。

构建器实际执行所选 `python.exe -I`，要求 Windows x64 Python 3.8.10；provenance
记录观察值及 `python.exe` / `python38.dll` 哈希。已有生产依赖锁、前端输入、
产品提交和 dirty 状态继续记录。文件名及 wheel 平台标签不代替执行证明或 Win7 验证。

## 解压包门禁

```powershell
.venv\Scripts\python.exe scripts/build_portable.py --output-dir dist/candidate-portable-20261002 --ripgrep-source scripts/oracles/official/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe
.venv\Scripts\python.exe scripts/verify_portable.py --archive dist/candidate-portable-20261002/dsh-win7-portable-v0.1.0.zip --output .goose/out/portable-final-extracted.json --expected-commit <完整候选提交SHA> --browser <Chromium绝对路径>
```

`--expected-commit` 拒绝错误提交或 dirty provenance；不传 `--browser` 时报告明确
标记浏览器未运行，不把 runtime 通过当作 Web 通过。Node/Chromium 仅为开发观察工具。

验证器将实际 ZIP 解压到含中文和空格的系统临时路径，检查运行时哈希及全部
119 个固定前端文件。Host 的 PATH 只有解压目录和 System32，没有用户 Python、
Node/pnpm、PYTHONPATH 或 API Key。探针由包内 Python `-I` 执行，生产模块和
搜索路径必须来自解压目录，pip/pytest/QuickJS 均不可导入。
探针源码是仓库中的验证驱动，不注入仓库生产包或运行 pytest。

实际执行范围：

- minimal、standard、creative、web、headless 的 canonical CLI 配置输出。
- 作者生成的纯 Python 工具插件及两层锁定依赖：原生 pack、ZIP 安装、正式
  profile 启动、真实工具调用、关闭后模块清理、重启、升级、指定版本回退及卸载。
- 正式 Web profile 中通过创造模式工具导出 Python Host / JavaScript Client，
  使用包内原生 `build` 和 `pack`，再安装到相同 canonical profile。
- 会话日志 flush、关闭后冷查询和日志投影恢复。预备零步 turn 只是合法的会话
  列表 fixture，不伪装成模型生成或真实远程模型旅程。
- 原版浏览器的欢迎提示、无凭据时“稍后配置”、冷会话侧栏选择、最新标题恢复，
  安装 Client 的真实点击及 JSON RPC 回包；Session follow 走 `/api/remote.mux`，
  普通 RPC 走 Connection HTTP 路径。验证器观察实际网络消息。
- 最终浏览器 gate 还要求强制关闭观察浏览器后，同一 Python Host 和已安装
  Remote 仍能回应另一条 HTTP 请求；结果以最终候选 report 为准。

开发候选 `dist/candidate-ab9883b2`（provenance 为 `ab9883b2` + dirty）已完成
13 个 runtime 检查和 4 个原版浏览器步骤。它用于开发验证，不冒充干净候选。
最终提交候选及最后的断连步骤分别使用上述 `portable-final-extracted.json` receipt，
提交和归档 SHA-256 由实际构建与验证输出给出，不靠本记录推断。

## 连接重置修复与原版依据

浏览器失败退出曾触发 WinError 64：mux pump 发送失败帧后，发送关闭帧又失败，
后台 task 的拒绝未取回，canonical fail-loud 可能终止 Host。
Python `MuxConnection` 现将连接重置按 socket EOF 退役，在关闭帧无法送达时
仍释放 writer，并观察已完成 pump 的异常；其余连接不随之关闭。

固定原版 `packages/api/gateway/src/stream-server.ts` 已监听 WebSocket `error`
并终止对应 socket，也通过 `done.then(remove, remove)` 观察 pump 的两种结算。
因此这是迁移版偏差修复，不登记为原版 bug。

新增故障注入覆盖 Windows read reset、item/error/close 连续写失败的 iterator
释放；另以真实 TCP abrupt close 验证新连接仍可使用相同 Gateway。
`.goose/out/portable-reset-comparison.json` 对比起点实际 Python 源码与修复：
两例起点均抛 `ConnectionResetError`，修复后均通过，记录输入哈希。
这是迁移前后比较，不是原版双侧 oracle。

标题排查没有确认新 bug：原版 listing 允许较旧的 checkpoint cut。fixture 在
`turn/end` 之后 rename，冷侧栏可以先显示工作目录名；日志仍包含最新标题，
打开 Session 后原版 history/projection 路径更新标题。本 gate 验证两步及实际
`session/follow` 地址，未重命名冷会话或重建其日志以掩盖缓存语义。

## 回归与边界

- 构建/打包专项：24 passed。
- Gateway/WebServer 专项：12 passed。
- 包含最后连接修复的全量 `pytest tests`：**4714 passed、2 skipped、1 warning**，
  670.15 秒，退出码 0。原始日志与 JUnit 为
  `.goose/out/portable-final-full.log` / `portable-final-full.xml`。
- 之前仅构建修复的全量为 4711 passed、2 skipped、1 warning，703.58 秒；
  不代替上述最终结果。既有 Proactor 析构 warning、pytest-asyncio fixture 提示和
  测试 HTTP 连接中止诊断保留，不宣称零警告。

软件继续采用固定运行时 Portable；插件经 profile/Loader 的目录、ZIP 或指定哈希
HTTPS ZIP 获取，创造模式导出及可选预构建 Client 进入同一 store。候选不执行
系统 pip/npm/pnpm。当前浏览器验证只证明本机 Chromium；Win7 真机与目标浏览器
保留用户暂缓状态。尚未认证通用 JS Workflow/Host、完整 SDK 动态治理、任意 wheel/
原生依赖、版本范围求解、npm/PyPI 获取、公共目录及全项目 parity。完整授权审计、
软件更新保留用户资产的发行旅程和公开发布也不能由本门禁替代。
