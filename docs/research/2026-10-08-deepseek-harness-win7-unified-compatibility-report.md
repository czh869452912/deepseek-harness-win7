# DeepSeek Harness Win7：Chromium 108 前端兼容性复核与交付门禁设计

> **文档类型**：两次故障排查合并报告 / 兼容性风险台账 / 后续迁移约束 / 回归验收参考
> **版本**：v1.2（源码与交付 bundle 复核；补充 Chromium 108 交付门禁设计）
> **日期**：2026-10-08
> **项目**：[`czh869452912/deepseek-harness-win7`](https://github.com/czh869452912/deepseek-harness-win7)
> **结论状态**：源码与交付 bundle 确认 `AbortSignal.any()` 和审批/提问中的 `Promise.withResolvers()` 兼容缺口；已定位模型选择 loading 的双输入条件。Win7 故障与临时 polyfill 部分恢复沿用已有现场反馈，原始材料尚未归档；**正式兼容层和 Chromium 108 专项门禁尚未实施，不能签收交付可用性**。
> **适用范围**：Python 3.8.10 Host、原版 Cordis/React Web GUI、Windows 7 SP1 及相关便携版。
> **本次复核基线**：本地 `master` / `0f06bed62c823821068a100c284b90e4488edc22`；固定上游 `cd5ef8148158c3a752a658978873241fdf8e2bbc`。文中源码结论绑定此基线，不自动适用于现场使用的未知版本 Portable。

## 1. 执行摘要

**核心缺口是：全盘接收固定上游 WebUI 时，确认了产物一致性，却没有独立确认目标 Chromium 108 的运行兼容性。** 原版一致、构建通过、现代浏览器旅程通过，均不能证明目标旧浏览器可用。下一步应复核完整前端交付面，并建立“输入与产物审计 → Chromium 108 实际运行 → 同一最终 Portable 解压运行 → 发布回执绑定”的独立门禁，防止不兼容版本进入交付。具体设计见第 6.5–6.8 节；本次只完善报告和交接，不实现产品补丁或门禁。

本报告合并两次关联排查：**A. Win7 浏览器 JS API 缺失造成会话控制流失败与重复重连**；**B. 配置模型后，模型选择入口长期显示“正在加载模型…”**。两者属于同一浏览器运行时兼容风险域，且会话控制流缺失能够解释模型选择框得不到状态的现象，但模型目录 RPC 是否也有独立异常尚未通过 Network/Host 日志证明。

本次在 Windows 7 真机上测试 Web GUI 时，浏览器控制台报告 `TypeError: AbortSignal.any is not a function`，调用栈指向 `RemoteStream.read()`。同一界面持续出现 `[connection] connection lost, retry #N`（截屏时超过 120 次），但 Windows 10 环境未复现。

Win7 测试浏览器的 User-Agent 显示 `Windows NT 6.1; WOW64`、`Chrome/108.0.5359.95`、`QIHU` 标识；控制台能力探针进一步确认：`AbortSignal.any === undefined`、`AbortSignal.timeout` 为 `function`、`Promise.withResolvers === undefined`。

**首要问题是前端使用了目标浏览器不支持的 Web API，不是 Windows 7 防火墙所能解释的 JavaScript `TypeError`。** 仓库的 `RemoteStream` 和连接代管理逻辑直接调用 `AbortSignal.any()`；调用失败足以阻断相关流的建立。反复重连很可能因此发生，但仍需在注入兼容层后，通过握手、WebSocket 帧及服务端日志确认是否还存在独立网络问题。

**新的现场复测证据**：用户在 Win7 浏览器 Console 临时注入了较简易的 polyfill 后，原先的若干异常及 timeout 相关报错不再出现，前端流程可以进一步执行；但界面所有功能与运行状态**仍不完全正常**。因此它是“同一类兼容性缺口确实影响运行”的有力支持，不能作为完整修复、模型列表彻底恢复或网络全面正常的签收证据。用户没有提供临时 polyfill 的准确代码与前后日志，不能反推出究竟补齐了哪些 API、哪项改变直接消除了 timeout 相关报错。

迁移工程今后应将**目标浏览器 API 能力**与**目标操作系统/ Python 可运行性**并列作为明确的发布基线，在 **Host 生成的 HTML 中、任何客户端模块执行前**注入受控的兼容层，既维持固定上游前端源码/构建产物的可对比性，也补齐浏览器运行时的能力差异。Chromium 108 自动运行与 Win7 真机认证须分别记账；后者沿用既有延期决策，不以本报告自动恢复执行，亦不以现代 Windows 上的结果替代。

本次还确认审批/用户提问的源码及交付 bundle 各有两处 `Promise.withResolvers()` 调用。因此，启动 `READY_MARKUP` 的局部替代不能覆盖这些交互；该 API 对启用这些功能的 Web 交付属于 **P0 兼容缺口**，但尚不能断言它就是用户临时 polyfill 后其他异常的实际原因。

## 2. 测试环境和直接证据

**证据来源边界**：下表的 Win7 截图、能力探针和 Console 临时补丁效果继承原报告的现场描述。本次未取得可定位的原始截图、注入代码、日志、现场候选提交或 ZIP 散列，没有重做 Win7 实测。新增可复核依据是本地源码、实际 bundle 与固定上游逐字节比较，以及公开兼容资料；后续须把原始现场材料绑定到精确候选再归档。

| 维度 | 观察 / 结论 | 证据级别 |
| --- | --- | --- |
| 操作系统 | Windows 7，User-Agent 标识为 Windows NT 6.1、WOW64 | 真机截图确认；SP1 版本未从截图核实 |
| 浏览器 | Chromium 108.0.5359.95 内核标识，带 QIHU 字样 | User-Agent 观测；具体 360 浏览器产品/兼容模式未完全核实 |
| Windows 10 对照 | 此前的控制流异常与模型选择异常未观察到相同表现 | 用户测试反馈；不是 Win10 全量验收 |
| `AbortSignal.any` | `undefined` | 真机 `typeof` 检测确认 |
| `AbortSignal.timeout` | `function` | 真机 `typeof` 检测确认 |
| `Promise.withResolvers` | `undefined` | 既有现场探针记录；本次源码/bundle 确认审批和提问确有调用，**尚无这些调用在现场报错的原始日志** |
| 报错 | `TypeError: AbortSignal.any is not a function`，栈顶 `RemoteStream.read (remote-stream.ts:107:36)` | 控制台截图确认 |
| 伴随现象 A | `[connection] connection lost, retry #N` 持续增长，截图至少出现 `#126` | 控制台截图确认；是否全部由 API 缺失引起仍待隔离验证 |
| 伴随现象 B | 已配置模型，但模型选择始终显示“正在加载模型…”且无法正常选取 | 用户 Win7 实测；未取得模型目录请求/响应抓包 |
| Console 临时 polyfill | 简易 polyfill 后流程推进，若干原有错误和 timeout 相关报错不再出现 | 用户后续实测；未提供注入代码与完整前后日志 |
| 修复完整性 | 前端所有功能和运行状态仍不完全正常 | 用户实测，**不允许标记为已完成** |
| 先前工作区目录选择故障 | 用户已报告该问题不再存在 | 与本次浏览器报错分属不同故障，不应混为一谈 |

**浏览器版本边界**：[Google 官方系统要求](https://support.google.com/chrome/a/answer/7100626)确认 Chrome 109 是最后一个支持 Windows 7 的 Chrome 正式版本。MDN 维护的兼容数据分别记录 [`AbortSignal.any` 从 Chrome 116 支持](https://raw.githubusercontent.com/mdn/browser-compat-data/main/api/AbortSignal.json)、[`Promise.withResolvers` 从 Chrome 119 支持](https://raw.githubusercontent.com/mdn/browser-compat-data/main/javascript/builtins/Promise.json)。因此，即使从该真机 Chromium 108 升级到 Win7 可运行的官方 Chrome 109，这两个 API 仍不会自然获得支持。第三方 Chromium 浏览器存在定制和版本差异，应以实际能力探针为准。

## 3. 故障链路与代码定位

### 3.1 已证实的异常链路（P0）

前端会话流在 [`packages/api/gateway/src/client/remote-stream.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/api/gateway/src/client/remote-stream.ts) 第 107 行附近执行：

```ts
const generationAbort = new AbortController()
const signal = AbortSignal.any([this.lifetime.signal, generationAbort.signal])
```

Chromium 108 中该静态方法不存在，调用直接抛出 `TypeError`，导致 `RemoteStream.read()` 对应的控制/快照流失败。该异常**不是服务端拒绝、认证失败或防火墙规则本身产生的错误**。

### 3.2 连接重试的合理解释（需复验）

[`packages/api/gateway/src/client/remote-events.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/api/gateway/src/client/remote-events.ts) 的 `pumpEvents()` 在启动连接代时同样执行：

```ts
const generationSignal = AbortSignal.any([signal, failed.signal])
```

[`packages/client/connection/src/client/connection.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/connection/src/client/connection.ts) 在连接代失败后打印 `connection lost, retry #N` 并退避重试。由此可形成合理的因果假设：**缺少 `AbortSignal.any` → 连接代初始化异常 → 进入重复重连**。是否还存在实际 WebSocket 连接错误，必须在 API 缺失修复后单独观察网络面板和 Host 日志。

**本次源码复核补充**：`pumpEvents()` 第 128 行在 `openStream()` 之前调用 `AbortSignal.any`，其失败 Promise 经 `runGeneration` 交给 `ConnectionController.loop()`，后者进入共享退避和重试。因此，在该方法缺失且未注入兼容层的条件下，这条代码路径足以触发重连，甚至尚未打开事件逻辑流。`RemoteStream.read()` 第 107 行的调用也在内部 carrier 重试 `try` 之前，属于独立的流初始化阻断点。两者共同由 API 缺失解释，但不能把 `RemoteStream.read()` 的一个堆栈直接当作现场全部连接重试的唯一原因。

### 3.3 一个已有但不充分的兼容特例

[`dsh/host/webserver/injections.py`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/host/webserver/injections.py) 中的 `READY_MARKUP` 已专门用 `new Promise(...)` 实现启动就绪 deferred，规避上游使用的 `Promise.withResolvers`。这说明工程已经存在**针对 Win7 浏览器的局部修复**，但它**没有全局定义 `Promise.withResolvers()`**，也没有解决运行时 `AbortSignal.any()` 调用。

**已核实的其他调用面**：审批插件 `packages/client/ui-approval/src/client/index.ts:52` 和 `src/client/contract/slots.ts:100`；提问插件 `packages/client/ui-user-questions/src/client/index.ts:64` 和 `src/client/contract/slots.ts:140`。调用分别用于交互完成等待和 Pending 对象的结果 Promise，在相关 Remote Event 到达时执行。两份 `lib/client.js` 各保留两处调用；Gateway `lib/client.js` 保留四处 `AbortSignal.any`。上述七个源码文件及三份 bundle 与固定 `reference` 对应文件逐字节一致，说明**原版产物完整性与旧浏览器运行兼容性是两个不同的检查结论**。这只是已定位的调用面，不是全前端扫描完成证明；实际装配范围仍须从活动 Loader 与 boot manifest 获取。

### 3.4 模型选择持续 loading：已定位前端等待条件（关联故障 B）

模型选择入口位于 [`packages/client/ui-model-selection/src/client/ModelSelect.tsx`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/ui-model-selection/src/client/ModelSelect.tsx)。它从每个 Session 的 `ModelDirectoryState` 取得 `current/status/groups`。在 `current === null && status === 'loading'` 时会显示 **“正在加载模型…”**。

下游核心判断位于 [`packages/client/ui-model-selection/src/client/directory.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/ui-model-selection/src/client/directory.ts) 的 `syncInputs()`：

```ts
const catalog = this.catalog.store.getSnapshot()
const projected = modelSelectionProjection(this.projected.getSnapshot())
if (catalog.status !== 'ready' || catalog.value === null || projected === undefined) {
  // 第一次解析前：只要模型目录或 Session 模型投影未就绪，就保持 loading（或错误态）
  // ...
}
```

这不是“模型 API Key 校验正在进行”的专属提示；模型目录和 Session 投影**两个输入缺一不可**。尤其 `projected === undefined` 时，即使目录已经返回，也可能无法使选择器从第一次 loading 状态进入 ready。

实际依赖链可拆为：

```text
用户点击/进入模型选择入口
  -> ModelDirectoryResolver / ModelDirectory
     ├─ 模型目录 ModelCatalogDirectory.load()
     │    -> ctx.remote.session.modelCatalog()
     │    -> Python Host dsh/api/session.py::modelCatalog()
     │    -> LLM providers / list_models / resolve_model_info
     └─ 当前 Session 的 modelSelection 持久投影
          -> Session 初始化 / control baseline / follow 与 projection 更新
  -> ModelDirectory.syncInputs() 同时要求 catalog.ready + projection 存在
  -> ModelSelect 显示模型并允许 selectModel
```

**关联机制**：此前已实测 `RemoteStream.read()` 在 Chromium 108 因 `AbortSignal.any()` 抛出异常；而 Session 控制流正是通过该 RemoteStream 创建（[`packages/api/session-controller/src/client/transport.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/api/session-controller/src/client/transport.ts) 与 [`.../src/client/index.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/api/session-controller/src/client/index.ts)）。这为“Session/投影状态不完整 → 模型选择一直加载”提供了**有源码支持的高置信度解释**。但尚未验证模型目录 RPC 的实时状态及具体 Session 投影数据，**不能宣称已证明唯一根因**。

### 3.5 模型目录与模型调用须分开排查

[`packages/client/ui-model-selection/src/client/catalog.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/ui-model-selection/src/client/catalog.ts) 通过 `session.modelCatalog()` 加载目录；成功置为 `ready`，失败置为 `error`，并在连接代重置、LLM 适配器或设置更新时重新加载。

Python Host 对应 [`dsh/api/session.py`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/api/session.py) 中的 `modelCatalog()`：遍历注册的 providers，通过 `list_models` / `resolve_model_info` 产生 `groups`，单个 provider 的失败被汇入 `failures`。**列出模型元信息**和**真正向模型 API 发起推理请求**是不同路径。不能仅凭模型选择无法展开就认为 API Key、模型服务或防火墙有问题；也不能因为修复控制流就跳过模型目录 RPC 验证。

本次确认 `modelCatalog()` 位于第 177 行，返回 `default/routableProviders/groups/failures`；Provider 组内失败被收集，并不意味着整个 RPC 已失败。根服务 `ModelDirectoryResolver` 启动时主动加载共享目录，连接重置、适配器、设置或凭据变更会触发重新加载；并非只有打开菜单才开始请求。目录即使已 ready，首次 Session 投影仍为 `undefined` 时，`ModelDirectory` 仍显示 loading。须分别采集两个输入状态及对应连接代，不能用“已填写模型配置”替代它们的运行证据。

这次“配置完成但无法选取”应按以下顺序定位：① 浏览器 API 与 Console 首错；② Connection 连接代/WS；③ `session.modelCatalog()` 的请求、返回和错误；④ 当前 Session `modelSelection` 投影是否存在；⑤ `ModelDirectory` 是否进入 ready；⑥ `selectModel` 响应及恢复；⑦ 最终实际模型请求成功。

### 3.6 新增现场证据：临时 polyfill 的作用与边界

- **实测变化（用户反馈）**：通过 Console 注入简化 polyfill 后，前端流程比原来更进一步；此前若干异常与 timeout 相关报错消失。
- **支持的判断**：至少一部分阻断性问题确实来自旧浏览器缺少或不能正确使用的 JavaScript 运行时能力；纯粹把重连警告当成防火墙故障不合适。
- **不能据此推出**：所有连接都已建立、所有控制/投影流都已恢复、模型列表已正确显示、超时机制正确、最终模型调用已成功。
- **未记录信息**：临时 polyfill 的具体代码、注入 API 集合、刷新后是否仍有效、Network 请求与状态、哪些其他功能异常。报告均记为待补证据，**不能替代正式改动和回归测试**。
- **特别注意**：真机能力探针原本显示 `AbortSignal.timeout` 已是 `function`；“timeout 不再报错”不等于“此前缺少 `AbortSignal.timeout`”，还可能是上游异常连带影响了超时/重试流程。

### 3.7 区分先前的原生目录选择问题

先前的工作区选择等待属于另一条链路：[`dsh/host/directory_picker/native.py`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/host/directory_picker/native.py) 使用 PowerShell `-STA` + WinForms `FolderBrowserDialog`；替代的 `examples/web-browse.patch.yml` 可装配应用内目录浏览器。其涉及 OS 原生 GUI/子进程/窗口焦点，不应与这次 **JavaScript 浏览器 API** 报错归为单一根因。

## 4. 迁移兼容性基线：明确四个彼此独立的运行层

| 层级 | 本工程应写入的约束 | 错误示例 | 验收方法 |
| --- | --- | --- | --- |
| **OS 层** | Windows 7 SP1 x64（如支持其他架构应单列） | 新版 Windows API、系统 DLL、COM、TLS/证书、窗口焦点不兼容 | Win7 真机 GUI/进程/网络测试 |
| **Python Host 层** | Python 3.8.10；依赖轮子及子进程必须能在 Win7 加载/运行 | Python 3.9+ 语法/API、仅支持 Win10 的原生轮子 | 干净机/Portable 启动、依赖加载、Host 回归 |
| **浏览器运行时层** | **至少覆盖实测 Chromium 108 能力集**；不能把 Chrome 109 或现代 Win10 浏览器等同于 Win7 可用性 | `AbortSignal.any()`、`Promise.withResolvers()` 不存在 | 目标版本能力探针、真实页面与连接/交互测试 |
| **协议与构建产物层** | HTTP / WebSocket / Typert Remote / 客户端动态插件 Bundle 均须在目标浏览器正常执行 | JS 语法与内建 API 不兼容、仅主入口打补丁而插件/Worker 仍失败 | 构建产物扫描、端到端流恢复、动态插件装配测试 |

**重要原则**：`tsconfig.target`、Vite `build.target` 和转译器通常主要控制**语法转换**，并不会自动补齐 `AbortSignal.any` 这类 Web API。当前 [`apps/web/vite.config.ts`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/apps/web/vite.config.ts) 设有 `build.target: 'es2022'`；这**不是** Chromium 108 的完整运行能力证明。动态 Client Bundle 以及 Worker 等独立全局上下文需要另行核查。

## 5. 修复和架构约束

### P0：在客户端启动前建立统一的浏览器兼容层

1. **优先使用 Host 侧注入，不修改固定上游业务逻辑**：复用现有 `webserver/index-inject` 的 `head` 脚本注入能力，或受控的 HTML index tap；确保脚本在全部 `<script type="module">` 和动态 Client Bundle 执行前生效。
2. **仅按能力缺失补丁**：`if (typeof AbortSignal.any !== 'function') ...`、`if (typeof Promise.withResolvers !== 'function') ...`，现代浏览器保留原生实现。
3. **以语义等价为目标，不以“无报错”为目标**：`AbortSignal.any` 要支持 iterable、空集合、非法输入拒绝、多个预中止信号按输入顺序选择原因、后续取消和监听器清理；还需验证组合信号级联与重入取消。`Promise.withResolvers` 要提供正确的 `promise/resolve/reject`、thenable 与重复结算语义，并覆盖通用构造器、Promise 子类及非法接收者；不能用固定 `new Promise` 的箭头函数冒充完整实现。语义依据见 [DOM Standard](https://dom.spec.whatwg.org/#dom-abortsignal-any) 与 [ECMAScript](https://tc39.es/ecma262/multipage/control-abstraction-objects.html#sec-promise.withResolvers)。
4. **注入失败要可观测**：在启动诊断输出缺失 API 和补丁版本；缺失关键能力且未成功补齐时应提示“浏览器不受支持”，而非无限连接重试。
5. **拒绝散点修复**：不要在每个 `remote-stream.ts`、`remote-events.ts` 或插件内逐处重复 polyfill；尽量保持原版源码/构建文件的 SHA 对齐。若确需修改上游，必须单独记录偏差和迁移理由。
6. **隔离作用域**：Host Python 与 Node/TS 参考包不使用浏览器 `window`；页面 polyfill 也不会自动进入 Web Worker、iframe 或其他 realm。若实际启用这些运行面，须单独注入/测试。

**工程化 polyfill 语义清单**：

| API | 本机观测 | 最低修复要求 | 通过标准 |
| --- | --- | --- | --- |
| `AbortSignal.any` | 缺失；已触发阻断性错误 | 接受任意 iterable；支持预中止、首个取消原因、异步取消；清理监听器、不改变原生实现 | 控制流、断线重试、取消/超时测试通过 |
| `Promise.withResolvers` | 缺失；审批/提问源码及 bundle 确有调用，现场触发尚待取证 | 提供 `promise`、`resolve`、`reject`，支持构造器语义；保留原生实现 | 真实审批、提问、计划确认及取消/卸载闭环通过 |
| `AbortSignal.timeout` | 本机存在 | 不应覆写；审查相关 `reason` / `throwIfAborted` / 错误分类 | 实际 deadline/取消测试通过 |

**落地接入点**：`dsh/host/webserver/injections.py` 可生成 `head` 类型 `script` 行，`dsh/host/webserver/webserver.py` 的 `render_index()` 将注入行应用到 HTML，`dsh/host/frontend_static/frontend_static.py` 则负责提供实际发布版 index。建议实现为**独立的 Win7 兼容性插件/模块**，显式声明启用条件和版本，不把大量补丁塞进 `READY_MARKUP`。

该插件应通过 `ctx` 服务和 `webserver/index-inject` 事件接入，声明所需服务并使用可撤销注册。`render_index_injections()` 将 head 行放在 `<head>` 开标签之后、按表顺序输出；所以仅声明 placement 为 head 仍不够，必须验证它位于所有可执行 parser/preload 脚本之前，并核查后续 raw tap、静态入口和 CSP 是否改变效果。卸载可撤销 Host 的后续注入注册，但已打开页面中的全局 polyfill 不会随 Host 卸载自动撤回；该边界应写入生命周期测试。

### P0：恢复“模型目录 + Session 投影”的双输入闭环

在确保兼容脚本**先于所有 JS 模块**执行后，必须分别观测 `modelCatalog` 和 `modelSelection` 投影。只有“能够展开并选择具体模型、刷新/重连后仍正确、实际推理请求可工作”才算通过。

尤其要覆盖：`modelCatalog` 返回正常但 Session control/follow 投影尚未 ready；目录请求失败；Provider 局部失败；连接代重启清空并重新加载；初次加载竞态；已选模型不在当前目录但 Provider 仍可路由等情况。不能把“把 loading 字样隐藏”或“强制填充默认模型”视为修复，那会掩盖真实的状态同步问题。

### P1：扩展兼容性清单与自动检查

- **已定位交付兼容缺口**：`AbortSignal.any`（P0）；`Promise.withResolvers`（审批/提问功能 P0；启动就绪的局部替代不能覆盖这些调用）。
- **已支持**：`AbortSignal.timeout`（本台真机观测）。不要对已经存在的原生方法强行覆盖。
- **需要审计但不得预判为故障**：`Array.prototype.toSorted/toReversed`、`Object.groupBy`、`Array.fromAsync`、`Symbol.dispose`、`Error` cause、`structuredClone`、`AbortSignal.reason/throwIfAborted`、WebSocket 与相关异步迭代特性，以及第三方构建产物的运行时代码。以使用位置、兼容数据库和真机实际调用判定。
- **包括动态模块**：`packages/client`、`packages/api/gateway/src/client`、`packages/client/connection`，以及实际交付的 client plugin Bundle；不要只扫描 `apps/web` 首屏代码。

### P1：区分故障来源，禁止仅凭 `connection lost` 判断网络问题

| 现象 | 优先验证 | 不应直接认定 |
| --- | --- | --- |
| `TypeError: <API> is not a function` | 浏览器版本、运行时 API 能力、polyfill 是否先加载 | 防火墙、Host 崩溃 |
| 重连伴随同步 `TypeError` | 修复 API 后重试；查看流启动异常 | 一定是 WebSocket 被拦截 |
| Network 面板握手 401/403 | token、认证与访问控制 | JS API 问题 |
| WS 握手失败/连接超时 | 端口、Host 日志、代理、防火墙、TLS | 已由 polyfill 解决 |
| 页面可加载但交互卡死 | 动态 Bundle、异步流、Promise/Abort 语义 | 所有协议均成功 |
| 模型入口一直显示“正在加载模型…” | `modelCatalog()` 是否 ready；Session `modelSelection` 投影是否 undefined | 一定是 API Key/模型服务不可用 |
| Console polyfill 后“顺畅一些” | 对比首错、WS、目录、投影及实际模型调用 | 已完成正式兼容修复 |

## 6. 建议加入仓库的迁移门禁

### 6.1 开发时的能力检查

在 Win7 浏览器 DevTools 执行，记录 User-Agent、实际能力以及首次报错：

```js
console.table({
  userAgent: navigator.userAgent,
  abortSignalAny: typeof AbortSignal.any,
  abortSignalReason: 'reason' in AbortSignal.prototype,
  abortSignalThrowIfAborted: typeof AbortSignal.prototype.throwIfAborted,
  abortSignalTimeout: typeof AbortSignal.timeout,
  promiseWithResolvers: typeof Promise.withResolvers,
  arrayToSorted: typeof Array.prototype.toSorted,
  structuredClone: typeof globalThis.structuredClone,
  webSocket: typeof WebSocket
})
```

报告中必须区分：**方法缺失**、**功能被调用而出错**、**经兼容层后恢复**、**仍有未排除的环境因素**。

### 6.2 回归矩阵（建议作为发布阻断条件）

| 用例 | Chromium 108 / Win7 真机 | 现代 Chromium / Win10 |
| --- | --- | --- |
| 页面启动、插件装配、Console 无关键异常 | 必测 | 必测 |
| 鉴权后连接代建立、WebSocket 持续稳定 | 必测 | 必测 |
| 工作区选择（原生和 browse 两种路径） | 必测 | 必测 |
| 创建工作区、创建会话、刷新/重启后恢复 | 必测 | 必测 |
| `session.modelCatalog()` 目录成功、局部失败可见、恢复重试 | 必测 | 必测 |
| Session `modelSelection` 投影正确到达并驱动选择框退出 loading | 必测 | 必测 |
| 模型选择与推理强度选择、刷新/断线后保持 | 必测 | 必测 |
| 选中模型后发起一次真实请求并得到响应 | 必测 | 必测 |
| 正常模型流式输出、取消、中断恢复 | 必测 | 必测 |
| 断线重连与 Session 控制/快照流恢复 | 必测 | 必测 |
| 并发取消/超时/销毁，不出现悬挂监听器和无限重试 | 必测 | 必测 |
| 审批/提问/动态 Client 插件装配 | 必测 | 必测 |
| Portable 包在无开发环境的 Win7 上启动 | 必测 | 建议 |

**建议门禁顺序**：完整产物审计 → 固定 Chromium 108 自动运行及现代浏览器反向回归 → 同一最终 Portable 实际解压运行 → 回执绑定发布。Win7 真机是单独的 OS/浏览器组合认证，目前按既有决策延期；恢复时执行上表真机矩阵。未执行真机不得宣称 Win7 实机认证。其他引擎构建须单列结果，不能默认替代 Chromium 108 必需 lane。

### 6.3 现场定位手册：区分“目录缺失”和“投影缺失”

1. **记录首个红色错误而非后续重试计数**：旧浏览器 API 缺失的 `TypeError` 优先于判断防火墙。记录注入前/注入后 Console 原始截图与 User-Agent。
2. **Network 检查 WebSocket 握手/帧**：确认连接代建立且能持续接收，而不是仅看到页面和按钮。
3. **Network/Host 日志检查 `session.modelCatalog()`**：请求是否发出、是否收到成功业务结果、返回 `groups`/`failures` 是否合理；注意这可能封装在 Gateway RPC 中，不一定以 `modelCatalog` 命名的独立 URL 出现。
4. **核查 Session 模型选择投影**：在 Host 投影和 Client 观测链中确认当前 Session 的 `modelSelection` 值不再是 undefined。不要直接在生产模式打印用户凭据或完整模型请求。
5. **验证选择与真实调用**：点开菜单，选择另一个有效模型/推理强度，重载页面并确认保持，发送测试提示词并核实实际 Provider 响应。
6. **若仍异常**：补录首个不同的新 Console 异常及其堆栈，按“JS API → 连接层 → 模型目录 → 投影 → UI Store → 模型调用”逐层定位，不把修复一次 polyfill 当作关闭整个缺陷。

### 6.4 修复后的明确通过标准

以下是相应运行范围的功能标准；108 自动化与延期的 Win7 真机闭环分别记录，不能互相替代。

- `AbortSignal.any` 缺失时，兼容层能在前端模块执行前建立符合预期的函数。
- 浏览器不再出现 `remote-stream.ts:107` 对应 `TypeError`。
- `remote-events` 能建立连接代，连续数分钟无无故增长的重连计数。
- Network 中实际 WebSocket 握手成功且能收发帧；Host 日志无协议/认证异常。
- 工作区、会话、消息、取消和恢复功能完成 Win7 真机闭环。
- 模型目录 `session.modelCatalog()` 可重复获取；会话 `modelSelection` 投影准时到达；模型选择框不再无期限 loading。
- 可以选择模型、刷新/重连后恢复、发起实际模型请求并得到响应。
- 现代浏览器使用原生 API，不因兼容层引入行为倒退。
- 若仍有网络错误，单独建立网络/安全软件缺陷，不要继续归因于已修复的 API。

### 6.5 现有门禁实际覆盖与缺口（本次核查）

| 现有入口 | 已有保护 | 尚未提供的 Chromium 108 资格 |
| --- | --- | --- |
| `scripts/frontend-inputs.json`、`scripts/import_frontend.py` | 绑定固定上游、完整 build record 和逐文件散列；当前记录 218 个产物 | 文件与原版一致不能证明语法、Web API、CSS、第三方运行时代码兼容 |
| `scripts/verify_release.py` | 冻结候选、完整 Python/Source/配对、真实浏览器与同包解压；回执绑定 candidate、前端和 archive SHA-256 | 当前要求有真实 Chromium 可执行文件，未要求主版本为 108，也没有 108 专项兼容结果 |
| `scripts/verify_portable.py`、`scripts/portable_browser_oracle.mjs` | 在实际解压 Host 上运行原版前端旅程 | 未证明这些旅程在 Chromium 108 执行；当前 scope 明确不认证 Win7 |
| `.github/workflows/verify.yml` | 调用完整发行入口，使用 runner 已安装的 Google Chrome | Chrome 路径不是版本锁；没有固定 108 浏览器下载/散列/版本及缺失能力探针资格 |
| `.github/workflows/release.yml` | 发布 verification 上传的原 ZIP，不另建不同包 | 只有加入并强制校验 108 回执后，才能证明该 ZIP 通过目标浏览器兼容门禁 |

因此不能把本报告写为“现有门禁已经保证 108 兼容”。应新增专项检查并接入已有统一门禁和发布资格验证，而不是再建立一套重复全量 Python 测试。具体实现文件名、CLI 参数和回执 schema 尚未确定，下面是设计要求。

### 6.6 门禁设计：四个检查阶段

| 阶段 | 检查范围与产出 | 拒绝条件 |
| --- | --- | --- |
| G1 输入与全前端产物审计 | 从固定前端清单、包导出、活动 Loader/boot manifest 建立实际浏览器文件集合，包含主入口、动态 client bundle、依赖 chunk、懒加载、CSS 和实际启用的 Worker/iframe；记录路径、SHA-256、运行 realm、API/语法/CSS 兼容审计及兼容层覆盖 | 缺文件、散列不符、未知 bundle/realm、实际使用但 108 不支持且无已验证适配的能力；不能只扫描 TS 源码或靠正则无命中放行 |
| G2 固定 Chromium 108 实际运行 | 固定可复现的浏览器发行物/完整版本和二进制散列，启动后通过浏览器协议版本、UA、注入前后能力探针核对；在 canonical Web Host 中执行第 6.2 节相关旅程及兼容层语义测试；保存 Console、pageerror、请求/WS 帧和 Host 观察 | 用现代 Chromium 冒充 108、缺必需依赖、首错/未处理拒绝、关键交互失败、无限重连、取消/超时/资源清理失败；缺失或 skipped 必需项按未通过处理 |
| G3 最终 Portable 同包资格 | 对待发布 ZIP 记录 SHA-256，在新拥有目录安全解压，启动包内 Python 与 canonical Web profile；复核包内前端/兼容层散列，使用同一固定 108 运行关键旅程和动态插件，并验证真正由该解压 Host 服务的 HTML 注入顺序 | 开发工作区代替解压包、从工作区补文件、兼容层未打包/未装配、最终 HTML 先执行客户端、资源服务不完整、同包旅程失败 |
| G4 回执与发布资格 | 将 G1–G3 结果接入 `verify_release.py` 的资格校验及现有 artifact 发布链；同时保留现代浏览器反向回归和原版完整性要求 | 缺 108 回执、候选/输入/前端/兼容层/ZIP 身份不一致、结果非 passed、篡改/缺失回执、验收后重建不同 ZIP；均拒绝发布资格 |

**浏览器识别不能只靠 UA**：第三方 QIHU 产品版本与 Chromium 内核版本应分别记录。先选定可信可获得的固定 108 observer，再验证它的二进制来源/散列和运行能力；现代系统上的 Chromium 108 自动测试只证明目标引擎范围，不等于 Win7、第三方浏览器或原生 GUI 认证。自动 observer 是开发依赖，不加入零依赖 Portable 产品运行依赖。

**审计不是把所有旧 API 字符串设为禁用词**：为每个实际命中记录使用位置、是否进入浏览器产物、是否启用、realm、108 支持资料和适配测试。Node 测试中的 `Promise.withResolvers` 不等于页面故障；交付 `lib/client.js` 中的调用则必须评估。CSS 也须做关键布局/交互的视觉核验，不能以 JavaScript 无异常替代整个 WebUI 可用。静态扫描漏报与动态旅程未触达必须相互补足。

**控制组**：兼容层未启用且目标能力缺失时，已知故障应能复现；启用后对应场景通过。另在现代浏览器检查原生函数身份保持、结果不退化。现代浏览器删除 API 的实验只能作为补充控制，不能代替实际 Chromium 108。若固定前端遇到无法通过运行时补齐的语法或 CSS 缺口，应阻断候选并单列适配决策，不能为了通过而悄悄改写原版源码、bundle 或 pin。

### 6.7 最小必需旅程、回执与拒绝控制

1. **启动与连接**：served index 的兼容层在任何可执行客户端脚本前生效；实际 boot roster 全部装配；鉴权、`/api/remote.mux` 握手及事件/控制/快照/跟随流可用；强制断线后恢复，不靠重试计数未增长替代帧观察。
2. **模型闭环**：目录与投影两路分别记录状态及连接代，涵盖先后到达、Provider 局部失败、RPC 全部失败与重试、菜单选择、推理强度、刷新和重连后的持久恢复；自动化用可控本地 Provider 验证真实协议/Agent 请求。实际外部模型调用另行标记未运行或按已有凭据授权执行，不能拿模拟响应冒充远程服务成功，也不使 CI 依赖付费服务。
3. **交互与取消**：消息/工具、审批、普通提问、计划确认、动态插件装配，以及交互 pending 时取消、超时、销毁/卸载；保证结果回传、监听器清理及无悬挂。按实际支持 profile/patch 的客户端清单覆盖，不能固定写死插件数量。
4. **交付与资格拒绝**：增加错浏览器版本、缺回执/必需项 skipped、兼容层遗漏/晚注入、最终 ZIP 或任一前端文件改变、回执绑定其他候选等负向控制，确认统一门禁拒绝，而不是只验证正例能运行。

专项回执至少记录：检查器/配置版本、候选 commit 与冻结输入散列、upstream pin、前端 manifest/build digest/实际文件清单、兼容层版本与 SHA-256、最终 ZIP SHA-256、解压 Host 身份、浏览器来源/完整版本/二进制 SHA-256/实际协议版本及 UA、补丁前后 API 探针、逐旅程 result/必需项执行数、realm 覆盖和日志/原始观察定位及散列。明确分列 `Chromium 108 自动化`、`现代浏览器回归`、`Win7 真机`、`实际外部模型调用`，后两项延期或未运行不能写 passed。

回执字段存在不等于资格成立：验证器须检查字段类型、精确绑定和必需范围，并配套篡改/遗漏控制。资格属于“这一份前端 + 这一版 Host 注入层 + 这一 ZIP + 这一浏览器”的组合；任何绑定输入变化都需相应复验，不能复用旧包结果。每轮使用新的拥有输出目录，保存失败材料，不覆盖旧拒绝。

### 6.8 实施节奏与当前状态

按 **完整前端复核/固定 108 基线 → Host 兼容层与定向控制 → 108 功能旅程 → 同包与统一门禁/CI 接入** 推进。日常定向运行 G1/G2 相关部分；稳定关联批次或正式 Portable 候选再执行统一发行门禁及 G3/G4。`verify_release.py` 已包含全量 Python，不在前面重复执行 `pytest tests`。CI 当前触发器和时间限制未改变，门禁接入需在实现时单独评估，不能由本报告自动视为已生效。

本次完成源码/bundle/公开资料核对和设计交接；**G1 全面审计、G2–G4 新门禁、产品兼容层、Chromium 108 运行及 Win7 真机均未完成**。`migration.py check/ready` 只检查台账有效性和依赖，不证明兼容性；不得提升已有迁移任务状态或追加上游缺陷例外。本专项待办见 [HANDOFF.md 下一步工作](../../HANDOFF.md#下一步工作chromium-108-前端复核与交付门禁)。

## 7. 迁移实施优先级和责任分界

| 优先级 | 交付项 | 验收证据 |
| --- | --- | --- |
| P0 | 完整前端 Chromium 108 复核；建立实际交付 bundle/realm/API/语法/CSS 清单 | 固定候选、逐文件散列、能力支持与适配矩阵；不可用项阻断 |
| P0 | Host 统一注入 `AbortSignal.any`、`Promise.withResolvers` 兼容层；核实所有客户端之前生效 | 最终 HTML 加载顺序、语义/清理控制、审批/提问及关键流回归 |
| P0 | 隔离 API 缺失导致的重连和剩余网络/Host 异常；兼容预检失败应可诊断 | 108 Console、Network WS 帧、Host 日志；真机材料另记 |
| P0 | 模型选择双输入（Catalog + Session Projection）诊断与恢复 | `modelCatalog` 成功/失败样本、投影状态、选择与实际模型输出 |
| P0 | 固定 108 自动运行、最终 Portable 同包检查与发布回执拒绝控制接入统一门禁/CI | G1–G4、精确 ZIP、浏览器版本/散列及缺失/篡改拒绝证据 |
| P1 | 审计并适配其他实际使用的运行时能力 | 目标版本测试、对等语义控制，未知能力不得静默放行 |
| P1 | Win7 真机认证矩阵和现场材料归档（执行仍延期） | 恢复认证时记录精确候选、系统/浏览器、原始日志和逐项结论 |
| P0 | 检查实际交付动态 Client Bundle 和启用 Worker/iframe 的独立全局作用域 | 完整 bundle/realm 清单及适配运行证据 |
| P2 | 原生目录选择器与 Host 子进程/Win7 GUI 兼容性单独治理 | 原生/browse 双通道真机测试 |

## 8. 安全及发布边界

Windows 7 和其能运行的旧版官方 Chrome 已停止常规安全更新。**“应用兼容 Win7”不等于“环境具备现代浏览器安全性”。** 建议采用本机回环监听、最小可达网络范围、有效认证、隔离可信工作区与受控浏览器配置，避免用旧浏览器访问不可信站点。不得为了修复此类 `TypeError` 而关闭防火墙或浏览器安全校验。

## 9. 本次仍未完成的验证

1. 已有用户 Console **临时** polyfill 后“部分恢复”的实测反馈，但没有完整代码、对照日志及端到端闭环；当前**不能宣称已正式修复或验收通过**。
2. 没有证据证明重复重连全部由 `AbortSignal.any` 引起；复验之后才能排除另外的 WebSocket/Host 异常。
3. 尚未实测 `session.modelCatalog()` 的 Network/Host 返回、对应 Session `modelSelection` 投影及真实模型选取是否完成；不能排除独立的 Host/Provider 目录缺陷。
4. 本次只核实 Gateway、审批和提问的直接源码与 bundle 调用，尚未完成所有动态前端 Bundle、第三方依赖、CSS 和启用 Worker/iframe 的 Chromium 108 全面复核。
5. `QIHU` 浏览器的确切产品版本、Chromium 内核真实能力与站点兼容模式应通过独立记录补充。
6. Win7 SP1、32/64 位进程、系统补丁、证书/TLS 状态未在原报告的现场描述中完整确认。
7. 仍有其他前端功能和运行状态异常，尚需搜集修复后首次异常及分模块回归结果；不得因几个错误不再出现就签收整个 Web GUI。
8. 尚未固定和运行 Chromium 108 observer，未实现 G1–G4 专项验证、回执拒绝控制或 CI/发布接入；现有现代浏览器门禁不能弥补这个交付缺口。
9. 正式 Host 兼容层及其装配/打包、语义控制尚未实现；没有新的兼容产品提交或通过专项验证的最终 ZIP。

## 10. 供后续迁移任务引用的简明约束

> **Win7 兼容性原则**：目标不仅是 Python 3.8.10 与 Win7 OS 能启动，还包括目标 Chromium 108 可运行固定上游 Web GUI。禁止根据原版一致、现代浏览器验收或 `es2022` 构建通过推断旧浏览器兼容。须复核完整交付前端，并将目标版本自动运行和同一最终 ZIP 的检查纳入发布资格；Host 在 Client 执行前统一补齐必要能力，验证功能、取消语义、资源清理和动态插件。不得修改上游业务逻辑掩盖缺口；无法维持原版产物的适配需独立决策和记录。OS/Host、浏览器能力、协议和原生 GUI 的证据分别记账；Win7 真机认证仍延期，未执行不得宣称实机认证。**模型选择另设双输入闭环**：Catalog 返回、Session 投影到达、菜单选择、重连/刷新恢复、实际 Provider 请求链；本地自动化与外部服务调用明确区分。Console 临时 polyfill 仅属诊断，不能作为发布签收。

## 11. 本次复核方法与验证范围

本次是文档核查，未修改产品、前端 bundle、CI、迁移台账或 pin。复核包括：检查上述调用链与 Host 注入顺序；逐字节比较第 3.3 节七个源码文件和三份 `lib/client.js` 与固定 `reference`；核对现有发行脚本、前端输入记录和 CI 发布链；查阅 Google 系统要求、MDN 兼容数据及 API 语义资料。三份已定位 bundle 的身份如下，供接续者复查，**不代表实际现场包身份**：

| 文件 | SHA-256 | 直接调用数 |
| --- | --- | --- |
| `packages/api/gateway/lib/client.js` | `fe28e214b4bcc7fa35236e44ed541944e16bbf1ec003fc860e4d4bb09ec218b3` | `AbortSignal.any`：4 |
| `packages/client/ui-approval/lib/client.js` | `f73e11bb8b42fff5b2ac9bfb59f07485cdf7dcaa539042ce9f77937ff853168b` | `Promise.withResolvers`：2 |
| `packages/client/ui-user-questions/lib/client.js` | `440d7e89ad01ae2452975cc449355ba8a4ab5342388b8ce88e78a833ca6ac7b7` | `Promise.withResolvers`：2 |

文档交付采用 `git diff --check`、两份文档的本地链接/锚点与源码路径检查，并运行 `.venv\Scripts\python.exe scripts/migration.py check` / `ready` 确认现有台账和依赖边界。选择这个范围是因为本次只修改报告与交接；没有执行 pytest、Chromium 108、Win7 真机、Portable 构建或完整发行门禁，也不形成新的产品兼容签收。

**复核结果**：`check` / `ready` 均退出 0；10 个指定文件与固定上游逐字节一致；3 个本地文档链接/锚点和 27 个源码链接路径有效；文档差异及新增报告的空白检查通过。这些结果只支持本次文档与源码核查结论，全面前端兼容审计和交付资格仍待执行。

---

## 参考资料与源码索引

- [Google Chrome 系统要求：Chrome 109 是最后支持 Win7 的 Chrome](https://support.google.com/chrome/a/answer/7100626)
- [MDN / AbortSignal.any](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/any_static)；[浏览器兼容数据（Chrome 116）](https://chromium.googlesource.com/external/github.com/mdn/browser-compat-data/+/refs/tags/v6.0.0/api/AbortSignal.json)
- [MDN / Promise.withResolvers](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Promise/withResolvers)；[MDN 兼容数据（Chrome 119）](https://raw.githubusercontent.com/mdn/browser-compat-data/main/javascript/builtins/Promise.json)
- [DOM Standard / AbortSignal.any 语义](https://dom.spec.whatwg.org/#dom-abortsignal-any)
- [ECMAScript / Promise.withResolvers 语义](https://tc39.es/ecma262/multipage/control-abstraction-objects.html#sec-promise.withResolvers)
- [Gateway 客户端 RemoteStream](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/api/gateway/src/client/remote-stream.ts)
- [Gateway 客户端 Remote Events](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/api/gateway/src/client/remote-events.ts)
- [Connection Controller](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/connection/src/client/connection.ts)
- [模型选择器 ModelSelect](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/ui-model-selection/src/client/ModelSelect.tsx)
- [模型目录加载 ModelCatalogDirectory](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/ui-model-selection/src/client/catalog.ts)
- [模型选择状态 ModelDirectory](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/ui-model-selection/src/client/directory.ts)
- [模型选择根服务 ModelDirectoryResolver](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/client/ui-model-selection/src/client/service.ts)
- [Session 控制流传输与订阅](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/packages/api/session-controller/src/client/transport.ts)
- [Python Session Remote 与 modelCatalog](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/api/session.py)
- [Python Host HTML 注入与 `READY_MARKUP`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/host/webserver/injections.py)
- [WebServer `render_index`](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/host/webserver/webserver.py)
- [Frontend Static 发布入口](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/host/frontend_static/frontend_static.py)
- [Vite build.target 配置](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/apps/web/vite.config.ts)
- [Python 原生目录选择器](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/dsh/host/directory_picker/native.py)
- [Browse 模式装配补丁](https://github.com/czh869452912/deepseek-harness-win7/blob/0f06bed62c823821068a100c284b90e4488edc22/examples/web-browse.patch.yml)

*说明：源码索引绑定 2026-10-08 本次复核的 `0f06bed62c823821068a100c284b90e4488edc22`，后续提交应重新核查；现场 Portable 身份尚未确认。Win7 API/Console 截图和临时 polyfill 部分恢复是原报告继承的现场反馈，本次未取得原始截图、补丁代码或完整日志。先前原生文件夹选择问题仅作为独立背景保留，不混入本报告的共同根因。*
