# 单一迁移基线整合记录

日期：2026-09-27。目标：保留各分支有效成果与可追溯提交历史，归并到实际远端默认分支 `master`。本次不启用新迁移编排系统，不宣称全部上游契约已完成迁移。

## 来源与保护

- 起点：本地 `master` `dd3bc48b`，远端 `origin/master` `59f52c7f`。
- 最新 Cordis/Timer/Settings 候选：`2dda572a`。
- Schema 历史任务：`94f1c116`；重叠修复保留新实现的 sentinel 语义。
- 插件安装与注册表：`8c57bbf4`。
- Web/消息反馈：`0cfeda1d`。
- 旧 `main`：`ebc2cd45`；整合其独有工具、预设、测试和打包成果。
- 旧工作树 `ddde47acaddc` 的 49 个未提交改动已保存快照 `6c03d53dbe34be292a074da70dc352e196e2b5f4`，完整文件树与候选链内 `b25225f9` 相同。
- 原 ref/worktree 清单、快照、Git bundle 和逐轮测试日志保存在主工作区 `.goose/runs/consolidation-20260926/`；归档引用在 `refs/archive/consolidation-20260926/`。原工作树及忽略文件保留，不做目录清除。
- 来源按可达关系去重；多个 candidate 分支不能当成多个独立模块。

## 冲突取舍与修复

以最新 Cordis 实现和固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc` 的源码契约为准，不以旧 main 的另一套核心覆盖新核心。命令反馈 invariant 与消息反馈 invariant 分开导出，避免同名模块覆盖。

修复服务代理调用方绑定、工具执行参数适配、持久化 JSON 边界、Loader entry 所有权与配置持久化、预设共享挂载，以及异步注册/卸载等待。问答服务恢复注册并校验真实活跃 root agent 的身份。工具作用域使用 `create_scope` 显式标记；普通 plugin fiber 不自动构成 agent 隔离域。

旧测试的契约差异按上游核对后更新：`has` 表示声明存在而非 provider 已激活；直接 `get` 与属性访问走不同路径；返回 Task 的调用使用 await/ensure_future；`set_service` 保留兼容替换语义而 `provide` 拒绝重复注册；卸载通知发生在最终状态变化之前；不可变 session 事件拒绝写入。没有通过统一跳过或删除失败测试获得通过。

快照 corpus 补齐引用的 JSONL，并固定原始字节，避免 Windows 换行转换破坏与上游比对。打包文件复制测试使用独立二进制 fixture，不依赖开发机恰好安装过 npm 包。

## 验证状态

在独立整合工作树使用 Python 3.8.10 执行完整回归：

```powershell
.venv\Scripts\python.exe -m pytest tests -q --tb=short -o faulthandler_timeout=45
```

结果：**2901 passed、3 skipped、2 warnings，164.32 秒，退出码 0**。完整日志在主工作区 `.goose/runs/consolidation-20260926/test9.log`。

跳过项为 Windows 上不适用的 POSIX 路径语义、POSIX 文件权限，以及未构建的 portable 目录冒烟检查。两条 warning 是 Python 3.8 Windows Proactor 管道清理告警；另有 pytest-asyncio 配置弃用提示和测试 mock HTTP 客户端断开日志。未把告警称为零告警通过。

本次没有生成新 portable 发布包，没有验证 Win7 实机或真实模型 API。主工作区既有 `dist` 是旧产物，原先不支持 `--profile`，不能用它代表新源码基线；保留它用于追溯。当前打包脚本还要求预先准备固定版本 ripgrep 输入，发布准备需单独完成。

全量回归前修复热重载递归扫描阻塞事件循环；定点监听测试显式关闭与其无关的递归目录扫描。所有来源 ref 已核对归档副本及祖先关系；开放 PR 数量为 0。

## 分支归并与恢复约定

唯一长期开发分支为远端默认分支 `master`。合并保留来源提交历史，不压成不可追溯的单个快照。发布时先以非强制推送更新 `master`，再将旧远端 `main`、`dev`、`p1-cordis-foundation` 转成 `archive/consolidation-20260927/` 下的 tag 后移除对应分支。

旧本地分支保存于 `refs/archive/consolidation-20260926/heads/`；旧工作树保留在原目录，以 detached HEAD 保留原提交及未提交文件。可用 `git switch -c <恢复分支名> refs/archive/consolidation-20260926/heads/<原分支名>` 恢复分支。不要自动复启旧 Goose 队列。

## 后续边界

保留 Python 3.8.10 / Win7 产品目标与 React/TS 前端。开发机测试通过不等于 Win7 实机验收，也不等于真实 API/provider 网络验收。后续迁移先建立共享契约与差分基准，再在现代开发环境采用可替换 worker 执行器，详见同目录研究文件。
