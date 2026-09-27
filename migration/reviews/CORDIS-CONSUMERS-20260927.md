# Loader/HMR 消费者双侧观察

固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`，产品工作树基于
`a3c4462c`。本轮增加探针和记录，没有新增产品代码修改；此前两轮核心修复
仍在工作树中。契约细化为 `CON-CORDIS-CORE@4`，状态仍为 draft/review。

## 已观察的边界

| 场景 | 路径 | 观察 |
|---|---|---|
| C31 | 真实 Loader builtin 插件，Entry.update | entry 和 options 身份保留；旧插件清理后新配置生效 |
| C32 | EntryGroup.remove，清理由 gate 暂停 | fiber 已从 entry 脱离，但 store 行保留至清理结束 |
| C33 | 真实 HMR 服务，直接调用 refresh 入口 | 同一身份执行中两次变更合并成一次追加刷新 |
| C34 | 同路径的两个 refresh key | 第二个身份可独立执行，不与第一个共用 pending 状态 |
| C35 | 公开 registerConfig、真实初次文件扫描 | watcher 已停止时卸载仍等待 pending refresh；结束后注册清空 |
| C36 | 公开注册、撤销及同路径重新注册 | 旧刷新未结束时新注册可运行；旧清理完成后新注册仍保留 |

六项均匹配，扩展 runner 后重跑 C1–C36 全部匹配。C33/C34 使用精确触发的
组件探针，不是磁盘事件测试；C35/C36 使用真实临时目录、chokidar 初次扫描
及 Python 轮询适配，不注入虚假 watcher。Loader 使用官方 builtin 扩展口，
不覆盖动态模块解析与导入缓存。

C35 在读取 pending 观测前，分别等待上游 watcher.closed 和 Python
轮询服务停止，避免刚创建 disposal Task 尚未运行时的假等待断言。
所有 pending 路径以显式 gate 释放，并在 finally 中卸载根 Context。

## 执行环境和证据

开发依赖固定于 scripts/oracles/package-lock.json：tsx 4.22.4、chokidar
4.0.3、picomatch 4.0.3、@babel/code-frame 7.29.0。schemastery、Loader、
HMR 和 Cordis 均映射到未修改的固定上游源码。Node 22.22.2 通过传给 tsx
子进程的 --expose-internals 获取真实 ModuleLoader，不使用替身。
这些都是开发侧依赖，不进入 Python 3.8 / Win7 产品。

初次调试中的 Node 启动参数、baseUrl 和 asyncio.create_task/ensure_future
问题属于适配器错误，修正后才保存正式观察；没有将它们算成产品差异或通过。

- `CORDIS-CONSUMERS-20260927.json` 保存新增六项原始观察。
- `CORDIS-C1-C36-20260927.json` 保存完整 36 项重跑。
- `RUN-CORDIS-CONSUMERS-20260927.json` 保存测试结果、日志和输入 hash。
- `tests/test_cordis_consumer_observations.py` 从冻结上游观察读取预期值，
  离线重放 Python；这不替代双侧 runner。

## 尚未覆盖与下一步

1. Module HMR 的真实代码替换、缓存失效及失败回滚；Include pending apply
   与再次配置更新、服务卸载之间的等待关系。
2. refresh 同步前缀、已完成 awaitable、跨语言 task/context 身份和错误处理
   交错；本轮只观察明示 gate 边界，不声称所有微任务顺序一致。
3. 磁盘 change/unlink、目录删除重建及 Windows 7 实际文件监听环境。
4. 官方集成用例逐项映射。`git -C reference ls-files 'vendor/*/test*'`
   未列出 vendor 测试；这不表示上游没有覆盖。`reference/vendor/README.md`
   指向 Boot 的 app-boot/user-patches、CLI built-bin 以及目录选择器的
   loader-composition 等测试，应按行为和消费者继续盘点。
5. 旧 portable 和跨盘搜索三个基线失败仍需各自任务关闭；固定候选验收前
   不解锁 MIG-SPINE-001，不把 36 个本地 ID 当作官方覆盖分母。

另外，公开 Loader 当前使用 `dsh/cordis/loader.py` 内的 EntryTree/EntryGroup
实现；拆分的 loader_entry.py/loader_group.py 也有调用入口。契约消费者清单
补入 loader.py，后续需按实际调用路径核对，不能只根据文件名判断实现已统一。
