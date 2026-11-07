# 创造模式复审：相对路径合同与 Python 源码诊断

日期：2026-11-07。固定原版：`a4c74a91e06b00fe0b0937bde982170c526cc842`。本轮只修复用户复审指出的两个 P2，不扩大创造模式功能；承接[指引收敛记录](2026-11-06-creative-win7-authoring-alignment.md)。reference 保持干净。

## 修复内容

1. 通用 [filesystem provider](../../dsh/skill/canonical_filesystem.py) 恢复 `os.path.abspath(bundled)`：相对 `bundledSkillDir` 和相对 `DSH_BUNDLED_SKILL_DIR` 均按进程工作目录解析，绝对路径保留原义。仅在 [Creative bundle](../../packages/bundle/creative/cordis.patch.yml) 的[配置组合](../../dsh/boot/profile.py)中，将该 bundle 自带技能路径转为绝对路径；用户 profile patch 不做路径改写。测试覆盖从其他目录启动、相对配置、绝对配置、相对环境变量、用户覆盖和 CLI/Web 实际首次请求加载技能。
2. [Host runner](../../dsh/extensions/host_runner.py) 对普通 Python 异常使用 `traceback.format_exception`，保留真实异常链、调用帧和动态 `<cordis-host>` 源码行号；已有显式字符串 `.stack` 仍沿用原合同。[启动及 RPC 测试](../../tests/test_cordis_python_diagnostics.py)使用真实同步/异步除零异常，不人工赋予 `.stack`，经 canonical Web Context 和 RemoteDispatcher 验证返回值、运行诊断与模型 steering。

旧 runner 配对对照曾删除启动异常的原版 stack，导致迁移版缺栈也能通过。本轮改为显式 Python 语言投影：采用实际 Python 3.8.10 运行捕获的[完整 traceback 夹具](../../tests/fixtures/cordis-runner-python-apply-stack.txt)，仅归一化工作区和标准库目录。保留全部帧、行号、异常类型、消息和各重复诊断字段，输入摘要绑定夹具；缺栈、错行号、错类型或增加未知帧均判为不同。原有 NUL 键碰撞场景的显式 `.stack` 仍只用于该场景，普通异常已有独立覆盖。

## 定向验证

使用仓库 `.venv` 的 Python 3.8.10。选择技能 provider/工具直接消费者、Creative profile 配置组合、CLI/Web 首次请求、Host 生命周期/guard/RPC/steering 和 Cordis 七工具配对，覆盖变更提供端及消费链路；不因本次局部修复执行整个发行门禁。

输出目录：`.goose/out/creative-win7-review-fixes-20261107-001523/`，命令、输入摘要、XML、原始观察及检查结果见该目录的 `verification.json`。

| 检查 | 结果 |
| --- | --- |
| 定向 pytest：canonical skill journey、profile boot/bundles、Python diagnostics、runner state、guard、Cordis tools，以及 CLI/Web 实际首次请求技能加载四种组合 | **183 passed**，102.10 秒；`fixed.log/xml`。 |
| 新鲜 Source/Python runner 配对 | **15 旅程、149 步通过**：13 matched；1 项已登记 NUL 碰撞差异；1 项明确 Python traceback 投影。`runner.json` 及双侧原始观察。 |
| 新鲜 Source/Python 七工具配对 | **92 matched、0 different**；`tools.json` 及双侧原始观察，保留原有明确语言适配。 |
| Python 3.8 语法、文档相对链接与差异空白检查 | 通过；`final-checks.json`、`diff-check.log`。 |

首轮 `targeted.log/xml` 保留 15 passed、5 failed（49.04 秒）：三个新测试误读不存在的工具结果字段，两个新测试 helper 参数与 RPC 业务参数同名。修正测试后执行上述定向集合，失败记录未覆盖。`runner-raw.json` 与 `runner-normalized.json` 保留真实 traceback 捕获过程。

## 仍未完成的等价验收

Client define 阶段语法预检仍未对齐，错误仍延后到浏览器激活。既有 Python Host 执行环境和多预设 Inspect 共享租约差异继续单列。本轮没有重新执行浏览器、完整 Python 回归、Portable 发行门禁、真实模型开发任务或 Win7 真机测试；定向通过不代表“除语言外完全等价”，不提升整体迁移验收状态。

后续复审发现，合法单参数同步插件的真实 traceback 仍夹带参数绑定试探的 TypeError。本记录及上述回执保留原输入身份；现已修复调用位置，重新捕获无该噪声的栈夹具，并验证真实业务异常链继续保留，见[异常上下文修复记录](2026-11-07-creative-win7-exception-context-fix.md)。上述旧回执不认证更新后的 guard、诊断测试或栈夹具。
