# Cordis 同场景源码 oracle

此目录属于现代开发环境，不进入 Python 3.8 / Win7 产品运行路径。
Node 与 tsx 直接执行固定 `reference/vendor/cordis/src`；仅通过 tsconfig
将其 cosmokit 包名映射到同一上游提交的源码。没有替换 Cordis 实现或编辑 reference。

```powershell
npm.cmd ci --prefix scripts/oracles --ignore-scripts --no-audit --no-fund
.venv\Scripts\python.exe scripts/cordis_oracle.py --output .goose/out/cordis-oracle.json
```

`tsx@4.22.4` 与传递依赖固定在 package-lock.json；本次开发机 Node 为 22.22.2。
Python 端保持 3.8 语法。`--tsx`、`--node` 可显式指定安装位置，产物记录实际命令。

每个 C1–C36 场景在独立子进程运行，两侧输出 JSON 观测值，比较值、状态和事件
顺序。只将 JS 的无返回值编码为 JSON null，对应 Python None；不对事件排序、
删除异常或将未完成的进程算成通过。类型、缺少的字段和数组顺序均参与比较。
同步函数本体在两侧分别定义，但行为步骤对应；adapter 的一致性仍需代码审阅，
两个相同的 adapter 错误不会被差分自动发现。

退出码 0 表示选择的轨迹匹配，1 表示轨迹差异，2 表示 runner/adapter 执行失败。
每个进程超时默认 20 秒。stdout/stderr、环境、上游 SHA、产品基点以及源码与
runner 文件 hash 保存在报告中。运行期间不要并发修改输入；报告是工作树证据，
不能自动代替固定候选提交的 acceptance。

C3/C21 用显式 gate 保持 provider 加载中；C12 用 gate 检查依赖清理期间的可见性。
C13 检查 dispose 调用返回瞬间，C14 检查 LOADING 通知中重入 dispose。
C4/C5 共用依赖激活/失效场景，C3/C21 共用严格与非严格读取场景；21 个 ID
不代表 21 个独立官方用例，也不代表完整 Cordis 覆盖。

本 runner 覆盖现有 C1–C36 的主要语义，未穷举取消、无 ambient loop、全部
EventBus 时序、身份隔离或 Loader/HMR 的双侧交错；这些仍需独立场景和消费者
回归。普通 pytest 对 runner 的协议及比较规则做验证，不要求 Win7 安装 Node。

C22–C24 检查多监听器前缀顺序与同步/异步失败；C25/C27 检查重复清理与
child/root 所有权；C26 检查失效时已经在途的 async iterator yield；C28/C29
直接运行上游 Timer 的 timeout/interval 卸载路径。C30 比较放弃 JS Promise
观察者与取消 Python Task 观察者，不声称 JS Promise 存在取消 API。
已完成 Future 与 JS resolved Promise 的调度、task/context 身份仍待独立覆盖。
`tests/test_cordis_wave2_observations.py` 使用保存的上游观测做离线 Python 回归；
它不替代重新运行双侧 runner。

C31/C32 通过真实 Loader 的 builtin 扩展口挂载探针插件，验证配置更新身份及
pending 清理；不覆盖动态模块导入。C33/C34 在真实 HMR 服务中直接触发私有
refresh 入口，验证同 key 合并、不同 key 独立执行；不属于文件监听集成证据。
C35/C36 使用临时文件和公开 registerConfig，经过真实 chokidar 初次扫描，
验证卸载等待和同路径重新注册的身份保护；Python 对应真实轮询适配。
等待通过显式 gate 和 watcher 停止状态同步，进程超时仍判为 runner error。

Loader/HMR 使用未修改的上游源码；新增 schemastery、loader 源码路径映射，
以及固定版本 chokidar、picomatch、code-frame 开发依赖。runner 将
`--expose-internals` 传入 tsx 启动的子进程，以启用真实 Node ModuleLoader。
这些依赖和 Node 内部 API 均不进入 Win7 产品。上游模块热替换与失败回滚、
磁盘 change/unlink 的完整矩阵，以及 refresh 同步前缀调度尚未双侧验证。
