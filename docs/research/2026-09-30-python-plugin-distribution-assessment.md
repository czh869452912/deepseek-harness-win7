# Python 第三方插件发布、获取与创造模式交付评估

日期：2026-09-30。

分析基线：`8fe3ac13`，固定上游目标 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。

本文评估 DeepSeek Harness Win7 在 Web 核心链路初步可用之后，如何支持第三方 Python 插件的开发、分享、安装与更新，以及如何将创造模式生成的动态插件转化为可重复安装的发行物。本文是设计评估，不是已实现的插件规范或全项目上游对齐认证。

后续采用的发布方向、凭据/存储关闭修复及新回归结果见 [Python Host 发布实施记录](2026-09-30-python-host-release-decisions.md)。本文的历史基线、验证结果和未实施能力仍按当时事实保留。

本地目录/ZIP、实验 Python 入口与 API 的后续实现见 [本地交付实施记录](2026-09-30-python-plugin-local-delivery.md)。下文仍保留原分析基线；当前实现范围和剩余依赖、升级、client 与发行验证以该记录为准。

后续源码版本升级/回退已有实施；创造模式指定版本导出、显式发行文件集、Host/用户预设装配及实际安装重启验证见 [源码项目交付记录](2026-10-01-python-plugin-source-export-progress.md)。下文历史基线不据此改写，Client、依赖闭包、多来源获取与最终发行仍须分别验收。

预编译 Client / Python Remote 联合插件的原生打包、安装、浏览器调用及升级回退见
[Web 联合交付记录](2026-10-01-python-plugin-web-delivery-progress.md)。原版 HMR 的
boot graph 保留至页面刷新，卸载后旧 Client 调用必须被 Host 拒绝；依赖闭包、
通用动态 Client 导出和最终发行仍未由此完成。

创造模式导出的 Host placement Client 已有原生 `build`、源码 receipt 与真实
原版 evaluator/Remote 联合验证，见 [Client 源码构建记录](2026-10-01-python-plugin-client-build-progress.md)。
Session Client 所有权、完整动态 runner 治理、依赖与多来源获取仍须实施。

后续 Session placement 的 preset 所有权、Agent lookup 路由与原版侧栏切换联合
验证见 [Session Client 交付记录](2026-10-01-python-plugin-session-client-progress.md)。
完整治理、依赖、用户 preset 引用清理、多来源获取和最终发行仍须分别完成。

后续已增加指定归档 SHA-256 的原生 HTTPS ZIP 获取，以及安装／版本历史的来源
记录，见 [HTTPS 获取实施记录](2026-10-01-python-plugin-https-acquisition-progress.md)。
它进入相同本地 store，不认证 npm/PyPI 获取、公共目录、依赖闭包或实际公开发布。

后续已接通作者预展开的纯 Python 精确依赖闭包、profile 冲突检查和原生 import
租约，见 [依赖闭包实施记录](2026-10-01-python-plugin-dependency-closure-progress.md)。
wheel、原生库、版本范围求解、宿主兼容复用与最终发行继续实施。

后续候选构建保留旧产物、实际运行时身份检查，以及解压 Portable 内的插件交付、
会话冷恢复和原版浏览器验证见
[解压运行时门禁记录](2026-10-02-portable-extracted-runtime-progress.md)。
它不认证 Win7、公开发布、软件更新资产保留或全项目迁移完成。

## 1. 结论

建议采用 **Python Host 插件为主体、Web 客户端资源可选、统一包描述与 Cordis 装配** 的路线。

第三方插件优先通过本地开发目录、ZIP 文件和 GitHub Release 交付。保留现有 `package.json`、`dsh.bundle.patch`、profile 与 Loader 解析模型；npm 可以作为额外获取渠道，但普通用户安装预构建插件不应以 Node 或 pnpm 为前提。PyPI 可以承担 Python 库依赖分发，也可以成为后续插件获取来源，但最终应归一到同一套插件身份、兼容性校验和装配流程。

前端编译与用户运行环境应分离：TS/TSX、CSS 及相关打包工作在现代开发电脑或 CI 上完成，Win7 端只加载发行包中的 Python 代码和浏览器产物。普通工具插件应优先复用原版 Web 的通用工具展示，只有需要新的面板、设置或交互时才增加 client 半部。

当前最重要的工作是形成一个可验证的交付闭环，而非先建设插件市场：

```text
开发源码 -> 试运行 -> 验证卸载 -> 打包 -> 安装
         -> 重启恢复 -> 升级/回退 -> 分享
```

## 2. 当前仓库具备的基础与缺口

### 2.1 已有能力

| 能力 | 当前实现与范围 |
| --- | --- |
| Profile 包管理入口 | `apps/cli/plugin.py` 在 profile 目录调用系统 pnpm，并在成功后协调 dependencies 与 `dsh.profile.bundles`。 |
| Bundle 组合 | 包通过 `dsh.bundle.patch` 声明补丁，启动由 canonical profile boot 组合配置。 |
| 内置 Python 实现解析 | `dsh/boot/plugin_registry.py` 为安装自带的 npm 包身份提供 Python 实现映射。 |
| 外部 Python 加载 | `dsh/cordis/loader.py` 支持模块、文件与类入口；包入口解析也支持 `.py`。外部插件并非只能通过修改内置映射表加载。 |
| Web 扩展发现 | `LoaderClientModuleRegistry` 从活动 Loader 来源读取 `dsh.client` 和 `exports["./client"]`，协调客户端模块图及卸载。 |
| 动态 Python 插件 | 创造模式工具可定义、运行、更新和停止动态插件；Host 代码按 Python 执行，并要求暴露 callable `plugin`。 |
| Web 核心旅程 | 已有正式 profile 下的工作区、会话、模型请求、工具、恢复、反馈和日志导出验收记录。 |

外部 Python 文件加载和带 client 声明的 Python 包已有局部测试基础，见 `tests/test_dynamic_plugin_loader.py` 与 `tests/test_client_modules_loader.py`。这些测试证明相关加载机制存在，不证明第三方安装、依赖解析和浏览器联合旅程已经完整可用。

### 2.2 尚未形成的发行能力

- 尚无统一的 `dsh.python` 发布入口与兼容性描述协议。
- 现有 plugin CLI 没有独立的 Python 插件 ZIP 安装流程，仍依赖系统 pnpm。
- 尚无完整的第三方 Python 依赖解析、锁定、冲突诊断和离线安装闭环。
- 动态插件定义主要存放在 runner 的内存对象中；尚无将这些定义导出为持久源码包、跨启动安装和升级的完整流程。
- 现有装配能力不能替代发行包检查、安装事务、失败恢复及软件升级后的用户资产保留验证。

另外，Loader 当前对部分 JS/TS Host 文件使用 `create_js_mock_plugin` 进行测试兼容模拟。第三方正式安装路径必须明确拒绝不支持的 Host 实现，不能将模拟装配视为真实 JavaScript 执行成功。已经移植的内置包映射和原版浏览器客户端复用是不同的情况。

## 3. 插件结构与公共接口

### 3.1 统一发行单元

建议一个发行包同时携带功能需要的 Host、client 和装配信息：

```text
foo-1.0.0.zip
|-- package.json
|-- cordis.patch.yml
|-- python/
|   `-- dsh_foo/
|       |-- __init__.py
|       `-- plugin.py
|-- client/                    # 可选，已构建的浏览器产物与资源
|-- wheels/                    # 可选，已锁定的 Python 依赖闭包
|-- lock.json
|-- README.md
`-- LICENSE
```

`package.json` 是结构化包描述文件，读取它不需要 Node。安装器可以把已验证的包落入现有 profile 包解析位置，继续使用 Loader 和 bundle 组合，不必另建第二套运行时插件注册体系。

ZIP 不是新的运行模型；它是完整预构建包的交付容器。npm `.tgz` 或 wheel 也可以作为其他交付容器，前提是最终能得到一致的插件描述、文件集合和装配结果。初期应先完成一种容器，避免同时实现多个安装后端。

### 3.2 Python 描述扩展

建议新增 `dsh.python`。以下是需要定义的语义，具体字段名和 schema 应在实现前冻结：

| 元数据 | 用途 |
| --- | --- |
| 包名、版本、作者与源码地址 | 标识来源、版本和可追溯源码；第三方使用自己的命名空间。 |
| Python 源码根与模块入口 | 明确从哪个包内目录加载哪个模块及导出；优先规范模块入口，而不是依赖任意全局 `sys.path`。 |
| Plugin API 版本 | 标识宿主保证的公共接口范围，与应用版本分开。 |
| Python 与宿主版本要求 | 安装前判定兼容性；支持 Python 3.8.10 不等于必须拒绝所有更高 Python 版本。 |
| Python 库依赖 | 描述运行所需库，并在发行时解析为包含传递依赖的固定闭包。 |
| 所需服务及装配位置 | 区分服务依赖与库依赖，说明功能属于 Host 或会话预设。 |
| 平台、架构及验证信息 | 区分纯 Python 与原生依赖，记录实际验证的目标环境。 |
| Client 与 Remote 要求 | 继续使用上游 client 声明，并明确需要的通信类型产物和服务接口。 |

包名只能指向包自身被允许发布的入口，不能借助入口映射重新定义任意内置插件身份。Python 入口必须解析为真实实现，缺失或不支持时应给出明确错误。

内置 registry 继续承担安装自带实现的映射，第三方发布不应要求修改它。外部插件的来源解析应沿用 profile-local 优先和安装自带 fallback 的所有权边界；这不等于允许第三方 Python 模块覆盖核心 `dsh` 包。

### 3.3 公共 Plugin API

需要明确哪些 Python 接口受到兼容承诺，避免第三方依赖所有内部 `dsh.*` 路径。可通过薄的公共导出层提供 Plugin、Context、Schema、工具注册和生命周期接口，初期不必复制整个内部目录结构。

先将 API 标记为实验范围，通过示例插件与外部试用验证后再冻结稳定版本。服务接口、事件和 Remote 协议也属于兼容合同，不能仅凭 `Plugin` 类未变就断言插件 API 没有变化。

插件仍须遵守 Cordis 的服务依赖、动态服务访问与可逆注册约定。安装器负责文件和环境；插件生命周期负责工具、事件、服务、路由等运行时注册。二者必须分别验证。

## 4. Python 依赖与 Win7 运行约束

### 4.1 Profile 所有权

Python 依赖应由 profile 管理，不能写入 Portable 自带运行时。例如可使用 profile 下的版本化依赖目录，并记录其所属安装代次。

独立目录能避免程序更新覆盖用户依赖，但不会自动实现同一进程内的库版本隔离。Python 模块缓存、插件导入以及宿主自身依赖都会影响解析；仅增加 `sys.path` 或使用动态模块名，不能保证每个插件各用一套相互冲突的库。

初期应优先支持标准库和已经验证的依赖集合。同一 profile 内出现无法合并的约束，或第三方依赖与核心依赖冲突时，应拒绝安装并报告冲突。确实需要独立库版本的功能，可后续设计子进程服务与 RPC 边界，不能假定任意 Cordis 插件都可以无改动迁移到子进程。

### 4.2 固定依赖闭包

离线包应包含所有必要的传递依赖及对应哈希，而非只提供顶层 requirements。记录至少需要包含 Python/ABI、架构、插件版本、依赖版本、文件哈希和构建来源。

推荐安装阶段只使用经过验证的 wheel 或发行工具预生成的文件集合，不在普通用户的 Win7 电脑上编译源码包。实现还需要明确 Portable 中如何提供 wheel 安装能力，不能假定系统已安装 pip。

`cp38` 或 `win_amd64` 标签不能单独证明 Win7 可用。原生库可能使用更高版本 Windows API 或依赖额外 DLL；依赖闭包必须有 Win7 验证记录。常规 Windows CI 与 Win7 真机验证应分别标注。

### 4.3 信任边界

进程内 Python 插件具有宿主进程的操作权限，能直接调用 Python 文件和进程 API。Cordis realm 隔离、独立依赖目录及工具审批均不能作为任意 Python 代码的安全沙箱。

因此，导入或激活插件就是执行代码的边界。安装阶段可以先检查描述和文件，运行验证则应在专门的测试进程与测试数据中进行；这种测试进程隔离也不能替代恶意代码沙箱。哈希用于确认内容一致，不代表作者可信或功能安全。

## 5. Web 资源的构建与复用

开发者可以在现代 Windows、Linux 或 macOS 上构建前端，发行包携带已经生成的 JS/CSS、静态资源，以及 Remote 契约所需的类型产物。Win7 用户运行这些浏览器资源时不需要执行 TS 编译或 Node 构建脚本。

兼容性需要同时满足：

1. JS 语法、浏览器 API 和 CSS 能力与已选定的 Win7 浏览器匹配。转译不能自动补齐所有浏览器 API。
2. Client 声明、模块格式、依赖图与当前上游模块加载器匹配。不能把任意打包器的输出都当作可加载 client bundle。
3. Connection、Typert、Remote 和宿主服务合同与 Python 提供端一致。
4. React、Cordis 等共享运行时按现有 external/服务约定复用，避免无意携带重复实例。
5. 所有运行资源随发行包交付，离线安装后不存在遗漏的运行时下载。

复用原版 client 产物不代表复用原版 Node Host 实现。若客户端依赖某个未移植的 Host 服务，仍须提供对应 Python 实现，或者明确声明不支持。

官方 Node 16 的平台文档将 Windows 最低支持版本列为 Windows 8.1/2012 R2。因此，不应把附带官方 Node 16 作为 Win7 发布方案。Electron 22 是最后支持 Windows 7/8/8.1 的 Electron 主版本，但这不能推出独立 Node 16 同样支持 Win7，也不能替代本项目的浏览器验证。

## 6. 插件发布与获取

### 6.1 初期渠道

| 渠道 | 适用场景 | 交付要求 |
| --- | --- | --- |
| 本地开发目录 | 创造模式开发、作者调试 | 持久保存源码、描述与测试；开发安装行为明确。 |
| ZIP 文件 | 用户之间直接分享、内网和离线部署 | 包完整、入口固定、依赖闭包可验证。 |
| GitHub Release | 公开版本发布 | 版本化源码、安装包、校验信息、说明和验证范围。 |
| npm | 已有 npm 发布流程或上游生态接入 | 作为可选获取后端，不能仅凭安装成功断言 Python Host 可运行。 |
| PyPI | Python 库及未来 wheel 插件来源 | 保留统一插件描述和装配语义，不直接污染自带运行时。 |

安装器初期应以本地包导入为核心。网络下载和目录索引后续可以复用相同安装流程。公开目录只需先记录身份、版本、下载地址、兼容性和验证信息，不必立即建立市场 UI。

### 6.2 作者发布流程

```text
版本化源码
  -> 构建可选 client
  -> 解析并锁定依赖闭包
  -> 校验发行文件集合
  -> 在干净 profile 安装和验证
  -> 生成版本包及校验信息
  -> 发布到 Release 或交付文件
```

发行测试应从实际安装包开始，不能只运行源码目录中的插件测试。包应包含使用说明、许可证和必要的依赖授权信息，并排除真实凭据、用户会话、工作区文件和本机绝对路径配置。

## 7. 安装、升级与卸载事务

当前 `apps/cli/plugin.py` 的 pnpm 调用和 bundle 协调不足以承担完整的 Python 安装事务。新能力应保留 canonical CLI/profile 入口，定义明确的扩展命令或参数，并说明与现有 pnpm 转发行为的兼容关系。

拟议的本地包安装入口可采用 `dsh plugin --profile web add .\foo-1.0.0.zip`，但该语法目前没有实现，不能当作现有使用说明。

建议安装过程分为：

1. 在暂存目录检查包结构、包内路径、入口、版本要求、依赖闭包和 client 产物，不执行任意包安装脚本。
2. 构建候选依赖目录，诊断与核心和现有插件的冲突，记录锁定信息。
3. 生成候选 profile 组合，验证所需服务、Host/会话所有权和运行旅程。
4. 保留可恢复的旧代次，提交新的文件、配置及依赖状态。
5. 按明确策略重启或激活；失败时恢复旧代次，并保留可诊断结果。

只回滚 `package.json` 和 lockfile 不足以恢复安装。包目录、依赖文件、bundle 列表、用户补丁和运行状态都可能已经变化。应设计代次或事务记录，并处理进程中断以及 Windows 文件占用情况下的恢复。

第一阶段可以采用停用、替换、重启生效的策略。涉及原生库或依赖版本变化时，不承诺运行中无重启更新。更新业务数据的插件还须单独声明数据迁移与回退能力，文件回退不能自动撤销业务数据迁移。

卸载需要先撤销运行时注册，再移除该插件的装配引用和安装文件。共享依赖只能在没有使用者时移除；用户数据的保留或删除应有明确策略。

## 8. 创造模式成果的持久化与分享

动态 runner 适合快速试验，但会话中的动态身份和代码定义还不是完整发行包。需要增加从试验成果到持久源码、测试和发行物的转换能力。

推荐流程：

1. 在用户所有的插件项目目录中保存源码与描述；动态试验结果导出时保留明确的代码版本。
2. 检查功能应该挂到 Host 还是会话预设。会话贡献的工具、persona 和 prompt 放入用户预设；共享注册表和跨会话服务放入 Host。
3. 用可重复测试验证功能和卸载，检查是否意外依赖当前会话、已有凭据、临时服务或内存状态。
4. 生成独立版本包，并写出依赖、配置示例、兼容要求和使用说明。
5. 在干净 profile/预设安装，重启后重新验证，再交付给其他用户。

应维护稳定的插件包名与发行版本，并记录动态 `pluginId/packageId` 到导出源码版本的来源关系。动态版本 ID 不应直接替代公开包版本。

创造模式修改用户预设和插件项目，程序安装目录中的内置预设仍由发行版本管理。更新 Portable 时保留用户插件、profile、锁定信息和用户预设，避免将自进化等同于直接修改正在运行的核心安装。

共享 Python 插件可以首先不带 client。新增工具的通用展示往往已经足够；确实需要新界面时，再提供预编译 client 或在现有动态 client 合同允许的范围内开发 JavaScript。客户端试验代码也需要转化为可独立安装、重启加载的产物。

## 9. 分阶段交付与验收

| 阶段 | 交付目标 | 必须形成的验收证据 |
| --- | --- | --- |
| A：开发预览 | 薄的实验 Plugin API、Python 入口描述、示例插件、本地目录和 ZIP 安装/卸载 | 无 Node/pnpm 的 Python 3.8.10 环境，从安装包完成加载、执行、卸载、重装和重启恢复；安装失败不损坏已有 profile。 |
| B：创造模式交付 | 持久源码项目、导出、版本记录、升级和回退 | 动态试验成果在干净环境安装；来源可追溯；失败版本可回退；会话与 Host 所有权正确。 |
| C：完整离线与 Web 扩展 | 依赖闭包、冲突诊断、预编译 client、Remote 类型产物 | 断网环境完整安装；原版 Web 浏览器实际执行 client/Host 联合旅程及卸载；指定 Win7/浏览器环境验证。 |
| D：发现与规模化 | 公共目录索引、可选 npm/PyPI 获取后端 | 多来源统一安装结果；版本和兼容信息可查询；获取失败不影响当前安装。 |

阶段 A 优先使用标准库插件，避免同时引入复杂依赖和 UI 扩展。每个阶段使用同一个真实示例形成完整旅程，再扩大支持范围。共享接口变更须包含 Loader、profile、client 和测试消费者的必要改动，不能把报告或文件清单当作完成证明。

软件本体继续发布固定运行时的 Portable 包。发行构建应锁定 Python、内置实现、上游前端产物和平台依赖，记录来源与校验信息；用户插件单独由 profile 管理。开发预览、当前 Windows 验证、Win7 验证和稳定发行应使用不同的明确状态。

## 10. 本次评估的验证结果与限制

评估期间未修改产品代码。基线 `8fe3ac13` 下执行：

```powershell
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe scripts/migration.py check
.venv\Scripts\python.exe scripts/migration.py ready
```

全量 pytest 结果为 **20 failed、3605 passed、6 skipped、1 warning**，耗时 547.49 秒，退出码 1。失败分布：

- 模块 fallback 闭包及扫描次数断言：2 项。解析结果包含测试预期集合之外的依赖，扫描次数触及断言上限。
- Headless HTTP、重试和 PI 旅程：12 项。其中部分输出显示会话临时文件创建时报路径不存在；尚未在本次评估中完成根因确认。
- PI 凭据行为断言：1 项。设置被启动环境以只读方式提供的凭据引用遭到拒绝。
- 当前 `dist/dsh-win7-portable` 冒烟：5 项。目录中缺少 `python.exe`，不能作为完整 Portable 发行物。

warning 为 Windows Proactor transport 在事件循环关闭后的析构诊断。此结果是当前检出与本机环境的实测结果，不应改写成历史验收中的全量通过，也不直接推导为 Web 核心链路整体不可用。

`migration.py check` 通过，确认记录和固定 inventory 有效；`ready` 返回 0 且无就绪任务输出。两者均不认证第三方插件能力或全项目 parity。

本次未修复上述失败、未重新构建 Portable、未执行 Win7 真机或第三方发行包浏览器旅程，也未产生可重新验签的原始回归日志归档。发布候选需要在明确的干净环境重新执行门禁、保留原始证据并完成目标平台验证。本文所有新增安装、导出和回退流程均为待实施建议。

## 11. 依据

### 仓库源码与测试

- [插件 CLI](../../apps/cli/plugin.py)
- [Profile 解析和组合](../../dsh/boot/profile.py)
- [Canonical profile boot](../../dsh/boot/profile_boot.py)
- [内置插件解析表](../../dsh/boot/plugin_registry.py)
- [Cordis Loader](../../dsh/cordis/loader.py)
- [Cordis 插件形态](../../dsh/cordis/plugin.py)
- [Loader 驱动的 client 模块发现](../../dsh/host/client_modules/loader_registry.py)
- [Typert 类型产物加载](../../dsh/typert/loader.py)
- [动态 Host Runner](../../dsh/extensions/host_runner.py)
- [创造模式工具](../../dsh/extensions/cordis_manager.py)
- [Python 动态插件测试](../../tests/test_dynamic_plugin_loader.py)
- [活动 client 模块与卸载测试](../../tests/test_client_modules_loader.py)
- [Portable 构建](../../scripts/build_portable.py)
- [迁移记录入口](../../migration/README.md)

### 已有验收记录

- [Web 核心可用链路](2026-09-29-web-usable-baseline.md)
- [Web 设置专项](2026-09-30-web-settings-acceptance.md)
- [长运行、预设共存与工作区](2026-09-30-web-long-run-and-presets.md)

这些记录分别声明了自己的提交、环境和验证范围，不能替代本次实测或未来发行候选验收。

### 平台官方资料

- [Node.js v16.20.2 平台支持矩阵](https://github.com/nodejs/node/blob/v16.20.2/BUILDING.md)
- [Electron Windows 7/8/8.1 支持终止公告](https://www.electronjs.org/blog/windows-7-to-8-1-deprecation-notice)
