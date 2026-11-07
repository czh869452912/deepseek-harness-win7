# 创造模式开发指引：收敛到原版迁移范围

日期：2026-11-06。依据用户明确的新约束：以固定原版为目标，只做 Python 3.8 / Win7 必要适配。本文取代[上一方案](2026-11-06-creative-win7-authoring-plan.md)中“单独 Win7 开发扩展”的接入决定；[上一轮观察](2026-11-06-creative-win7-authoring-implementation.md)作为历史证据保留。

## 当前实现

- 直接适配随产品交付的同名 [cordis-plugin-development](../../packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/SKILL.md)。以 reference 固定原版正文为底稿，保留章节、能力导航、工具用法、Client UI/主题示例、审批、版本、修复及临时插件定位；替换 Host 源码与必要的 Win7 环境说明。reference 与原版前端不改。
- 恢复原版系统提示里的技能加载要求及后续技能引用；删掉先前“自行翻译原版 Host 示例”的提示替换。其余语言/执行环境适配保留；配对观察明确记录新的语言投影，不放宽七工具行为比较。
- Web cordis 沿用 preset 自带 skills 路径；CLI Creative 通过已有 filesystem provider 的 bundledSkillDir 加载同一资源。Creative 组合配置时，仅将自身 bundle 声明的自带资源路径转为绝对路径；通用 provider 的用户相对配置和相对环境变量仍按进程工作目录解析，用户 patch 保持原值。未增加技能 provider 类型或启动参数。
- 删除本轮引入的 win7-plugin-authoring 插件、registry 入口、package identity、独立技能名字和启用 fragment/patch。默认七工具不增加 export。用户同名技能仍按现有来源 rank/scope 合并；用户旧副本不自动改写。
- 将原生发行内容移到[独立文档](../plugin-distribution-win7.md)。既有 cordis_export / 安装 CLI 保留为明确启用的本机能力，不在默认开发技能中要求导出、构建、安装或跨重启交付。通用动态开发不强制专用计数器或外部检查器。
- 保留上一轮实际发现的多预设 Inspect 注册冲突修复；它使既有用户 preset 可共存，不增加动态插件权限或改写公共 register 的重复拒绝规则。

原版项目实现使用 TS，但模型编写的动态 code.host/code.client 本来就是 plain JavaScript。迁移对应关系是 Python Host / 原版 JS Client，不能将动态 Client 改成 Python，也不能声称动态入口编译任意 TS 工程。

## 明确保留的差异与限制

Python Host 在受信进程中允许 imports；Service/Event Inspect 保留原版协议类型；Client 语法错误目前到浏览器激活时报告。这些是已有运行时差异，本轮技能收敛没有修改执行器或宣称差异消失。多预设 Inspect 共享租约属于记录在案的本机修复。

先前模型评估绑定旧版技能，不作为当前正文的模型任务完成率证据。当前开发机检查不代替 Win7 真机、完整回归或 Portable 发行验收。

## 本轮验证

定向选择实际 CLI/Web 序列化请求和技能加载、默认七工具、用户技能遮蔽/多预设、可执行 Python 示例、技能 registry/filesystem 直接消费者、Creative profile 组合及新鲜 Source/Python 工具配对。资源位置变更同时检查现有可选交付消费者，避免留下断链。

输出目录：`.goose/out/creative-win7-alignment-20261106-234659/`。首轮保留 entry-contracts.log/xml：CLI 的 URL 路径写法不适合 profile patch，以及请求工具排序断言错误；后续检查单独输出，不覆盖该轮失败。

| 检查 | 结果 |
| --- | --- |
| 首轮默认请求、作用域、实际示例及工具合同 | 97 passed、4 failed；失败均为上述入口/断言问题，保留诊断。 |
| 修正后的 CLI/Web 默认与单独 export 两种组合，实际首次请求及 skill 工具加载 | 4 passed，20.30 秒；entry-fixed.log/xml。 |
| 当前完整 test_win7_authoring、canonical skill journey、session skill scope、skill registry lifecycle、profile boot/bundles | 28 passed，106.00 秒；consumers.log/xml。显式提供 Edge，浏览器用例实际执行，没有跳过；包括迁移后的示例、安装浏览器链及中文/空格路径检查。 |
| 新鲜 Source/Python Cordis 工具观察 | 92 matched、0 different；cordis-tools.json 及两侧原始输出。七工具行为逐项比较不变；提示只保留 6 项必要语言/执行环境替换，删除了 4 项技能路由偏离。 |
| 技能正文与源码 | 保留原版全部二/三级标题；工具用法、provider 导航、Client UI、主题、版本/审批和 @pluginId 六节逐字一致；docs-and-source.json。Python 3.8.10 下 13 个相关 Python 文件语法通过，14 份 Markdown 的相对链接可解析。 |
| 技能格式与空白 | quick_validate 与 git diff --check 通过。 |

各批次重叠用例不重复作为新增通过数；verification.json 保留命令、日志、XML、状态和汇总。未跑完整回归、重建 Portable、进行新一轮真实模型开发任务或 Win7 目标机测试。

2026-11-07 复审修复了此前通用 provider 的相对路径回归，并补齐普通 Python 异常的真实 traceback。上述旧回执仅对应当时输入，当前变更与新鲜定向验证见[两项复审问题修复记录](2026-11-07-creative-win7-review-fixes.md)，不能据此认定除语言外完全等价。
