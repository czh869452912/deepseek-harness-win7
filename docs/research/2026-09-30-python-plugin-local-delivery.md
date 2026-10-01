# Python 插件本地交付实施记录

日期：2026-09-30。产品起点：`059a70ca`；本文对应其后的工作树实现。
固定参考版本：`cd5ef8148158c3a752a658978873241fdf8e2bbc`。

后续已增加停机升级、保留源码代次、版本查询与显式回退，实际 CLI、Loader 和进程
中断恢复见 [版本事务进展](2026-10-01-python-plugin-versions-progress.md)。本文仍保留
首次目录/ZIP 交付的历史验收范围，不把后续能力写成当时已实现。

本批次落实 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)
中的第一阶段。本地交付是 Python/Win7 宿主扩展，不是对原版 JS Host
插件语义的完整移植，也不建立全项目迁移完成或 Win7 实机认证。

## 实际交付

- `dsh.plugin_api` 提供实验 API 1 的薄导出：Plugin、Context、Schema、
  ToolExecutionInput、ToolExecutionResult。服务和事件仍有各自的契约；不承诺任意内部模块稳定。
- `dsh.python` 明确真实 Python 模块入口。Loader 优先处理该入口；即便包另有 JS main，
  Python 描述或导入失败也不进入 `create_js_mock_plugin`。
- 包内模块在私有包命名空间加载，支持相对导入，不修改全局 `sys.path`。
  命名空间包含安装路径、版本和 Python 源码摘要，避免同进程重装新源码仍执行旧模块。
  这不提供任意 Python 库的版本隔离，也不构成代码沙箱。
- CLI 支持本地目录或 ZIP 的 `add`，以及已管理包的 `remove` / `rm`。
  保留 package.json、dsh.bundle.patch、profile 和 Loader 装配，安装目录为
  profile 下的 `node_modules/<包名>`。这里只使用目录约定，安装和执行无需 Node/pnpm。
- `examples/python-echo` 是带 LICENSE 的标准库示例，真实注册 `python_echo` 工具，
  使用 `inject = ["tools"]` 和调用者所有的工具注册，卸载时撤销。

## 描述合同

`package.json` 的包名使用自身命名空间、版本为非空字符串；安装器拒绝覆盖安装自带身份。
`dsh.bundle.patch` 指向包内 YAML patch。`dsh.python` 的实验字段集如下：

```json
{
  "apiVersion": 1,
  "sourceRoot": "python",
  "entry": "echo.plugin:EchoPlugin",
  "minPythonVersion": [3, 8, 10],
  "minHostVersion": [0, 1, 0],
  "dependencies": []
}
```

路径为相对 POSIX 路径。entry 为模块与导出名，支持模块文件或包的 `__init__.py`。
版本数组按三元整数元组比较下限，不是 PEP 440 表达式；没有声明任意版本范围或依赖求解能力。
API 版本不支持时明确拒绝。Python/npm 依赖声明目前必须为空，原生 DLL/PYD/SO/EXE/wheel
拒绝安装。后续必须扩展依赖、平台和来源合同，才能达到评估中的完整交付范围。

安装先验证元数据、路径、Python 语法和 YAML 配置，不导入插件、不运行安装脚本。
导出是否可执行及插件 apply 成功与否在真实 Loader 激活阶段验证。
安装成功表示文件和 profile 引用已提交，不能据此证明插件功能正确或可信。

## 命令与所有权

停止目标 profile 后，在源码环境运行：

```powershell
.venv\Scripts\python.exe dsh.py plugin --profile web add .\examples\python-echo
.venv\Scripts\python.exe dsh.py plugin --profile web add .\python-echo.zip
.venv\Scripts\python.exe dsh.py plugin --profile web remove @example/python-echo
```

前两个是同一包的两种安装方式，不能连续安装覆盖已存在的包。
Portable 用户通过 `dsh.bat` 传入相同参数。命令不代表当前 dist 已重建或发行。
ZIP 支持包文件直接位于根目录，或位于唯一的外围目录。

安装复制源码快照，并将包名加入 profile.dependencies、dsh.profile.bundles 和
dsh.pythonPlugins。后者记录版本和各文件 SHA-256。安装不写入 Portable 的 lib。
用户 patch 保留；卸载仅删除对应引用与已验证的安装文件。修改过的安装源码或新增文件
会阻止卸载，避免静默丢失用户修改；生成的 __pycache__/*.pyc 不参与源码摘要。
用户数据应放在安装目录之外。

其他包命令仍走现有 pnpm。存在受 Python 安装器管理的快照时，pnpm 修改命令明确拒绝，
防止它重建或移除这些自引用的目录依赖；list/ls/why/outdated 保留。
两种管理工具的依赖协作与升级尚未实现，不能称为统一依赖安装器。

## 事务与进程边界

本地包与 ZIP 限制为 64 MiB、4096 项，拒绝路径穿越、Windows 保留名称、路径大小写别名、
链接/目录联接、非普通 ZIP 文件及加密条目。目录源不能包含安装 staging。

生产 run_profile 持有共享 OS 文件锁，安装器/pnpm 持有排他锁。
Windows 使用 LockFileEx，POSIX 使用 flock，进程退出释放锁，不用遗留 PID 文件判断活跃状态。
多个 Host 可共享读取；开始关闭仍保持锁，直至 Cordis 异步清理排空，才允许安装/卸载。

先准备包快照与文件摘要，再写事务日志、原子移动目录，最后以原子替换 profile/package.json
作为提交点。提交前中断恢复旧状态；提交后中断保留新状态并清理撤销副本。
下一次本地安装/卸载或正式 run_profile 启动都会检查恢复日志。
恢复前核对 profile 摘要和相关包文件；不匹配时停止，交由检查，避免覆盖外部修改。

该合同覆盖实际进程退出和注入的文件发布失败。它不认证断电、磁盘损坏、任意不遵守锁的
外部写入程序，也不包含升级代次、任意插件激活失败的自动回滚或运行中热替换。

## 验证

Python 3.8.10、当前 Windows 上的专项文件：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_python_plugin_distribution.py -q
```

结果：36 passed。实际覆盖目录/ZIP/外围目录 ZIP 的安装、正式 profile 启动、工具执行、
运行时卸载、磁盘卸载、重装、重启与修改源码后重装；无 Node/pnpm 查找；
正式 Web profile 的端口、Connection 和工具执行；版本/依赖/入口/语法失败；
ZIP 路径与别名、源码修改保护、导入失败命名空间撤销、跨进程锁、异步关闭期间锁保持。
补充验证 add/remove 准备过程中外部编辑 profile 时停止事务并保留编辑；初版在读取元数据后
才捕获原始字节可能覆盖新编辑，本轮将快照提前到读取元数据之前，回归固定了该问题。
四项真实子进程通过 os._exit(37) 分别在 add/remove 提交前后中断，随后正式 boot 恢复。
Web 专项未执行新的浏览器 client 交互，不把 Host 成功替代浏览器联合验收。

另以真实 `dsh.py` CLI 子进程验证：在隔离 DSH_HOME、PATH 为空且仅保留 SystemRoot 的
环境中执行 web profile 的目录安装、`--dump-config` 和卸载，退出码均为 0，配置输出包含
该插件。运行时为 Python 3.8.10；临时 home 为 `.goose/out/python-plugin-cli-tb2sub9k`。
这证明实际命令分派与离线安装不需要系统 Node/pnpm，不替代解压发行包的验证。

最终执行 `.venv\Scripts\python.exe -m pytest tests -q
--junitxml=.goose/out/python-plugin-distribution-reviewed.xml`：
**3683 passed、2 skipped、1 warning，302.70 秒，退出码 0**。
JUnit 的 failures/errors 均为 0；原始输出保留在
`.goose/out/python-plugin-distribution-reviewed.log`。
两项 skip 为 Windows 不适用的 POSIX 路径/权限语义。既有 Proactor transport 析构时
Event loop is closed 警告、pytest-asyncio 默认 loop scope 提示及测试 HTTP 断开诊断保留，
没有宣称零警告通过。两轮过渡实现回归为 3675 passed、2 skipped、1 warning（357.28 秒）
与 3681 passed、2 skipped、1 warning（301.17 秒），不替代最终结果。

`scripts/migration.py check` 通过，`ready` 无就绪任务；固定 reference HEAD 已核对。
Python 3.8 compileall 与 git diff --check 通过。这些不认证全项目上游对齐。

## 尚未完成

后续 Workflow/Ralph 占位成功已移除，真实运行与原生固定 Ralph 编排的验证见
[Workflow/Ralph 进展](2026-09-30-workflow-native-ralph-progress.md)。下面保留本批次原始
状态，通用 JS 脚本合同等未完成项仍须继续迁移。

仍须迁移原版 Workflow 的真实执行和 JS 输入合同、JS Host 动态能力、Inspect/Guard
及其他尚未验收模块。插件后续还需创造模式源码导出、版本化升级与失败回退、锁定依赖闭包、
可选 client 的浏览器联合旅程及实际 Portable/Win7 验证。GitHub Release 下载、npm/PyPI
获取源归一化也未由本批次实现。本批次未发布发行物，未发现或登记新的原版 bug。
