# 0.2.2-rc.3 具体实施路径

日期：2026-11-14（Asia/Shanghai）。目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。
前提：用户认可[目标选型](2026-11-14-upstream-target-selection-update.md)，本轮开始实施准备；不是整版迁移完成声明。

## 实施策略与当前成果

采用一个固定终点、合同分批实现、最后协调切换的路线。直接针对目标最终源码实施，中间版本仅用于理解相邻格式或协议，不安排逐版发行。目标机继续为 Python3.8.10/Win7；现代 Node 只属于 Source 构建和比较环境。

准备阶段已经实施两项发现器修正：

1. 跟随 app-boot 的明确导入和 official-bundles 的明确重导出读取 `PROFILE_TEMPLATES`；支持新版没有 `patchReload` 的字面量定义，不虚构该字段。缺失、歧义、动态 roots 或未知重导出均拒绝。
2. 按 manifest 的 `dsh.bundle.patch` 读取有序字符串/数组，覆盖 Web 的 standard、ptc、minimal、cordis 四份 preset patch。缺失、空值和包外路径拒绝。条件表达式只登记，不执行、不当作实际激活。

实际固定 tree 发现 414 份 manifest（runtime300/frontend83/platform8/tooling11/fixture12），17,797 条全树 Git 变更记录，五种官方 profile：acp/web/headless/sdk/sdk-minimal。这些数量含测试、文档和工具，不代表移植规模或能力完成度。现有 21 组 Source 配置、82 个配对驱动已逐项生成字面量输入审查表；旧路径、旧 pin、导入 helper 和断言语义仍需人工逐合同复核，不能批量替换 SHA 后签收。

独立 Source 放在 `.goose/out/rc022-prep-20261114-01/source`，detached 于固定目标。生产 reference 保持原 pin。工具链和原始执行结果见[准备检查](../../migration/candidates/rc022/preparation-checks.json)。

## S0 的三份交付

| 单元 | 具体操作 | 完成判据及失败处理 |
| --- | --- | --- |
| S0-A：输入与发现 | 固定 target，准备独立 Source，修正发现器，保存 manifest、profile roots、全部 bundle patch 和既有门禁审查清单。 | 实际生成成功，拒绝回归及直接消费者通过；不改生产 pin。已完成的范围见准备回执。 |
| S0-B：原样前端与环境 | 使用独立 Node24.9.0/pnpm11.28.5，首先检查目标锁文件及 install lifecycle；在独立 Source 执行 frozen-lockfile 安装。按其 `scripts/build.ts` 的 artifacts/official 构建路径准备原样资源，记录实际命令、构建环境与输入摘要。 | 原样资源在 Chromium108 和 Electron22.3.27 能加载；检查控制台、缺失 API/CSS、菜单/对话输入、文件/Markdown 预览、插件/预设入口。静态探针只认证 renderer 能力；聊天、上传、重连还须在真实目标 Host 上复验。失败保留，不能先改浏览器业务代码绕过。 |
| S0-C：两个合同样机 | 实际 Source/native v3→v4 父子恢复；原样插件 UI 的 index/list/install/update RPC 需求与本机 Python 分发接口对照。 | 格式探针覆盖子证据、坐标重映射、未知扩展及拒绝不发布；插件样机明确哪些操作可映射到 Python、哪些不支持。仅静态字段映射不算行为通过。 |

依赖安装前必须复核目标自身的生命周期与原生构建要求；不直接复用 `prepare_reference.py`，该脚本绑定旧版 pnpm、旧 Source 和原始前端，不能覆盖成新版本通用准备器。新候选的封存资源必须来自本轮实际构建，不能重标旧 frontend build record。

已检查目标的 `pnpm-workspace.yaml`、根 postinstall 和 native/system 构建入口：依赖安装有明确 `allowBuilds` 列表；根 `install-lefthook.mjs` 在 `CI=true` 时退出，准备运行时应显式设置该进程环境，避免安装 hooks 改变共享 Git 配置。`build:native-system` 使用 `--host-addon-only`，在 Windows 分支直接退出 0；这不是本轮已经执行的原生构建或 Win7 资格。

S0-B 的计划调用为独立 Node 执行已校验的 `pnpm.cjs`，安装使用 `--frozen-lockfile --store-dir <run>/pnpm-store`，随后 `run build:artifacts --profile official`；执行前后核对 Source tracked bytes 和构建输入。子进程 PATH 将独立 Node 目录置前，CI 和缓存/临时目录仅作用于本次进程并在退出后还原。先保存完整 install/build 输出，失败不修改锁文件或上游源码重试。该命令路径已静态核对，尚未执行；不把依赖安装或 artifacts 构建称为完整测试门禁。

S0-B/C 全部得出可实施结论后，才把下表细分为正式迁移任务及可验收合同。当前候选区不冒充 CLI 的并发任务领取或自动状态迁移。

## 主线合同与依赖顺序

下表路径是初步影响面；实现时包含必要的提供端、直接消费者和回归，不构成编辑白名单。

| 顺序/合同 | 实现边界及现有落点 | 验证与依赖 |
| --- | --- | --- |
| C1 基础运行时与装配 | 审计 `dsh/cordis`、`dsh/boot` 的 Fiber 配置、依赖、效果释放、Loader/Include 与 profile patch 数组；同步 canonical app/profile boot 和元数据。先提供后续合同所需原语，完整产品切换留到 C9。 | S0 后开始；固定 Source 的配置/依赖/卸载/失败传播配对。`official-bundles`、引导必需项和可选加载失败不能仅以 manifest 有对应类判断。 |
| C2 v4 格式与准入 | 新增显式 `dsh/session/format_v3_to_v4` 邻接边，更新 catalog 的候选入口；实现工具角色、来源、扩展命名空间、事件坐标、delivery 代际和父目录证据。 | 复用并复核 v0→v3 前置边；v4 原生输入走原生验证，不再次执行迁移。跟随目标规范及原测试；部分 decode 输出不等于 finish 成功。 |
| C3 存储发布与恢复 | `dsh/session` 的 preparations、generation、JSONL backend/handle、lease、lineage、只读观察和查询；收集直属子级事实并绑定同一恢复快照。 | 依赖 C2；真实文件/跨进程 lease、压缩与明文、源修订漂移、排他 successor、取消和失败保留。转换失败不得发布或覆盖源代际。 |
| C4 Session/Projection/Agent | 分离 snapshot、event log、state 和 projection 订阅；异步注册并持有 projection handle，补齐 append 单条/批量返回合同；同步 `dsh/core/agent_current.py` 等 Agent、token meter、history/query 和审批消费者。 | 依赖 C1/C3；无丢失/重复事件的快照→订阅交接、取消清理、释放后读取和冷恢复；所有权归相应服务，不能控制器重复注册。 |
| C5 模型与工具执行 | `dsh/core/tools.py`、`dsh/core/agent_loop_current.py`、`dsh/llm`、`dsh/workflow` 的按步 resolve/executable、提前固定模型、native/PTC 执行器、批次并行、错误及 ABORTED 分类。 | 依赖 C1/C4；模型声明、PTC 绑定与执行准入必须一致；覆盖换模型、重试、缺 provider、取消、超限及日志消费者。旧 `tools.mode`/环境变量迁移按目标拒绝/overlay 规则。 |
| C6 子代理与 Team | `dsh/subagent`、`dsh/team` 实现同级唯一名称和完整路径、旧 id 回退、parent/caller delivery、目录 v3 载荷、Team ownerName 与中断权限；同步 SDK/PTC/Remote。 | 依赖 C3–C5；重复/非法名称、嵌套协作、消息等待不重复唤醒、目录损坏/不可读、普通 fork 不被识别为 child、冷恢复和停止清理。 |
| C7 Connection 与应用 Remote | `dsh/host/connection`、`dsh/typert`、应用 controllers 的 Peer/Principal/admission、方法权限、上传回执、发送确认/幂等、历史投影和重连。 | 依赖 C4–C6；canonical `/api/remote.mux` 实际往返和非 owner 拒绝。新旧 renderer/controller 联调不能用旧 ApiProxy 或双业务 SSE 代替。 |
| C8 产品服务与插件交付 | `dsh/boot/python_plugins.py` 等 provider 对接插件索引/管理和事务回退；适配 `dsh-doc` 的 Python Host 文档，保持 JS Client；同步凭据/模型/Search/Fetch、动态 MCP、宿主级 schedule、预设和终端。 | 依赖相应 C1/C5/C7；实际 UI→服务→落盘→冷启动旅程、失败可诊断及卸载无残留。索引支持范围和 Python 包格式要准确，不承诺任意 npm Host 插件。 |
| C9 协调切换与发行准备 | 统一切换 reference、能力映射/注册表、运行时输入、原样前端、profile/preset 和门禁配置；Desktop Electron22 适配及打包消费者一起审查。 | 前述合同定向通过后执行；先检查四入口、真实服务和旧数据的定向集，再冻结稳定候选跑 `verify_release.py`。双架构/管理员生命周期/Win7 按约定分别保留证据。 |

各合同在提供端和消费者闭合后提交可审查变更。纯库先通过显式候选入口验证；服务接入沿用统一 Context，不建立跨插件私有导入网。现有 `_current` 已指向旧活动合同，不全仓复制为第三套 `_current`；只在格式/协议边界保留必要版本区分，完整装配在协调点切换。

## 需要优先查清的范围问题

- **PTC/Node：** 新版 base 出现 Node PTC runtime，目标机仍不能依赖现代 Node。须核对实际激活链并提供经审查的 Python runtime 适配/overlay；native 默认路径与 PTC 可选路径分别验收，不能忽略隐藏依赖。
- **Office 与 native/system：** Web manifest 直接引用 tool-office/workspace-dependencies，Source 构建也增加 native/system 路径。仅凭“以前可选”不足以省略；S0 要判定实际必需服务、按需资源和目标 OS/位数，再决定原生替代或明确产品 overlay。
- **插件安装：** 先迁移原样 UI 所需的真实 RPC 和本机 Python 事务服务；npm 代码语言、engines 兼容声明和索引可见性分别处理。失败不能留“已启用”假状态。
- **SDK/ACP：** 旧配对驱动含已变化/删除的 Source 路径，必须连同新的服务合同更新；不能批量重写 pin 或将未运行的配置标作通过。
- **Minimal 与附加能力：** 保持本项目约定双工具 overlay；LSP、Worktree、会话导入和外部 CLI 按有效依赖及明确产品需求立项，不能为完成包清单全部引入。
- **Windows ACL：** issue #4 独立定位。新授权目录限定为文件工具，并不证明终端/PTC 获得相同权限或旧问题自动修复。

## 数据保护、验收与退出机制

所有探针使用自有 `DSH_HOME`、受控父子会话和临时 profile，不指向实际用户会话。旧代际、旧程序可读取的备份和原发布回执保留。v4 外层格式不变也不代表新 subagent/catalog v3 和 Team 载荷能被旧程序读取；回退必须回到未被新程序写过的隔离副本，不能承诺新数据自动降级。

每批按实际合同选原失败、提供端、直接消费者和相关回归，保留命令、状态、日志/XML与配对观察；稳定切换前不重复完整回归或重建 Portable。完整验收只绑定一个冻结候选和实际 archive，目标与原始观察不相同的历史资格不能复用为新资格。

S0 若发现原样 renderer 或必需宿主合同不成立，记录失败和具体边界，再评估范围/rc.5 备选。没有实际探针结果前不承诺整版工期。完成标准是约定能力真实运行且依赖、失败、卸载和恢复闭合，不是 414 个包名各有一个 Python 类。

资源保留由 rc022-S0 持有：独立 Source 和构建工具仅保留到 S0 探针结束或目标被否决；届时保存观察后移除自有 checkout/依赖。已结束测试的合成仓库和下载传输包在本轮清理，命令/XML/摘要与必要失败观察保留，详见准备回执。
