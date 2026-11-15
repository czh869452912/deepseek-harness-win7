# rc022 profile HMR 生命周期退役记录

固定目标：`38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。本记录属于候选合同实施，生产 reference 尚未整体切换，不代表 C1 或发行验收完成。

Profile 模板、新建 manifest 和运行时 Profile 不再声明 `patchReload`；读取已有清单时把该字段作为未知扩展保留，不校验、不补写，也不据此选择启动策略。安装自带的精确旧 bundle tuple 仍按模板归一化，同时保留其他字段和用户 patch。

监听归属由 YAML 的实际 Loader 行决定：

| 组合 | 默认行为 |
| --- | --- |
| base / web | `@deepseek-ai/dsh-hmr`，仅有 `profileContext` 时启用，`root: []` 只监听 profile/home/manifest 配置 |
| headless / sdk / acp | 各自 bundle 明确禁用 HMR，可被后续用户 patch 覆盖 |
| sdk-minimal / 本项目 minimal | 没有 HMR 行 |
| 本项目 standard / creative | 继承 headless 的禁用行 |

模块监听需要明确选择目录，例如在用户 `cordis.patch.yml` 中覆盖：

```yaml
- id: hmr
  disabled: false
  config:
    root: ['.']
```

Launcher 不再在 boot 结束后额外插入 timer/HMR，也不再持有另一组用户 patch watcher。运行中的 HMR 自持配置监听、应用就绪屏障、共享事务队列与卸载清理。禁用该行会终止监听，后续编辑需要重新启动；不存在依赖旧清单字段的备用监听器。

`init_profile`/`initProfile` 使用 `(directory, bundles)` 两个参数，Desktop、SDK、ACP、Portable 检查及测试夹具的 Python 调用方同时迁移。`dsh.cordis.profile` 的发现、manifest、root 写入和层合成转交 canonical boot；移除静默默认 bundle、吞掉损坏清单和另行 heal 的路径。它保留的 bundle/profile 数据表只供兼容调用方读取，不决定 canonical profile 的激活。

本轮只迁移 HMR 所需资源和包标识，其他 bundle 行与原样前端仍按总体迁移计划推进。验证和初次失败、清理记录见 [C1-AU 回执](../../migration/candidates/rc022/profile-hmr-checks.json)。

真实 Web 消费者验证发现退出期间的同步旧模块图扫描可占用事件循环，触发 5 秒退出期限。配置替换路径现在按模块让出事件循环，根上下文进入卸载后终止规划；停止前已取得的资源仍由根收敛等待。外部图采用与部分替换相同的 Python SDK/stdlib/site-packages 宿主边界。保留原始任务栈和 CPU 观察，不调整退出期限。
