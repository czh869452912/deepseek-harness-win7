# 只读上游差分观察推进

`scripts/upstream_delta.py --base <existing-ref> --target <existing-ref> [--output <new-file>]` 只读取已存在的 Git commit，不 fetch、checkout、修改 pin/任务或安装定时巡检。开发 Git 使用 no-optional-locks，关闭 fsmonitor/untrackedCache 写入；NUL name-status 保留空白、Unicode 与 rename/copy 双侧路径。272 个 pinned manifest 的完整集合、逐字节 SHA256、name、owner 和实际声明的 dependencies/peer/optional/dev edges 在读取前验证，结束时再次检查 Source HEAD/status 与 inventory bytes。

建议性影响按最邻近 pinned package 归属与反向声明依赖传播，独立保留 non-package surfaces；根 package 的归属不能伪装成动态职责已经解析。新增/移动 package、运行期表达式和未来 target 的迁移仍需原版审查。输出只能排他新建，不修改 Source、Git 或 migration 状态，不覆盖已有结果。

19 项首次聚焦回归通过，覆盖真实临时 Git 历史的跨 package rename、delete/add、开发依赖传播、malformed NUL、dirty/wrong pin、坏 hash/name/dependency、缺失/重复 inventory、revision option injection、观察期间 drift 和受保护/重复输出。实际固定 Source 的父提交 8437bfb9 到 cd5ef814 演练识别 250 个 manifest 修改、250 直接 owner 和一个传递 owner，Source checkout 和 inventory 均不变；fresh 报告 `.goose/out/acp-a4-work/upstream-delta-parent-pin-v2.json`。该实际观察再进入第二十项回归。

契约为 CON-UPSTREAM-DELTA@1，任务 MIG-UPSTREAM-DELTA-002 从占位 draft 明确为 running；尚未经过完整门禁或签发证据。该有界工具不完成 D1 全职责、D2 无缓存/远程 Actions、延期 Win7 或整体 accepted_upstream。

第二轮包含实际 Source 的 20 项全部通过（5.85 秒）；进入完整门禁必需清单。清洁的全量候选验证和独立证据仍待进行。

新增二十条必需 selector 逐一对照实际 pytest collection；门禁回归 205 passed。完整 release gate 在相同 frozen inputs 下独立执行父提交到 pin 的只读演练，验证全部 Source identity/inventory hash，并把 fresh JSON 的 SHA256 纳入 receipts，不能仅据测试名称签收。
