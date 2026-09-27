# Cordis 第二批：事件、清理与 Timer

目标上游仍为 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，产品工作树
基于 `a3c4462c`。本记录是工作树观察，不是固定候选 acceptance。
契约升至 `CON-CORDIS-CORE@3`，任务仍停在 review，下游没有放行。

## 同场景观察与修复

| 场景 | 修复前 | 处理 |
|---|---|---|
| C22 多监听器前缀顺序 | 不同 | ambient-loop emit 在下一个监听器之前进入当前 async body，再调度延续 |
| C23 同步异常 | 匹配 | 保留异常中止派发 |
| C24 async 前缀异常 | 不同 | 异步失败不打断其他监听器，通过 loop 异常处理器报告一次 |
| C25/C27 重复 effect disposer、child/root 等待 | 匹配 | 保留所有权和 pending 清理 |
| C26 在途 iterator yield | 不同 | epoch 检查在 next 请求之前；已发出的 next 返回的 disposer 仍需接收 |
| C28/C29 Timer timeout/interval 卸载 | 匹配 | 直接执行上游 Timer 源码，对比取消结果与 effect 清理 |
| C30 取消观察者 | 不同 | shared disposal Task 归 owner 持有，observer 使用 shield，父级记录在实际清理后退休 |

C30 的 JS 侧放弃一个 Promise 观察者，Python 侧取消等待 Task；这是平台适配，
不代表 JS Promise 有 cancel API。用根 owner 等待最终清理，避免只检查第二次
dispose 的返回值就错误宣布完成。

新增九项离线回归从保存的上游 BEFORE 报告读取预期结果，不以修改后的 Python
输出生成期望。原 T38 测试由固定内部任务数组调整为验证等待任务与 inertia
仍被持有、清理只执行一次、最终不存在 pending settlement 或未等待警告。
完整专项通过后，最初因 T38 提前中止遗留任务而触发的后续警告也消失。

## 证据

- `CORDIS-WAVE2-BEFORE.json`：新增九个场景中 C22/C24/C26/C30 不同。
- `CORDIS-WAVE2-AFTER.json`：重跑全部 C1–C30，30 个匹配，无 runner error。
- 测试命令、原始日志摘要、输入和产物 hash 见 `RUN-CORDIS-WAVE2-20260927.json`。

这 30 个 ID 是本地源码推导场景，并非官方案例覆盖率。Timer 的两个卸载路径
也不代表全部 Timer 语义已验证。已有完成状态的 Python Future 与 JS resolved
Promise 的调度、当前 task/context 身份，以及无 ambient loop 的行为仍需单独
验证。未运行 Win7 VM、新 portable 或真实 provider。

## 后续顺序

1. Loader entry 创建、更新、销毁的身份与 effect 所有权，建立真实源码双侧探针。
2. HMR 同路径不同注册身份、pending reload 时再次变更、局部/根卸载；连同必要
   Loader 消费端共同修改，不按文件白名单拆开。
3. 盘点官方 Cordis/Boot 案例并补差异；关闭已有跨盘搜索和 portable 基线失败。
4. 核心契约和固定候选验收满足门禁后，再放行 Boot/Session 纵向迁移。
