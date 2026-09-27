# 下一阶段首批验收

产品候选：`54ee782560e56ea5ec4e7942384bd4e378ceb9c6`。目标上游仍是 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，全项目 accepted/observed 不变。

## 已完成与提交

- `f601fda2`：固定 Python / Node / 前端输入，新增可复用发行门禁，tag 发布只消费验证过的同一压缩包。
- `9b1a7f4b`：干净检出发现 CRLF/LF 差异后，前端摘要改为 Git 原始字节。
- `4775cb09`：干净回归复现 Windows delete-pending 锁竞争，增加有限重试，真实权限拒绝仍报错。
- `d87d6617`：IPv6 mock 请求不再经过机器代理；保留真实回环连接测试。
- `5c095153`：共同修复 Agent Registry / Factory / SessionPreparation / 必要旧 Web 消费者，闭合公开 create/resume 的发布与取消事务。
- `54ee7825`：记录当前 Connection / Typert Gateway / Remote 传输归属和后续依赖。

## 候选验证

独立工作树位于 `C:\Users\Administrator\.codex\worktrees\release-repro\deepseek-harness-win7`。开始时没有 `.venv` 或 npm 安装；初始化固定 reference 后安装锁定依赖。复现中逐项修复上述输入/竞争/代理问题，最终候选运行 `python scripts/verify_release.py --prepare` 全部通过。开发网络使用仅当前进程的代理设置；没有修改全局 Git/系统代理。

| 检查 | 结果 | 证明边界 |
|---|---|---|
| 完整 pytest | 3088 passed、2 skipped、2 warnings，187.64 秒 | 当前 Windows Python 3.8.10；两项 skip 为 POSIX 语义，两项既有 Proactor 清理警告仍保留 |
| 关键 Cordis 官方消费者 | 5 套件、80 passed | 固定选择的消费者 |
| Agent 官方生命周期 | 4 套件、100 passed | 上游基准执行，不代表 100 项 Python 对齐 |
| Agent 双侧观察 | 9 matched | 发布前可见性、setup/commit、三类取消源、迟到释放、销毁；另有 16 项本地边界探针 |
| Cordis 双侧原始观察 | 66 matched、C58 different | 原始结果保留；精确语言差异门禁 passed，范围仍限 C1–C67 |
| Web 协议官方基准 | 4 套件、71 passed | 协议盘点；尚非 Python Gateway 或浏览器端到端验收 |
| Portable | 包内 Python 五 profile 配置检查、隔离启动通过；342 个 Python 源文件字节一致 | 当前 Windows；前端为固定的已入库预编译输入 |
| 记录 / 盘点 | manifest 与清单重生成一致；67 场景、69 关键消费者参数实例映射有效 | 源码发现和依赖记录，不是覆盖百分比 |

包为 46,760,284 字节，SHA256 `52c0134e83017e0c0e9d58130b84a8f99da373374ad36bffc6e82e3ef4cebf64`；provenance 的候选 SHA 正确且 `worktree_dirty=false`。验证输出归档为 `migration/evidence/artifacts/NEXT-WAVE-20260927-*`。新增验收记录关联同一候选；旧证据保留，已有 Core/Spine/Portable 等契约已按当前候选复验。

## 下一交付边界

首批批准的 P0、公开 P1 工厂闭包和 Web 协议盘点完成。配置驱动 Agent 启动/重载、draining 身份仍由 Profile 批次对照；不能从公开工厂通过推导出整个 agent-loop 已全面等价。下一主线是 Session replay / recovery / projection，并用配置启动重载作为必要消费者。之后才推进 DeepSeek wire、Tools policy、Gateway/Remote 和目标源码前端重建。

远程 Actions 未运行、未创建发布 tag；Win7 真机继续按用户要求暂缓。没有将旧双 SSE / respond 兼容面认证为当前上游传输。两个原有 Proactor 警告未在本批次消除。
