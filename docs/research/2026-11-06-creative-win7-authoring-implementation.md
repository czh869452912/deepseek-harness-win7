# 创造模式 Win7 开发指引实施记录

> 历史实施记录：以下结果对应上一方案。用户后续要求收敛为原版的 Python/Win7 对应指引，当前默认入口与代码变化见[对齐记录](2026-11-06-creative-win7-authoring-alignment.md)。原独立技能资源已迁入同名技能目录；本记录中的旧模型结果不自动认证当前正文。

日期：2026-11-06。依据[获准计划](2026-11-06-creative-win7-authoring-plan.md)。源码基线和固定原版目标沿用该计划；本记录对应工作区实现，不是 commit、Portable 或 Win7 真机验收回执。

## 交付与接入

- 当时的开发指南说明 CLI Creative 显式 patch 和 Web 用户 preset。两个入口共享独立命名的 Win7 技能；其资源现迁入 [同名迁移技能](../../packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/SKILL.md)。当时由额外 provider 接入，保留原版技能及同名用户技能优先级。
- 技能覆盖 Inspect、语言边界、依赖与作用域、effect/事件/timer/异步清理、工具 DSL、Client Slots/主题/RPC、版本/审批/诊断，以及本机 export/build/pack/add/upgrade/rollback/remove。Host 是 Python 3.8.10，动态 Client 是 plain JS。
- 修正旧本地技能里的动态 API 示例和 export 的过期描述。补齐 python-echo 的显式发行清单；技能内另有完整原生项目脚手架，不依赖 Portable 中不存在的仓库 examples 目录。
- 动态 echo、带状态 RPC、事件/timer/异步清理，以及 Run 卡/持久 overlay 示例随技能交付。构建不自动将 Run 卡转换为全局面板。
- 根据真实任务暴露的入口问题，增加组合 stateful 样例及不依赖仓库 tests 的原生生命周期检查脚本；正文直接链接持久 overlay，明确 effect 返回清理函数的写法及部署解释器的精确定位方式。
- 新增两个原生扩展的 package inventory 身份文件，供真实 DeepSeek 请求解析活动 Loader 条目；实现仍由 Python registry 解析，无 TS 入口或目标机 npm 安装流程。

默认组合没有自动挂载技能扩展或 export，也未修改原版浏览器源码、Inspect 静态合同及默认七工具定义。

## 验证发现与必要修复

1. 正式请求暴露 `REQUEST_EXTENSION`：活动原生扩展缺少可解析的 package 身份。增加 metadata 后，真实序列化请求、技能目录及加载内容通过验证。
2. 示例执行暴露动态 output value DSL 的 required 用法错误；已改为属性级 required: true，并直接执行实际资源文件验证输入、输出与撤销。
3. 原生示例发行描述需要 formatVersion: 1；补齐后完成 pack、安装、两次冷启动、升级、版本回退和移除。
4. 不同 cordis 派生 preset 共存时，原生 Cordis manager 重复注册同一全局 Inspect provider。为 manager 内建 provider 增加可释放的共享租约，查询选择仍活动的 owner；公共 register 继续严格拒绝重复。验证先/后 owner 退出、最后撤销和不同 preset 的工具可见性。此项是明确记录的本机多预设装配修复。
5. 浏览器交付测试在重启前主动断开原页面，避免测试进程反复启动时的 Python 3.8 已关闭套接字回调异常。实际 Host 卸载立即撤销 RPC；原版页面重载后按新图移除 Client。没有为测试修改浏览器实现或套接字生产逻辑。

## 定向验证范围与结果

输出根：`.goose/out/creative-win7-implementation-20261106-194720/`。失败轮次的日志/XML/浏览器 JSON 均保留；成功轮次不覆盖失败观察。

分批共 **325 个不同 pytest 用例通过**；重复执行的用例不重复计数。verification.json 汇总命令、退出状态、日志/XML 和耗时。

| 范围 | 结果与证据 |
| --- | --- |
| CLI/Web 默认和扩展的首次实际请求、skill 加载、provider 作用域/遮蔽/清理、示例执行、事件/timer/异步清理、Inspect owner 转移、原生包旅程 | 9 passed；authoring-final.log/xml。请求使用本地可控 HTTP 服务，覆盖真实调用链，不能当成真实模型评估。 |
| 技能内独立原生脚手架、仓库示例实际 Web 启动 | 2 passed；scaffold.log/xml。 |
| guard、默认工具合同、Inspect、export、Client build、技能发现、会话目录与 canonical profile 的直接消费者 | 309 passed，2 个浏览器参数初始跳过；consumers.log/xml。 |
| 上述 host/session 两个浏览器参数，显式提供 Edge 后执行 | 2 passed；browser-consumers.log/xml，155.66 秒。 |
| 新技能 overlay 的实际 build/pack/install、原版页面、中文 Python RPC、页面重载、Host 冷启动、升级、回退、旧 RPC 撤销及页面重载移除 | passed；guide-browser-qualified.json/png。另已接入 pytest，1 passed；browser-guide-pytest.log/xml，47.69 秒。 |
| 反馈后组合 stateful 样例与独立检查脚本，从中文/空格工作目录执行，覆盖默认与改名工具；CLI/Web 实际技能加载复验 | authoring-feedback.log/xml: 3 passed、3 deselected；另 verifier-default.log/xml: 1 passed。其中两个 CLI/Web 用例与先前范围重合，不能重复累计为新用例。 |
| 技能内原生脚手架的中文/空格项目路径 | scaffold-unicode.log/xml: 1 passed，是既有脚手架用例的定向重验。 |
| 共享 Inspect provider 的实际工具查询，覆盖原有 Agent、其他 preset 与新建 Agent | inspect-scopes.log/xml: 1 passed，是既有作用域用例补强后的定向重验。 |
| 默认 Cordis 新鲜双侧观察 | cordis-tools-fresh.json: passed，沿用既有明确 Python 语言适配；未放宽 fixture。 |
| 迁移只读预检 | migration check 与 ready 均退出 0；migration-exits.txt 及相应日志。没有提升迁移状态。 |
| 技能结构、Python 3.8 语法、相对链接、diff 空白 | quick_validate 通过；docs-and-syntax.json 与最终检查记录。 |

以上是分批定向结果，不是一次完整回归或发行验收。Python 3.8.10、现代 Windows/Edge 下执行；未运行 verify_release.py、未重建 Portable、未取得本轮新样例的 Win7 真机观察。

## 真实模型任务评估

使用现有配置的 DeepSeek 官方服务，固定 deepseek-flash、reasoningEffort=high；每任务 360 秒上限。独立 Agent、独立任务工作区，共享同一安装和已复制开发 preset；不给额外正确源码，不把确定性 HTTP fixture 当模型表现。B4 本轮观察与质量限制如下，不是全任务能力合格证。

原始用户需求、实际序列化模型请求、会话事件、Package 清单、生成源码和结果留在输出根的 model-eval/；反馈后样本在 model-eval-followup/。各自的 input-manifest.json 绑定使用的技能与关键运行时文件摘要。不保存 HTTP Authorization，也没有将用户 API key 写入这些观察。只读任务另外将生成源码交给独立运行器复验实际返回值、非法参数拒绝和 stop 后撤销。

| 初版指引的基线 | 实际结果 |
| --- | --- |
| 只读工具，3 次 | 54.99、47.61、63.34 秒完成；均加载正确技能并 Inspect，实际调用、非法参数拒绝和 stop 撤销通过。三个生成源码的独立重放也通过。 |
| 状态/事件/timer，3 次 | 均达到 360 秒上限，未完成完整交付流程。第一轮实际观察到 1/2、重启后 1，并有独立源码重放；第二轮计数也能重放，但将内建 tools/result 称为自定义事件，违反需求；第三轮截止时尚无 define。阅读大量运行时源码和额外诊断消耗了主要步骤。不能把超时等同于所有生成代码均不可运行。 |
| Host+Client 面板，3 次 | 均未在上限内完成完整验收。第一轮有 ZIP，但实际安装后 Python RPC 失败：生成的 ctx.effect(lambda: state.clear()) 在激活时清空状态。第二轮等待 Client Inspect 时页面断线重连，属于评估环境干扰，不能计为模型能力失败。第三轮截止时仍在查询/搜索实现，尚无交付项目。 |

首轮浏览器评估脚本还出现审批按钮点击超时、重连后未收到先前 Inspect 请求等问题，诊断留在 browser-observations.initial.json、browser-observations.second.json 及相关日志。后续页面连续连接和异步等待逻辑已调整，但动态 Client 审批按钮自动化仍未取得有效通过结果；不能将这部分观察用于声称模型或产品的完整审批旅程通过，也不能据此计算可靠的模型失败率。

反馈后没有向模型粘贴修复答案；修改的是正式交付的技能：直接给出可执行组合样例与外部检查器、链接持久面板、解释 cleanup 的具体易错写法、定位确切启动器并避免递归搜索输出目录。随后以相同用户需求、模型和推理参数，各复测一次：

- 有状态任务在 **210.73 秒**完成，源码与当前会话定义一致；真实工具值为 1/2，stop 后撤销，重新激活回到 1；独立脚本验证自定义事件、timer、旧状态稳定和 snapshot RPC。没有人工补实现；发生一次过长 idPrefix 的自动纠错。
- 面板任务生成了已 build/pack 的项目与 ZIP；当前会话的动态 Client 审批未由测试脚本完成，因此该会话在 360 秒上限下仍记为未完整通过。另将模型交付的**原始 ZIP**安装进独立私有 home，实际浏览器点击、页面重载和 Host 冷启动后调用均通过，三次响应精确匹配“你好 Win7”；见 model-eval-followup/panel-1/installed-browser-qualified.json/png。独立安装验证没有修补源码，也没有在目标 Host 中提供 Node/pnpm/pip。

这些结果支持本机开发指引及具体样例可用，并暴露了模型效率、指令采纳和评估脚本的限制。反馈后的两个样本不能替代新指引的完整三类各三次评估；普遍开发任务质量、动态 Client 审批旅程、完整发行门禁及 Win7 目标机观察仍需分别取得证据。没有提升迁移状态或声明未经验证的发行物合格。
