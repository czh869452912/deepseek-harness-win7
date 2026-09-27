# Session JSONL 冷恢复验收

产品候选 `0ab68981d5ada7e547354c718280079f37d61f8d`，上游仍固定 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。

## 已完成

JSONL 使用核心 deterministic repair 补齐工具结果和 step/turn 边界；扫描器只提交连续有效记录的字节位置；冷 load 先截断坏尾再修复。inspect 保持只读，read_from 返回物理后缀，拒绝非法偏移、身份错配和未来 v1 格式。live open turn 不走冷修复。

- 干净托管工作树执行完整 scripts/verify_release.py：成功。复用之前固定版本的开发依赖，本次没有声称再次从空缓存安装。
- Python 3.8.10：3111 passed、2 skipped、2 warnings，186.84 秒。保留 Windows Proactor 清理警告及 mock HTTP 断开连接日志；没有声称日志零警告。
- 官方 Cordis 必要消费者 80、Agent 100、Session repair/JSONL 164 项通过。这些是上游源码基准，不等于对应数量的 Python parity。
- Agent 9 组、Session 冷恢复 7 组真实双侧观察匹配。C1–67 保留唯一 C58 原生 Python Future 调度差异，精确签名门禁通过。
- 新包 345 个 Python 源文件与候选相同；包内 Python 五个 profile dump-config 和隔离空 profile 启停通过。ZIP SHA256：`86c4e3dc504385263121b774ea11bb45644d7cd25fd3338d992b87550d5ec665`。
- 新包位于托管工作树 `C:/Users/Administrator/.codex/worktrees/release-repro/deepseek-harness-win7/dist/`；主工作树 dist 不是本次构建产物。

修复前重复加载半行尾部的损坏异常已保存。第一次全量回归的唯一失败是旧测试只预期 turn/end；依据原样 repair.spec.ts 和双侧观察改为同时断言 step/end、只读物理前缀、落盘及二次加载，不删除测试或放宽比较。

## 尚未完成及下一方向

1. 写入队列：受控写失败后 pending 由 2 条变为 0。应按 upstream write-behind/Coordinator 保留失败批次、串行化相同 ID 写入并定义 flush barrier。
2. 生命周期：持久化插件卸载没有 drain，观察到缓冲事件未生成任何日志文件。需要 effect/disposable 拥有 flush、retirement 和 HMR adoption，不只增加一个无等待的回调。
3. 共享 preparation：inspect/resume 的共享加载、observer cancellation、reservation、版本变更重试与 exact Session 身份。
4. SQLite 也有简化修复和 inspect 写盘问题；共享协调接口变更应一起修复 JSONL/SQLite，不能按文件白名单割裂提供端。
5. 上述稳定后迁移配置 sessionId/resumeSessionId、launcher identity、restore-or-create、损坏拒绝、旧 ID draining/reload，再推进 Session projection 与 Web 消费者。

MIG-SESSION-REPLAY-002 仍是未验收总任务；本次新建独立冷恢复任务并仅签发相应范围。Core/Agent/Spine/Portable 在同一候选复验，其他历史任务未强行刷新。Win7 真机继续暂缓，整体 accepted_upstream 仍为空，未运行远程 CI。
