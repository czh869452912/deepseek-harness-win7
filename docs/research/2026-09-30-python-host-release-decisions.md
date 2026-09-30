# Python Host 迁移修复与发布实施方向

日期：2026-09-30。产品基线：`6b37d902`，本文对应该基线之后的工作树修复。
固定上游：`cd5ef8148158c3a752a658978873241fdf8e2bbc`。

本文落实 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md) 的后续方向，记录本次实际修复和剩余工作。它不替代迁移任务验收，不认证全项目 parity，也不把设计中的安装命令写成现有使用说明。

## 运行架构

- Host、Cordis 服务、工具和第三方 Host 插件继续采用 Python 3.8.10，保持 Win7 SP1 目标。
- 原版 Web 浏览器代码及预构建 client 资源继续复用；Python 提供 Connection / Typert Remote 和相应服务。
- Node/pnpm 属于开发、前端构建及现有包管理工具链。后续预构建 Python 插件安装须消除普通用户对 Node/pnpm 的依赖。
- QuickJS 是本次对 Workflow 脚本缺口排查时提出的实验候选，并未成为正式依赖；临时安装已移除。嵌入 JS 引擎不会自动提供原版 Node VM、异步桥接或 Win7 兼容性。
- Python 工作流与代码运行能力不等于原版 JS 脚本原样执行。当前 `workflow_service.py` 仍返回占位成功，必须继续迁移真实调度和脚本执行；原版脚本输入的兼容性仍是显式未完成项，不能据此宣称全部迁移完成。

## 软件本体发布

沿用单目录 Portable ZIP，包含固定 Python 3.8.10 运行时、锁定的生产依赖、`dsh`、canonical CLI、原版 Web 和活动包所需 client 资源，以及 `dsh.bat` / `dsh-web.bat`。

发行物须绑定具体产品提交、固定上游、运行时与依赖版本、前端输入哈希和构建来源。现有 `scripts/build_portable.py` 已记录这些输入的一部分；构建器版本、`python38.dll` 文件名和 Windows wheel 标签均不能单独证明提供的运行时及其原生依赖通过 Win7 验证。

验证从实际解压包开始，在不依赖系统 Python/Node/pnpm 的环境完成正式 profile 启动、工具执行、会话持久化及重启恢复。Web 还须通过目标浏览器的实际交互旅程。当前 Windows 开发测试、开发预览和 Win7 认证分别记录；既有 Win7 真机验证暂缓状态保留，不冒充稳定 Win7 发行认证。

应用文件和用户资产分开管理。应用更新保留 profile、用户预设、插件源码、锁定依赖、凭据和会话；带数据迁移的版本还须声明回退边界。发布前检查离线资源完整性和授权文件，并排除真实用户数据及凭据。

当前 `dist` 的存在、旧构建 provenance 或配置 dump 测试不证明当前工作树已发行。本次未重新构建或发布 Portable。

## 第三方插件交付

采用同一套包身份与装配流程，沿用 `package.json`、`dsh.bundle.patch`、profile、Loader 和现有 client 声明。新增 Python 入口、Plugin API 和兼容性描述需要在实施时定义 schema 并验证提供端及消费者。

| 来源 | 实施顺序和用途 |
| --- | --- |
| 本地开发目录 | 首先完成源码持久化、真实加载、执行与可逆卸载。 |
| ZIP 文件 | 首先完成可分享、离线安装的发行容器，复用同一装配流程。 |
| GitHub Release | 发布版本化 ZIP、源码、校验信息、授权和验证范围。 |
| npm / PyPI | 后续可选获取来源，归一到上述流程；不引入第二套插件生命周期。 |

普通 Python 工具插件优先使用标准库和原版通用工具展示。有专用界面时，再由开发端构建可选 client 及 Remote 所需产物，Win7 用户不编译 TS/TSX。

依赖由 profile 管理，不安装进应用自带运行时。离线发行包须包含锁定的传递依赖及哈希；原生依赖单独验证 Win7。共享进程的库版本冲突必须诊断，独立文件夹不自动提供模块隔离。初期不承诺任意依赖或运行中无重启更新。

安装器先检查描述、文件路径和兼容性，再准备候选文件/依赖代次、验证装配、提交并激活。失败或进程中断须恢复旧代次。卸载先撤销运行时注册，再清除引用与文件，明确用户数据保留策略。进程内 Python 插件执行代码，不能将 Cordis realm 或审批描述成任意代码沙箱。

创造模式试验成果须导出为用户项目目录中的源码、包描述、版本与测试，再通过相同打包/安装流程交付。动态 runner 的内存定义不能替代重启后可安装的发行物。

当前 `apps/cli/plugin.py` 仍调用系统 pnpm；Python 描述扩展、ZIP 安装、依赖事务、升级回退和创造模式导出均未由本文实现。下一阶段应先用一个标准库插件证明从本地目录/ZIP 到加载、执行、卸载、重装和重启恢复的完整旅程，再扩展依赖和专用 client。

## 本次迁移版修复

| 问题 | 原版依据 | 迁移版修复和覆盖 |
| --- | --- | --- |
| 凭据读取旧服务名，并在正式启动后继续查询进程环境，漏掉 `.env` 层 | `credentials-local/src/index.ts` 的 `inherited` / `dotenvFallback` 调用 `launchEnvironmentOf` | 统一读取 canonical `launchEnvironment`，兼容两种已有快照表示。验证进程层只读、项目/用户 fallback、存储优先级、启动后环境变化以及正式 Web Remote 的重启恢复。 |
| 并发 domain close 可能重复释放单元，close 调用未立即阻止新写入 | `storage-domain/src/domain.ts` 的共享 `disposal` 与 `runClose` | 调用 close 即关闭写入入口，各等待者共享一次排空与释放；Python 等待者取消不取消 domain 自己的关闭任务。验证持久化、名称占用/重开、失败保持及取消。 |
| facility 逐个关闭，等待第一个 domain 时其他 domain 仍可写入 | `storage-domain/src/index.ts` 的 `closeAll` 使用 `Promise.all` | 对所有已打开 domain 同时发起关闭，再等待排空。延迟第一个写入，验证第二个已经关闭写入入口。 |
| 插件先 unmount，再排空；已提交写入的观察者无法经 hub 读取 domain | 原版 `apply` 的 disposer 先 `closeAll`，再 `unmount` | 保持 facility 挂载直到排空，验证真实插件卸载期间的 `domain/changed` 读取一致性与最终 JSON 文件。 |

这些是迁移版偏差修复，原版在上述位置已有正确实现；本次没有据此登记原版 bug。共享关闭任务使用 Python 3.8 的 `asyncio`，未引入新的原生运行库或修改前端。

已排空的 domain 写入不等于尚未入队的 projection-cache 任务也已排空。缓存任务在等待 Session flush 时与整个 storage/provider 关闭的竞争仍须单独验证；本次不把关闭顺序修复宣称为所有缓存关闭问题已解决。后续还须对齐按配置 backend/routes 的动态注入，当前插件仍硬编码 JSON 服务依赖。

## 验证

专项命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_storage_domain_lifecycle.py tests/test_storage_and_workspace.py tests/test_projection_cache_durability.py tests/test_credentials_launch_snapshot.py tests/test_pi_provider.py tests/test_credentials_parity.py tests/test_settings_credentials.py tests/test_settings_remote.py -q
```

结果：46 passed，退出码 0。环境为当前 Windows / Python 3.8.10。pytest-asyncio 提示未设置默认 fixture loop scope。

全量执行 `.venv\Scripts\python.exe -m pytest tests`：**3637 passed、2 skipped、1 warning**，311.35 秒，退出码 0。仍有既有 Windows Proactor transport 在事件循环关闭后的析构 warning，以及测试 HTTP 连接重置诊断；不宣称无警告通过。

`scripts/migration.py check` 通过，`ready` 退出码 0 且没有就绪任务输出。`git diff --check` 通过。这些检查不认证全项目迁移完成。

本次没有执行原版 domain 全套断言的双侧运行比较、Win7 真机、真实远程模型长运行或新 Portable 发行验收，也未新增可重新验签的正式 parity 证据记录。历史 assessment 的失败结果保留在其原始基线和环境下，不能用本轮通过结果改写历史。
