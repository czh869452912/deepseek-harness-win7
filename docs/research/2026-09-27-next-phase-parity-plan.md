# 第一批闭包后的整体评估与下一阶段对照计划

日期：2026-09-27。评估基点：`d0bf0922`；已验收产品候选：`25f59152523eccb1eb79dc8ae1090481cdee8214`；目标上游仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。

本文是下一阶段计划，不将建议自动写成 ready/integrated 任务，不改变当前 target/accepted/observed SHA。Win7 真机验证继续按用户要求暂缓。

## 整体判断

项目已经从“实现存在、测试标题声称对齐”推进到“基础架构有可复现双侧证据，能够完成一条真实装配/持久化恢复路径”。下一阶段应从 Cordis 基础语义推进到 Agent/Session 产品语义和真实外部协议。

当前六个任务 integrated 表示第一批定义的验收闭包完成，不是六个任务覆盖了整个 Harness。全项目 accepted_upstream 仍为空是正确状态。不能用 3064 / 14659 计算完成率：前者是本地 pytest 执行数，后者是上游测试源码中的字面声明数，参数展开、测试支持代码、语言适配和覆盖范围均不同。

| 层面 | 现有证据 | 本轮评价与边界 |
|---|---|---|
| Cordis/Loader/Include/HMR 基础 | 67 个源码推导配对场景，66 matched；C58 精确语言差异单独验收 | 可作为下游依赖，但不是任意插件、任意 await 交错的全称证明 |
| 关键消费者 | 原样上游测试 80 项；69 个必要消费者实例有断言映射 | 选定的 Preset、生命周期、Boot/Profile HMR 已有强证据；不能推广到所有业务插件 |
| 最小纵向流程 | 实际 run_profile、Loader、工具、JSONL、关闭、新 Context 恢复；仅 LLM 替身 | 成功路径已建立；未覆盖全部创建/恢复事务、取消、并发和损坏恢复 |
| 本地回归 | 已验收候选 3064 passed、2 skipped、2 warnings | 防止回归的基线；新增更强上游断言仍可能发现既存缺陷 |
| 发行物 | 自带 Python 3.8，五个 profile 配置检查、隔离启动，341 个 Python 文件一致 | 本机包有效；干净 checkout/CI 重建和真实用户流程是另一层验证 |
| 盘点/工作流 | 272 个 manifest 分类，1227 个测试源文件，14659 个字面声明，1346 个动态契约位置 | 发现清单已完成；动态表达式尚非已解析服务图，任务领取/租约/调度器没有实现 |
| Provider 与 Web | 已有大量本地实现和单元测试 | 尚无本批次完整协议级双侧闭包或官方前端浏览器端到端认证 |

来源：[看板](../../migration/status.md)、[最终评审](../../migration/reviews/CORDIS-FINAL-CLOSURE-20260927.md)、[最小流程测试](../../tests/test_profile_spine_recovery.py)、[基线字段](../../migration/baseline.json)。

## 源码核对发现的优先问题

以下区分已观察到的源码差异和仍需探针确认的行为，不把静态阅读当作完整运行时裁决。

### 1. Agent 工厂 / SessionPreparation 是下一处架构门禁

固定上游 [agent-loop/src/index.ts](../../reference/packages/core/agent-loop/src/index.ts) 的 createAgent/setupAndPublish/resumeWith 使用调用者 ownerCtx、SessionPreparation、signal、raceAbort/raceAbortCall，并跟踪尚未发布的 factory wrapper。恢复加载要能被调用者取消、owner 卸载或 factory teardown 打断；迟到的 preparation 必须释放，不能补发已经取消的 agent。

本地 [AgentRegistry.create/resume](../../dsh/core/agent.py) 的请求拆解主要转发 sessionId、options、meta、setup，没有转发上游 seed/signal。 [AgentLoopService](../../dsh/core/agent_loop.py) 当前 resume 直接 await persistence.load，再 enter/announce session，之后才 await setup；上游在 setup/commit 完成前保持未发布。仓库已有 [SessionPreparation](../../dsh/core/session/preparation.py)，但“类已迁移”不等于工厂已使用它完成所有权事务。

优先引入上游 [resume.spec.ts](../../reference/packages/core/agent-loop/tests/resume.spec.ts) 中 setup 未完成不可见、setup 拒绝零发布、owner 卸载、永不完成 persistence preparation 和迟到结果清理断言。已有普通 resume 回归与最小成功路径不能替代这些断言。此闭包应允许共同修改 AgentRegistry、AgentLoop、Session、持久化 preparation、Preset setup 及必要 Web/子智能体调用者。

### 2. Web 对照目标需要重新以当前 reference 确认

当前 manifest 清单没有名为 dsh-apiproxy 的上游包；固定目标存在 [client/connection](../../reference/packages/client/connection/src/rpc-host.ts) 的通用 RPC channel 注册、请求校验/信任和 Connection 服务。 [web-app](../../reference/packages/bundle/web-app/src/index.ts) 使用 connection、authenticatedUrl 等接口；本地仍有集中式 [ApiProxy](../../dsh/host/apiproxy/api_proxy.py) 和域处理器。

这证明需要一次“当前目标协议归属与装配”的核对，不单凭包名差异认定每个旧端点都错。应按本目标的真实前端消费者、路由/channel、消息 schema 和鉴权建立映射，查明双 SSE、POST /api/respond 与兼容入口的对应关系。不能只按旧 Web 文档或固定插件数量继续补页面。

### 3. Provider 目录可见不等于 DeepSeek 协议已等价

本地 [llm_openai.py](../../dsh/llm/llm_openai.py) 注册的 _SimpleAdapter 主要承担 provider 信息和简单模型目录；实际传输还需沿 LLMService 追踪。固定上游 llm-deepseek 有 serialize、translate、SSE、files-api、file-store、upload-index、dynamic-config 和 adapter E2E 等明确测试面。

先用官方 mock HTTP server/固定 wire fixtures 比较真实适配器的请求与流响应。不要只向 AgentLoop 注入已经翻译好的 LLM chunk，因为那会绕过最容易出现偏差的协议转换。远程 API 可用性、真实模型结果与确定性协议一致性分开记证据。

### 4. 本机成功还未变成干净环境的自动门禁

[release.yml](../../.github/workflows/release.yml) 当前只有 tag 发布：安装 Python 依赖后直接 build_portable；没有显式准备 reference、固定 ripgrep、Node/oracle 依赖、前端构建和完整回归。 [build_portable.py](../../scripts/build_portable.py) 默认依赖 reference/node_modules 中的固定 ripgrep 路径。本地这次通过显式 --ripgrep-source 提供了输入，因此不能推断 tag 工作流已经可以从干净 checkout 成功发布。

这是源码层面的复现风险，尚未执行远程 Actions 证伪；下一阶段应先修成可在空白工作目录重建的门禁。不要为验证而直接创建发布 tag。

## 建议依赖顺序与交付闭包

| 顺序 / 建议任务 | 范围与硬依赖 | 核心验收条件 |
|---|---|---|
| P0：MIG-REPRO-GATE-002 | 干净环境依赖准备、Python 3.8 回归、官方 runner、portable；基于现有闭包 | 无本机隐式 node_modules/缓存依赖；失败阻止发布；构建和测试绑定同一候选；明确两个 skip/两个 warning 的来源 |
| P1：MIG-AGENT-LIFECYCLE-002 | AgentRegistry + AgentLoop + SessionPreparation + 持久化 preparation + 必要 setup 消费者；依赖 Core@10 | 未发布身份、seed/signal、setup/commit、三类取消源、迟到结果释放、身份复用、并发同 ID、owner unload；双侧事件序列与零残留 |
| P2：MIG-SESSION-REPLAY-002 | Session 事件/消息、投影、JSONL 持久化；依赖 P1 的身份/发布契约 | 序号与事件顺序、chunk/message/工具结果投影、损坏尾部/中断 turn/未来版本、恢复后下一请求；运行官方 golden/replay，不仅测试 snapshot 辅助函数 |
| P3a：MIG-DEEPSEEK-WIRE-002 | LLM runtime + DeepSeek adapter + retry + token/附件必要消费者；依赖稳定消息/取消契约 | 真实 HTTP 适配器对相同 wire fixture 输出一致；请求字段、分片 SSE、半截工具参数、终止/usage、429/5xx/断流/取消及失败持久化；文件协议先核适用范围 |
| P3b：MIG-TOOLS-POLICY-002 | Tool runtime + scheduler + approval/plan/interaction + 子智能体入口；依赖 P1/P2 | schema、执行模式、并发/顺序、审批拒绝、dispatch 前取消、执行中取消、工具错误/重试、作用域隔离；提供端和消费者共同验收 |
| P3c：MIG-WEB-CONNECTION-002 | 当前 reference 的 Connection/RPC/生成接口/事件投影 + 本地适配 + 官方前端；依赖 P2 及已指定协议契约 | 真 HTTP + 浏览器，逐层核路由/envelope/鉴权、session projection、重连与重复消息、提交审批/问题；以目标源码定义支持语义，不预设旧协议等价 |
| P4：MIG-PROFILE-JOURNEYS-002 | 默认 profile 的真实装配，依赖上述必要消费者 | minimal/standard/creative/web/headless：启动、请求、工具、取消、会话恢复、退出；用重建 portable 再跑一次；Win7 验证继续单列暂缓 |
| 侧线：MIG-UPSTREAM-DELTA-002 | 只读观察与批次演练，不改变当前 reference | 记录 observed SHA、相对当前 target 的 manifest/源测试/契约变化，输出受影响消费者和重验集合；先审批次再推进 target |

P0 和 P1 可独立推进。P3a/P3b/P3c 的源码盘点和官方 fixture 提取可以提前进行，接口实现等待相应契约稳定；不要把所有工作机械串行。P1 内部若有 Provider/Consumer 环，应合成共同交付闭包，不把 SessionPreparation 和 Agent factory 拆成互相等待的任务。

第一阶段的实际起跑范围建议只设 P0、P1 和 Web 协议盘点。其余保留 draft，待已有接口和失败探针明确后再放 ready。这能尽早解决复现与生命周期风险，又不让多个下游同时修改未稳定接口。

## 下一项具体对照怎么做

对 P1，先跑固定上游 `resume.spec.ts`、`scope-lifecycle.spec.ts`、`agent.spec.ts`、`config-session-id.spec.ts`，保留参数展开。按“创建/恢复中的身份状态”而非包目录分组：

1. setup 暂停时：registry 不可见，session/created、agent/created、agent/session-start 未发布。
2. setup 抛错或 commit 抛错：零发布、scope 释放、preparation release 恰好一次、原 ID 可重新申请。
3. 外部 signal、owner 卸载、factory 卸载分别发生在 load/setup 阶段：调用及时结束，不等永久挂起的 backend。
4. 取消后 load/setup 迟到：释放资源，禁止重新 publish，禁止污染新一代同 ID agent。
5. 成功路径：精确 Session 实例、owner、seed 和发布顺序匹配；普通 root 创建与子 agent 调用者都要覆盖。
6. 必要消费者复验：Preset scope/setup、子智能体、Web 会话创建/恢复，以及已有 profile→JSONL spine。

先保留 Python 的失败观察，再修改共同闭包；不要先更新预期值或用兼容包装把不支持的 signal/seed 静默吞掉。取消适配应明确“业务取消信号”和“取消 Python observer Task”的区别。

## 单执行者和多智能体安排

当前关键工厂事务建议一个实现 owner。协调者负责 revision、依赖、共同变更和集成；独立审阅可以核对上游断言/反例，不能只重复跑同一组本地测试。

P1/P2 稳定后，Provider 与 Tools 可分开，Web 只有协议和 Session 投影边界明确后再并行。任务拥有独立工作树与验收责任，expected_paths 不限制必要跨端修复。有共享接口冲突时，协调者将提供端与必要消费者交给同一个闭包 owner，暂停冲突写入，其余分析继续。

现有只读记录门禁足够支撑这一阶段的单协调者。不要把分布式自动领取/租约/调度器做成产品语义迁移的先决条件。实际扩大并行到多个持续写入者时，再以独立任务实现事务领取、checkpoint 恢复和组合候选验收。

## 持续跟踪与进展指标

保持三个版本含义分离：accepted 是已验收范围对应的上游，target 是当前工作批次，observed 是最近确认的新上游。当前 accepted 不应被第一批完成自动填为全项目接受。只读 delta 观察不更新 target，也不使进行中的闭包每次追随 HEAD。

每次上游批次先比较 manifest/exports/config 与官方测试，再沿动态服务、事件、RPC、持久化格式找消费者。既有 1346 处声明只提供搜索入口；逐个已选择的契约补运行时解析与验证影响边，未知边保留 unknown。将这次生命周期、Web 协议变化作为更新演练的具体样例。

后续看板分别报告：发现范围、已核对官方断言/参数实例、真实双侧场景、纵向流程、平台适配、证据有效性。测试增加量、插件数量、包数量都不直接表示对齐比例。

阶段退出条件：P1/P2 的关键异常/取消路径完成官方断言和双侧复现；DeepSeek wire 与 Tools 的核心流程可在真实装配中组合；官方前端连接本地后端完成真实用户流程；空白 checkout/portable 可重复构建验证。范围外实验插件和未覆盖接口明确留在后续清单，不称为“已全面一比一”。

## 本轮复核

评估期间重新执行 `.venv\\Scripts\\python.exe -m pytest tests`：3064 passed、2 skipped、2 warnings，退出码 0（169.31 秒）；与已验收候选一致。源链接已校验。上述优先问题来自源码对照，尚未新增双侧失败探针；不能将建议任务误读为已经实施的修复。本轮新增研究文档，未推进任务状态或上游版本。
