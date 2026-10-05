# 规范压缩 JSONL 提供端推进

原版 JSONL 默认 compression 为 zstd；先前规范 registry 的原生提供端仍只写 plaintext，compression 参数也不改变 suffix。新 `persistence_jsonl_canonical.py`、`jsonl_store.py`、`jsonl_format.py`、`jsonl_zstd.py` 独立实现该物理边界，registry 和公共导出切换到规范默认值。历史 `persistence_jsonl.py` 仅保留明确导入的旧测试/适配接口，不作为正式 profile 的回退。产品 preset 不通过 compression:none 绕过缺失的压缩能力。

沿用已经验收、逐字节固定的私有 MSVCRT Zstandard1.5.7 DLL 和许可证。JSONL 使用无字典、未知大小的流压缩和 checksum；SQLite 使用独立的已有字典压缩格式。已知大小的一次性压缩会改变 frame header，不能替代 Node createZstdCompress。路径严格按原版 UTF16 code unit 和 ASCII 安全集合转义，包含 astral 和 lone surrogate。首次 durable append 原子发布独立 header frame 和事件 batch frame，后续只追加自己的 batch；读取忽略 packChunks 开关并保留原始 JSONL key 顺序、换行和逻辑文件名。

正式双侧驱动在固定原版上重新执行 579 个实际观察：561 个 frame/切点/checksum/全部 256 descriptor 向量、4 个 zstd/none × packed/unpacked 的精确 materialization 字节结果、4 个互读与冷准备结果、10 个原版读取原生生成 frame 的结果。双向比较完整 dev/ino/size/mtimeNs/ctimeNs revision；prepare 的 end-seed 不属于 durable prefix，也不发布 live Session。每次使用新 workspace/output，Source checkout 和输入前后哈希必须不变，原生运行来源模块/资源与 fresh Source/generated inputs 均闭合绑定；开发通过尚不代表正式签收。

受控测试覆盖 inert inspect 与 load 提交 torn-tail 修复、相反 encoding 无损拒绝、revision 改变重读、异步 I/O 取消后 worker 收尾、append fsync 失败恢复 prefix，以及 rollback 失败保留两个 cause。文件读取和写入在 owned worker 执行，取消不遗留打开的 worker。真实模型/history-tools profile 增加默认压缩选择，headless/PI 和自定义 SDK profile 验证完整压缩产物。原版 sdk-minimal bundle 显式配置 compression:none；该 bundle 及其对应测试继续检查 plaintext，未改动产品配置。首轮消费者中旧物理 suffix 断言失败，保持日志；后续按照各 profile 的实际原版配置检查产物，不改变业务断言。新增测试中错误的 registry/cleanup 方法名、旧 turn/end fixture 和门禁函数参数均在定向验证阶段纠正，初始失败日志不覆盖。

完整门禁增加 JSONL 互读/解压专项、原样 82 项 Zstd/兼容断言和必需回归，当前要求 372 lane、十七组 1210 原样断言、53 双侧驱动。原版前端 119 文件保持不变。SQLite 的 d5cc 完整失败候选、原版浏览器启动取消、缺少活动时间戳的部分字节流超时仍保留；新的通过样本不能将其归因或抹除。

提交前的定向验证包含 593 个实际测试：592 passed、1 failed；唯一失败是新断言错误地将 sdk-minimal 的显式 plaintext 配置视为默认压缩。按原版 bundle 配置纠正后，两项 SDK 定向测试均通过。原版 sdk-minimal bundle 未修改，其他 592 项已经通过的回归无需因这个测试断言变更重跑；提交后的完整冻结门禁仍须执行全部 tests。

产品候选 `865fea84e9845c196219d1ce4fe2c7ffcdb977e8` 的首次完整冻结门禁被拒绝：6801 passed、8 failed、6 既有平台 skipped、1 既有 warning；Source/配对/解压阶段未执行。精确 ZIP SHA256 为 `47fab1e4f888064b4a8d90f759a6e1609a0e00578bd44fa801830957a589330c`，输入清单 SHA256 为 `4056a305e9c49aff8e5047603bfb32be2f071f9a7f312377437b1cd73993c646`；ZIP、XML、完整日志和拒绝来源保存在 `.goose/out/session-storage-clean-865fea84/`，须进入后续证据归档。

六条 ACP 权限进程旅程的业务、取消、迟到响应、EOF 和关闭均已完成，观察器仍查找旧 plaintext suffix。观察器改为读取实际默认 `session.jsonl.zstd`，要求全部 frame 完整、checksum 解压成功，再检查原有批准审计事件。另两条 Web 启动测试未设置隔离 launch DSH_HOME，误读用户既有 plaintext 日志；规范 encoding refusal 正确阻止混用。夹具在快照捕获和启动前显式设置临时 DSH_HOME，不更改用户日志、产品默认值或 profile 参数语义。修复后 16 项定向测试通过（25.99 秒）；无新增 skip、例外、放宽时限或错误判据。该变更须独立提交并冻结新候选，不能签收或重跑 865fea84。

任意 malformed optional metadata/public plugin ABI、跨进程/多工作区/长历史和完整 B/C/D 范围继续开放。accepted_upstream 为空，Win7 真机按用户决定延期；本记录不宣称整体迁移闭环。

隔离和观察器修复后的干净候选 a6cf3dcd 完整 tests 为 6808 passed、1 failed、6 既有平台 skipped、1 既有 warning（1610.05 秒）。前述八项夹具问题已通过；唯一失败是原版浏览器 host 插件升级启动请求取消，两条原版 console error 拒绝，17 步业务仍完成。精确 ZIP SHA256 `a42207b435f87cb4c555be8b0ce445789acbd288c2cfc449a23a7bf89de0de9a`，输入 SHA256 `affb1d48d1e0ccfafab9d6680a34615ff7351928ae6101961f51dc4636cd9308`；完整失败产物保存在 `.goose/out/session-storage-clean-a6cf3dcd/`。Source/配对/解压阶段未执行。无新的存储签收，浏览器取消继续追踪，后续工具失败边界见 `2026-10-05-tools-scheduler-failure-progress.md`。

后续实际 malformed 观察揭示 45 处 optional presence、路径和 cold error 归属差异，根修复后正式 JSONL 驱动扩至 1030 观察并全部匹配；增加双 encoding/no-mutation 与 source-bound receipt 拒绝用例，当前门禁 398 必需 lane。精确范围、首轮失败和开发验证见 `2026-10-05-session-metadata-progress.md`；仍须干净提交后的完整解压/浏览器门禁，不据开发样本签收。
