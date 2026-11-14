# 0.2.2-rc.3 实施准备区

日期：2026-11-14。用户已认可[目标复核](../../../docs/research/2026-11-14-upstream-target-selection-update.md)，授权评估实施路径并准备实施。

- 固定目标：`dsh-v0.2.2-rc.3 / 38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。
- 当前上游生产 pin：`a4c74a91e06b00fe0b0937bde982170c526cc842`。代码基于当前工作区，包含已完成的创造模式适配。
- 本目录名称 `rc022` 明确区别于历史 `rc3`（0.1.5-rc.3）；不是新的活动基线或发行资格。
- 详细执行顺序、合同和准入标准见[实施路径](../../../docs/research/2026-11-14-rc022-implementation-path.md)。
- [准备检查](preparation-checks.json)记录实际执行的发现、回归、源码与工具准备结果；完整生成清单和日志留在自有忽略输出目录。

下一工作单元是 S0-B：使用独立 Source 与固定现代工具链完成依赖安装和原样前端构建，随后执行 Chromium108/Electron22 探针。S0-C 的 v3→v4 与插件协议探针尚未执行。所有迁移合同保持未签收。

生产 reference、注册表、运行时/前端输入清单和旧迁移任务本轮不切换。待合同实现与消费者定向检查闭合后，统一执行显式 promotion；`accepted_upstream` 不随准备记录自动变化。
