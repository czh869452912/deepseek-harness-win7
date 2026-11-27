# Win7 插件管理与索引分发对齐方案

2026-11-27 · 实施方案

## 产品流程

桌面端和 Portable Web 都以主界面的「插件」页作为日常入口。复用固定上游 `dsh-v0.2.2-rc.3` 的客户端、Typert Remote 和交互顺序。桌面菜单打开主窗口的「插件」页。用户可在「已安装」查看详情、配置、启停和卸载，在「发现」选择索引、搜索、查看版本并确认安装。「自定义插件索引」沿用原版的启用方式，源由当前 profile 配置。Win7 用户指南优先给出 Win7 兼容索引，内网部署可直接预配置团队源。 [原版索引指南](../../reference/docs/user/guide/plugin-market.zh.md)

「发现」推荐可安装的 Win7 版本。原版社区目录作为「浏览更多」的外部入口，也可供维护者筛选移植候选。已移植的项目链接到对应 Win7 版。对用户自行添加的索引，Host 在无法确认 Win7 兼容性时使用现有版本不可安装状态。安装前再次验证实际包，版本豁免仅适用于 DSH 版本范围。索引与包声明的匹配以包身份、版本及来源为依据。

## 改造前观察

- 当前桌面 `Ctrl+,` 打开独立窗口，接受本地 Python 文件夹和 ZIP，使用 profile 停机事务及启动健康检查。主窗口也已有原版插件页。 [桌面载体说明](../../apps/desktop/README.md)
- 当前 Web profile 默认以 `pnpm` 路径处理插件包。显式挂载 `PythonPackageBackend` 后，原版 `pluginManager.installBundle` 已在隔离 profile 导入 `dsh-context` ZIP，并在已安装列表返回该版本。 [安装调用](../../dsh/boot/plugin_installation.py) · [Python 包服务](../../dsh/boot/python_package_backend.py)
- 当前 checkout 中，「自定义插件索引」开关持久化，冷启动后出现「发现」。实验性插件卡片还出现缺失图标的包元信息错误。已用真实社区索引走到安装确认，目录的 DSH 版本检查允许一个明确要求 Node 24.9 的插件进入确认。内网相关的索引 HTTP、私有 HTTPS 仓库取包与已挂载后端的管理生命周期已经分别通过定向测试。 [索引版本判断](../../dsh/boot/market_listing_022.py) · [管理器生命周期测试](../../tests/test_rc022_manager_bindings.py) · [HTTPS 仓库测试](../../tests/test_rc022_python_package_acquire.py)

## 实施顺序

### 1. 统一 Host 包管理与桌面入口

在 Web 和 Desktop 的正常启动链路挂载原生 `profilePackages`，由同一 `pluginManager` Remote 驱动本地包导入、索引安装、启停、更新和卸载。Web 使用现有 HMR 和客户端事件反馈生效状态。Desktop 复用已有重启健康检查和失败回滚，使用原版客户端已有的「需要重启」状态，并让重启后的窗口反映最终结果。每个载体使用自身 profile 的包记录、依赖租约及设置。

本地文件夹和 ZIP 继续用于开发和离线分发。桌面保留本地导入作为显式操作，菜单的日常管理入口转到主窗口。将本地导入与 Web 管理页接到同一事务负责人，避免 UI 和停机工具同时写入同一 profile。升级场景读取已有桌面安装记录，保留已选组合包、配置与可恢复代次。修复实验性组合包的资源交付，并检查开关后动态更新和冷启动结果。 [Web 启动](../../dsh/boot/profile_boot.py) · [Desktop 启动](../../dsh/host/desktop/runtime.py) · [Desktop 健康事务](../../dsh/host/desktop/health_transaction.py)

### 2. 发布 Win7 兼容索引与首个安装包

用独立索引仓库维护原版 format-1 `index.json`、图标及发行说明。首个条目使用 `dsh-context`，通过 npm 兼容仓库发布带明确身份的预构建 Win7 包。选择已验证可直接安装的发行快照时，也可使用原版支持的固定 Git 提交和可选子目录，并验证目标机的 Git 前置依赖。当前 `dsh-context` 包标记 `private: true`，发布前需确定可分发的包名与版本，核对与原版同名包及已安装 ZIP 的迁移关系。验证从既有 ZIP 安装切换到索引发行包时的识别和升级行为。GitHub Release ZIP 继续供离线导入。

索引发布时核对 Python API 1、Windows 7 SP1、Python 3.8.10、宿主版本和位数。带 Client 的包还要核对固定 Web 协议目标及资源完整性。版本记录关联实际包和验证结果，详情写明实际依赖及支持范围。Host 在准备与提交时验证包身份、版本、完整性及 ABI，索引条目需指向已验证的 Win7 包。实际来源与条目不一致，或包校验失败时，停止安装并显示诊断。社区条目有可验证的 Win7 对应包时，从用户选择的条目进入对应发行版本。

MinerU 的公开 rc.1 ZIP 针对 `a4c74a91`，当前 Host 目标为 `38a6a5c9`。重新构建并验证后，以新发行版本收录，并注明需要兼容的 MinerU 服务。Univer Office 移植在独立发行包具备相应证据后收录。 [索引发布格式](../../reference/docs/user/guide/plugin-market.zh.md#publish-an-index) · [原版参考生成器](../../reference/apps/plugin-market-generator/README.zh.md) · [Web 包验证](../../dsh/boot/python_web_artifacts.py)

### 3. 支持内网部署

复用同一份索引格式、界面和 Python 包管理流程。每个部署在目标 profile 配置自己的索引 URL。推荐在内网 HTTPS 托管 `index.json` 和图标，使用 `source.registry` 指向内网 npm 兼容仓库。仓库的包元数据提供内网的 `dist.tarball` 与 `dist.integrity`，安装器验证实际收到的归档。Git 方案使用内网可达的固定提交。索引 URL 直接返回 JSON，避免登录跳转。

纯内网 profile 显式配置内网仓库和空 `fallbackRegistries`。索引、图标、包、依赖以及对外展示的文档地址均使用可达的内网资源。验收依赖私有 CA 的环境时，分别核对 Win7 Host、获取安装包的子进程和桌面浏览器的证书信任。需要登录的仓库另行验证元数据请求和归档下载各自的认证路径。 [仓库选择逻辑](../../dsh/boot/plugin_registry_policy.py) · [归档校验](../../dsh/boot/python_package_acquire.py)

## 实施验收

| 场景 | 通过条件 |
| --- | --- |
| 首次打开与已有 profile | Desktop 和 Portable 从正常入口进入同一原版插件页，能开启「发现」、搜索 Win7 索引。冷启动后源和已安装列表可读，旧版已装插件的选择与配置可用。 |
| 首个真实插件 | 从「发现」安装精确的 `dsh-context` 版本，启用后打开面板并读取会话数据。执行停用、再启用、更新和卸载，重启核对状态和功能。 |
| 不兼容与失败恢复 | 原版 Node-only 包、目标不匹配的旧 MinerU ZIP、损坏的归档、取消安装和新版本激活失败都有明确诊断。失败后重读列表和已安装代次，确认仍可启动与恢复。 |
| 内网独立分发 | 在阻断公网的环境中，通过内网索引完成浏览、安装、启用、冷启动和卸载。从请求记录核对索引、资源、元数据与归档均在内网。制造仓库 404 或不可达，确认无公网回退。 |

实现后优先验证变更涉及的安装服务、Typert 消费者、索引与 Desktop 事务。发行资格绑定实际候选、目标架构与解压产物，以统一门禁和相应的 Win7 观察为准。 [仓库验证指引](../testing.md)
