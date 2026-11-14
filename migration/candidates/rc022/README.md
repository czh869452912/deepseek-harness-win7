# 0.2.2-rc.3 实施准备区

日期：2026-11-14。用户已认可[目标复核](../../../docs/research/2026-11-14-upstream-target-selection-update.md)，授权评估实施路径并准备实施。

- 固定目标：`dsh-v0.2.2-rc.3 / 38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。
- 当前上游生产 pin：`a4c74a91e06b00fe0b0937bde982170c526cc842`。代码基于当前工作区，包含已完成的创造模式适配。
- 本目录名称 `rc022` 明确区别于历史 `rc3`（0.1.5-rc.3）；不是新的活动基线或发行资格。
- 详细执行顺序、合同和准入标准见[实施路径](../../../docs/research/2026-11-14-rc022-implementation-path.md)。
- [准备检查](preparation-checks.json)记录实际执行的发现、回归、源码与工具准备结果；完整生成清单和日志留在自有忽略输出目录。

下一工作单元是 S0-B：使用独立 Source 与固定现代工具链完成依赖安装和原样前端构建，随后执行 Chromium108/Electron22 探针。S0-C 的 v3→v4 与插件协议探针尚未执行。所有迁移合同保持未签收。

2026-11-15：已按用户授权开始分批实施并提交。C2-A 的显式[值转换助手检查](value-helpers-checks.json)完成 Source/native 配对；仅覆盖工具结果角色、消息来源和扩展内容，不代表完整 v4 格式、持久化或消费者闭合。Source 安装通过，artifacts 构建正在独立候选环境推进。

生产 reference、注册表、运行时/前端输入清单和旧迁移任务本轮不切换。待合同实现与消费者定向检查闭合后，统一执行显式 promotion；`accepted_upstream` 不随准备记录自动变化。

2026-11-15：C2-B [准入校验助手](admission-guards-checks.json)完成 620 组固定 Source/native 对照、80 项原版测试及 43 项 Python 定向测试；覆盖 system/developer 字段、来源与退役语法的拒绝边界，仍未接入目录或生产持久化。S0-B 原版 artifacts 8 个构建阶段已通过，浏览器探针发现旧浏览器新增 API 需求，继续核实兼容适配。

2026-11-15：S0-B [构建与浏览器边界记录](source-build-browser-checks.json)完成：固定原版构建 8/8 通过。Host 的 `toSorted` 兼容补齐后，Chromium108/Electron22 模型菜单与插件页导航可操作；截图同时确认 CSS Anchor Positioning 缺失导致菜单定位错误，插件清单加载完成状态也尚未验证。二者仍是后续准入工作，不标记视觉、插件或 Web 合同签收。

2026-11-15：C2-C [子会话事实与引用检查](child-facts-checks.json)完成 1025 组 Source/native 对照、54 项相关原版测试、59 项 Python 定向测试；历史自有 descriptor 选择、fork not-started 身份、未知可忽略事件归属和移动后的本地引用已按独立助手落地，完整流式迁移与生命周期关系仍待实现。

2026-11-15：C2-D [显式格式库检查](format-library-checks.json)完成 1321 组固定 Source/native 对照、404 项原版格式包测试和 778 项 Python 定向回归；新增流式 v3→v4、V4 编解码、生命周期/压缩/工具/重试/标题/命令/目录/交付关系校验。测试合成工作区清理完毕；这些 API 已作为独立版本模块导出，生产 format catalog、CurrentSession、持久化与消费者尚未切换，C2 不据此整体验收。

2026-11-15：C2-E [历史目录检查](historical-catalog-checks.json)完成 1426 组固定 Source/native 对照、155 项原版提供端测试和 785 项 Python 定向回归。独立 V0–V3 历史读取用于收集迁移前置事实，修正旧物理头与损坏头结果的字段输出顺序；生产目录仍为 V3。已删除本批用完的合成夹具，保留初次失败诊断与所有运行记录。

2026-11-15：C3-A [历史前置事实读取](catalog-prerequisite-checks.json)完成 240 组明文/zstd 实际文件对照、124 项原版提供端测试与 899 项 Python 定向回归。新增只读解码、子会话局部失败隔离及物理身份复核；补齐固定原版对历史 descriptor v1/v2 的读取规则。本批原始诊断和矩阵保留，已用完的实际文件夹具及时删除。此阶段仅证明 V0–V3 前置事实读取，V4 子会话读取、父目录补全、Session 与生产发布整合仍待闭合。

2026-11-15：C1-A [事件分发检查](event-dispatch-checks.json)完成固定原版/Python 的独立观察对照、12 项原版生命周期测试，以及两组 95/116 项 Python 定向回归。新增 Symbol 身份事件键、每个 middleware 独立的单次 next、parallel 调度标识、空监听键清除与 internal/update 注册 effect；配置解析/更新参数和 Fiber 依赖生命周期属于后续同合同整合工作，未据此宣称 C1 完成。

2026-11-15：C1-B [配置生命周期](config-lifecycle-checks.json)完成固定 Source/Python 配对及 58/98 项定向检查；原始输入与生效配置分离，提交先于更新，候选解析不发布，过期完成不覆盖新值。C1-C [服务保留](provision-retention-checks.json)完成 5 组 Source/Python 旅程、12 项原版与 168 项 Python 检查；每次 provision 独立身份，隔离服务不混入依赖快照，提供者等待消费者清理后释放。

2026-11-15：C1-D [定义与使用上下文](trace-context-checks.json)完成原版/Python 配对和 103/15 项定向检查，覆盖方法、getter、调用入口、继承、权限与日志归属。三批已用完的合成夹具均在提交前清理，失败诊断保留。独立 Source、node_modules 与工具链继续由 rc022-C1–C9 持有，用于其余固定上游合同和最终验收；完成 C9 或目标被否决后清理。C1 整体及其余合同仍未签收。
