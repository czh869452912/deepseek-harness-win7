# 创造模式复审：移除参数适配异常上下文

日期：2026-11-07。固定原版仍为 `a4c74a91e06b00fe0b0937bde982170c526cc842`，reference 未改动。本轮修复合法单参数 Python 插件的诊断污染，承接[上一轮两项修复](2026-11-07-creative-win7-review-fixes.md)。

## 根因与修改

[guarded_plugin](../../dsh/extensions/cordis_guard.py) 原先在 `signature.bind(ctx, config)` 失败的 `except TypeError` 中调用单参数插件。插件同步抛出业务异常时，Python 将正在处理的参数试探错误附加为 `__context__`，产生误导性的 `too many positional arguments`。

现在先选择调用参数，再退出参数探测的异常处理块调用插件。无法读取签名时也在异常处理块外调用原函数。不修改 traceback 格式化策略，不关闭异常链显示；保留真实业务异常和动态源码位置。

[诊断回归](../../tests/test_cordis_python_diagnostics.py)覆盖同步/异步、启动/RPC、无业务异常链/隐式业务异常链/显式 `raise … from …` 共 12 种组合。验证实际 Remote 返回、运行诊断和模型 steering：无参数试探噪声，有正确 `<cordis-host>` 行号；真实业务原因及对应异常链连接语仍保留。

[完整 Python 栈夹具](../../tests/fixtures/cordis-runner-python-apply-stack.txt)重新从实际 runner 观察捕获，不手写栈或删除错误字符串。配对仍比较完整栈，仅归一化环境路径；捕获原文保存在本轮输出的 `runner-captured.json`。旧夹具中的框架噪声不再作为必要语言差异保留。

## 验证范围与证据

输出目录：`.goose/out/creative-win7-exception-context-20261107-003100/`。使用 Python 3.8.10，选择 guard、runner 生命周期、实际 Remote/RPC/steering 诊断及七工具直接消费者，并执行新鲜 Source/Python guard、runner、工具三组配对。命令、输入摘要、日志、XML 和退出状态记录在 `verification.json`。

先对新增断言运行单参数同步启动场景，确实因 `too many positional arguments` 失败，保留 `reproduced.log/xml`。初次 `-k` 选择被父级 asyncio 标记全部排除，保留 `before.log/xml`，不计为缺陷复现或通过结果。修复后的定向与配对结果见下表。

| 检查 | 结果 |
| --- | --- |
| 定向 pytest：Python diagnostics、guard、runner state、Cordis tools | **175 passed**，146.34 秒，0 skipped；`targeted.log/xml`。 |
| 新鲜 Source/Python guard 配对 | 119 场景通过：117 matched，2 项既有 `CORDIS-GUARD-001` 差异；0 different。 |
| 新鲜 Source/Python runner 配对 | 15 旅程、149 步通过：13 matched，1 项既有 NUL 碰撞差异，1 项明确 Python traceback 投影。 |
| 新鲜 Source/Python 七工具配对 | 92 matched、0 different。 |
| Python 3.8 语法、文档相对链接、输入摘要和差异空白检查 | 通过；`final-checks.json`。 |

附加的 `scripts/migration.py check` 与 `ready` 会读取历史归档摘要，运行期间主动停止，不计为通过。保留各自日志及 `stopped-ledger-checks.json`；本次定向修复不依赖它们完成，不修改台账或历史回执。

本轮没有重新执行浏览器、完整回归、Portable 发行门禁或 Win7 真机验证。Client define 阶段语法预检仍未对齐；不宣称整体等价，不变更迁移验收状态。
