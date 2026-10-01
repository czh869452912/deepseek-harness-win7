# Python 插件升级、版本查询与源码回退

日期：2026-10-01；起始提交 `b3e70345`；固定参考版本
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。落实
[插件交付评估](2026-09-30-python-plugin-distribution-assessment.md) 的阶段 B
版本替换部分，继续 [目录/ZIP 交付](2026-09-30-python-plugin-local-delivery.md)。
这是原生 Python/Win7 插件交付扩展，不是原版 JS/npm 安装能力的 parity 认证。

## 实际命令

停止目标 profile 后，在 Python 3.8.10 源码环境执行：

```powershell
.venv\Scripts\python.exe dsh.py plugin --profile web upgrade .\python-echo-v2.zip
.venv\Scripts\python.exe dsh.py plugin --profile web versions @example/python-echo
.venv\Scripts\python.exe dsh.py plugin --profile web rollback @example/python-echo
.venv\Scripts\python.exe dsh.py plugin --profile web rollback @example/python-echo 0.1.0
```

upgrade 接受目录、根 ZIP 或单外围目录 ZIP。候选包名必须已经由 Python 安装器
管理；不能覆盖安装自带身份、未管理依赖或用户修改的安装源码。候选版本必须
与当前不同，同一保留版本的文件集合不能被重新定义。版本是非空字符串标签，
没有新增 SemVer / PEP 440 排序、约束求解或“最新版本”查询。

rollback 默认选择最近替换的保留版本，也支持明确的保留版本标签。回退仍通过
同一验证/替换事务，当前源码同时进入历史，因此可以再选择回来。versions 输出
JSON：包名，current/历史的 version、generation、current 标记，并核验实际快照。
versions 为只读共享 lease，可在 Host 运行时调用；upgrade/rollback 要求排他 lease。
存在未恢复 journal 时版本查询拒绝，不在只读查询中改写状态。

本地 Python 命令不要求 Node/pnpm；`upgrade ordinary-package` 仍属于 pnpm
转发。受 Python 管理 profile 中的 pnpm 修改保持拒绝，防止绕过源码快照事务。
CLI help 和示例 README 同步记录新能力；Portable 可传入同样参数，但本轮没有
重新构建 dist，不能把源码命令测试写成当前发行包已更新。

## 所有权与事务

当前源码仍位于 profile 的 `node_modules/<name>`，经既有 Loader / bundle patch
加载，未改内置 registry 或浏览器。`dsh.pythonPlugins[name]` 增加 history，记录
版本、各文件 SHA-256 和由这些字段计算的 generation。旧源码保存在
`.dsh-python-history/<name>/<generation>`，不写入 Portable 的 lib。历史顺序表示
替换顺序；回退选择从 history 移出并成为 current，原 current 追加到 history。

1. 持有排他 ProfileLease，恢复上次 journal，复制和验证候选。验证描述、API/
   Python/Host 下限、Python 语法、路径、JSON/YAML 与文件摘要，不执行插件代码。
2. 核验 current 的文件、身份、版本及 profile 引用。核验保留的历史源码，拒绝
   不一致、修改或 linked snapshot。保留其他依赖、bundle 顺序、用户 patch 和设置。
3. 写 replace journal，记录清单 before/after 摘要和新旧文件集合；依次把旧包移到
   事务 backup、候选移到 current，然后原子发布 profile 清单。
4. 清单未提交则撤销候选并恢复旧源码；清单已提交则核验新源码，将 backup
   存入历史，最后删除 journal。下一次 canonical boot 在共享 Host lease 之前
   调用同一 recovery，完成真实进程中断后的恢复。

恢复先验证所有候选路径和文件，再删除或移动。清单或事务文件被外部改动时，
保留 journal、current 和 backup 并报错，不能盲目删除未知内容。路径在 profile
范围内解析，并拒绝历史/staging 祖先的链接或 Windows junction。文件占用导致
重命名失败时恢复旧文件；若恢复本身仍无法完成，则保留 journal 供后续重试。

安装提交不等于插件可执行。导入失败、apply 失败与业务验证仍在真实运行阶段；
本轮提供显式回退，不自动运行任意插件来猜测是否需要回退。用户停止失败版本，
执行 rollback，然后重新 boot。源码回退不能撤销插件的业务数据迁移，插件数据
应保存到安装目录以外。remove 删除当前安装和引用，保留历史源码快照；尚无
历史归档清理/重新发现命令，不能把它们当作永久公共版本目录。

## 验证

当前 Windows / Python 3.8.10 专项：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_python_plugin_versions.py tests/test_python_plugin_distribution.py -q
```

最终专项 **75 passed，26.10 秒**，退出码 0：原 36 项目录/ZIP 交付测试及新增
39 项版本测试。目录/ZIP 升级、真实 Loader boot/工具执行/回退/再次选择新版本，
真实 Web profile 的端口、Connection / Gateway 及正确版本工具执行均覆盖。
Web Host 验证没有替代浏览器 client 联合旅程。

upgrade / rollback 各五个阶段使用真实子进程 `os._exit(37)`：旧包已移动、候选已
移动、profile 发布前、发布后、历史归档后，再从 canonical boot 恢复并执行正确
工具；提交前清单字节完全恢复。失败版本真实导入报错后，显式 rollback 并成功
boot。清空 PATH 的真实 CLI 进程执行 add、upgrade、versions、rollback、remove，
不依赖 Node/pnpm。另覆盖异步卸载时 Host lease 保持、注入的文件占用错误、外部清单编辑、
版本重复定义、被改动的 current / history、真实 Windows junction、中断后未知
文件保护、三版本历史及保留归档的卸载、plain pnpm 转发。

最终完整回归 `.venv\Scripts\python.exe -m pytest tests`（附 JUnit）为
**4493 passed、2 skipped、1 warning，410.08 秒**，退出码 0。JUnit 共 4495 项，
errors / failures 均为 0；输出为 `.goose/out/python-plugin-versions-full.log` 和
`.goose/out/python-plugin-versions-full.xml`。代码、测试与示例文件在完整回归期间
没有再修改。专项输出为 `.goose/out/python-plugin-versions-focused-final.log`。
保留既有 Windows Proactor transport 的 loop 关闭后析构 warning、专项
pytest-asyncio 默认 fixture loop scope 提示及测试 HTTP 中止诊断，不宣称零警告。

五个 Python 文件通过实际 Python 3.8 AST / 编译检查；migration check / ready
均退出码 0。固定 reference HEAD 未漂移且无 tracked 修改；
`git diff --cached --check` 通过。生产与测试五个文件的最终摘要与完整回归进行中
保存的摘要相同；用户既有未跟踪评估文件未修改或纳入提交。这些检查不认证
Win7 实机或完整上游 parity。

## 后续交付与迁移范围

阶段 B 仍缺持久创造模式源码项目、动态身份到公开包版本的导出和来源记录，
更完整的安装组合/运行验证及业务数据回退合同。阶段 C 的离线传递依赖闭包与
哈希、冲突诊断、Win7 原生依赖认证及预编译 client/Remote 联合旅程仍待实施；
阶段 D 的公共目录索引、GitHub Release/npm/PyPI 获取归一化也未实现。

本轮无新运行时依赖、QuickJS、Node Host 或浏览器源码变更，无新原版 bug；
改进属于此前 native installer 的明确功能缺口。完整 JS Host/Workflow、浏览器/
CDP 及其他未验收业务模块仍需迁移；accepted_upstream 未建立。软件本体仍采用
固定 Python 3.8.10 的单目录 Portable，发行物/依赖/前端输入须锁定并从实际解压
包验收。本轮未构建或发布 Portable，Win7 实机及目标浏览器维持用户暂缓状态。
