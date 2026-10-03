# 迁移记录校验读取修复

本次 A2 接入校验中，多个历史 acceptance 记录重复引用同一大组输入，Windows Python 3.8.10 反复执行 Path.resolve/read_bytes，使 check/status 各耗时数分钟。只读 faulthandler 诊断定位于 `scripts/migration.py: file_path` 的重复 resolve，原始诊断保留于 `.goose/out/acp-next/migration-check-diagnostic.log`。

`validate` 现在只在本次调用内观察每个具名文件一次，各记录仍分别对照其精确预期哈希；没有跨调用缓存，不修改 acceptance 内容、不跳过旧记录、也不把 stale evidence 改为 current。读取期间应保持输入稳定，正式发行门禁另外核对完整输入快照和 candidate 在全过程未变。

新增反例证明共享输入/产物只读一次、两个不同预期哈希仍独立判定、下一次调用能发现输入与产物修改。迁移工作流测试 28 passed；修改后的 check/status 均通过。无缓存依赖安装、远程 Actions 与 Win7 并未由此认证。
