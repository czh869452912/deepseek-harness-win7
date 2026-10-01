# Tool-result pruner 迁移进展

日期：2026-10-01。产品起点 `12b11466`；固定参考版本
`cd5ef8148158c3a752a658978873241fdf8e2bbc`。当前开发环境为 Windows / 原生 Python
3.8.10。本记录覆盖工具结果裁剪及其提供端、Loader、Session 消费者，不认证全部
compaction、原版 JS 脚本执行、全项目迁移或 Win7 发行。

## 实际差异与修复

原版依据为 `reference/packages/compaction/compaction-tool-result-pruner/src/`
的 `index.ts`、`config.ts`、`types.ts`，以及该包两份原样测试。

- 原有构造器会将配置字符串转换为整数，接受废弃的 snake_case 配置，且不验证
  head + marker + tail 是否超过 threshold。旧测试甚至要求将 36 字符扩展为超过
  threshold 的替换文本。现在只接受原版三个 canonical 配置键，校验整数、正负边界
  和输出预算；默认值及解析结果脱离调用者并冻结。显式 Python 构造器关键字仍作为
  到 canonical 配置的语言适配，不作为 YAML 中额外的配置键。
- 补齐原版公开的 Config Schema，包含数值类型、step、min 和 default，Provider
  wrapper 共享同一份 Schema。Loader 获取的配置及 Schema 字段与实际原版比较。
- 原有 `len` / Python 切片会将显式 UTF-16 surrogate pair 计作两个字符。现在按
  JS 字符串迭代边界处理 astral scalar、显式配对及孤立 surrogate；组合字符按
  code point 计数，仍不承诺 grapheme cluster 完整性。
- 裁剪只计算 text block，保留其他 block 的顺序与引用、text 的额外字段、跨 block
  的单一 marker，丢弃空 text block，并验证结果更小且不超过 threshold。
- 替换保留原版完整 event.data、message identity/source、tool-result 扩展字段和
  isError。返回 canonical `originalSeq`、`replacementSeq`、`callId`、`charsBefore`、
  `charsAfter` 和聚合 `charsRemoved`，移除旧的原始字符串/legacy event 回退。
- 提供端声明必须注入 `tokenMeter`；真实价格写入 `compaction/prune` 后，替换通过
  Session 的 surface replace 和 sourceEventSeqs 引用原事件。直接构造缺少 meter
  的服务也不能静默发布零价格。
- 一轮开始即捕获所有 candidate seq/event，期间新发布的结果留给下一轮。替换失败
  向调用方传播，先前成功替换保持 durable；失败前已经提交的价格记录也保留。
- Provider 的注册随所属 Fiber 撤销，缺少 meter 时 pending，提供方卸载后撤销，
  重新提供 meter 时重新激活。Cordis `has` 检查属性声明，不能用它代替读取服务
  实例来判定卸载。

真实 Session invariant 测试及双侧观察确认：没有 open turn 时，价格记录已提交，
随后 replacement 被 invariant 拒绝；surface generation 不变。TokenMeter 只在
对应 replacement 到来时消费价格，单独价格记录不会减去 tokens。重新开启 turn
后裁剪成功。这是原版已有行为，本轮不将这条保留价格记录登记为原版 bug。

## 双侧观察与验证

新门禁：

```powershell
.venv\Scripts\python.exe scripts/pruner_oracle.py --output .goose/out/pruner-final-paired.json
```

原版 runner 通过现有开发端 Vitest aliases 直接导入固定参考源码；Python runner
调用实际迁移服务、Session、TokenMeter、invariant 和 Loader。两侧共享 case recipes，
比较完整观察结果，不删除错误文字、替换字段或失败记录，也没有差异豁免。

门禁检查 reference HEAD 和 tracked 工作树状态，并记录自身 recipes / runners /
配置及 native pruner 的 SHA-256。比较仅排除真实时间戳；Unicode 输出按等价 UTF-16
wire 表示比较，保留孤立 surrogate，不以替换字符掩盖差异。

41 组观察包括 18 组配置、12 组内容、5 组 Session 和 6 组 Loader / lifecycle。
最终门禁 **41 / 41 matched**，退出码 0；报告、双侧观察及实际执行日志为
`.goose/out/pruner-final-paired.json`、`.ts.json`、`.python.json`、`.0.log`、`.1.log`。
配置覆盖 nullish defaults、整数值浮点数、负零、大整数、无限输出预算、错误类型和
废弃配置；Session 覆盖完整元数据、短结果跳过、多个替换、第二轮收敛、replay、
部分失败保留、新结果不进入本轮 snapshot，以及真实 invariant 拒绝与重试。

原版未修改的全部 compaction 测试通过：12 files / 197 tests，4.29 秒，退出码 0；
日志 `.goose/out/pruner-source.log`。其中包含 pruner 的内容、事务、invariant、真实
Loader composition 原样断言，197 项不是 197 个 Python 双侧场景。

既有 compaction 双侧门禁也通过：155 项，153 matched + 两项之前单独登记的
原版 bug 修正差异；日志 `.goose/out/pruner-compaction.json`。本轮没有发现新的
可证明原版 bug，所修复的是迁移版偏差。

最终专项：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_tool_result_pruner.py tests/test_compaction.py tests/test_compaction_invariant.py tests/test_command_compact.py -q
```

137 passed，14.10 秒，退出码 0，日志 `.goose/out/pruner-focused-final.log`。
5 个变更 / 新增 Python 文件的 Python 3.8 AST 解析及 compileall 通过。

Schema 和最后的回归断言补齐前，完整 pytest 为 4143 passed、2 skipped、1 warning，
335.06 秒，退出码 0；JUnit 4145 项，failures / errors 均为 0。历史输出保留在
`.goose/out/pruner-complete.log` / `.goose/out/pruner-complete.xml`；这份过渡验证
不替代最后版本的完整回归。最终版本执行：

```powershell
.venv\Scripts\python.exe -m pytest tests --junitxml=.goose/out/pruner-final.xml
```

**4147 passed、2 skipped、1 warning**，332.07 秒，退出码 0；JUnit 共 4149 项，
failures / errors 均为 0。日志及 JUnit 为 `.goose/out/pruner-final.log` /
`.goose/out/pruner-final.xml`。warning 是既有 Windows Proactor transport 在关闭
事件循环后的析构诊断；pytest-asyncio fixture loop scope 提示和本机 HTTP
connection-aborted 诊断保留，不宣称零警告通过。

reference tracked 工作树保持干净。migration check 通过，ready 退出码 0 且没有
就绪任务输出；git diff --check 通过。这些检查不认证全项目迁移完成。

## 后续完整目标与交付方向

交付继续遵循 [Python 插件交付评估](2026-09-30-python-plugin-distribution-assessment.md)：
固定 Python 3.8.10 Portable，Host 插件通过 profile / Loader 装配，专用 client
在开发端预构建。目录 / ZIP 的 Python 插件实验安装已有实现；创造模式持久导出、
版本升级 / 回退、锁定且带哈希的离线依赖闭包、插件 client 联合旅程，以及
GitHub Release / npm / PyPI 获取归一化仍须实施。

通用原版 JS Workflow、动态 JS Host、Inspect、其他未验收模块、实际 Web 客户端
联合验证及新的 Portable 发行仍属于完整迁移目标。当前 `migration/status.md` 的
accepted upstream 尚未建立，manifest 数和全量 pytest 不能作为全部迁移完成证明。

本轮没有新增生产依赖、QuickJS、Node Host、现代 Windows API 或浏览器源码变更，
未重建 / 发布 Portable。Win7 实机及目标浏览器验证继续保留用户暂缓状态。
