# 规范压缩 JSONL 提供端推进

原版 JSONL 默认 compression 为 zstd；先前规范 registry 的原生提供端仍只写 plaintext，compression 参数也不改变 suffix。新 `persistence_jsonl_canonical.py`、`jsonl_store.py`、`jsonl_format.py`、`jsonl_zstd.py` 独立实现该物理边界，registry 和公共导出切换到规范默认值。历史 `persistence_jsonl.py` 仅保留明确导入的旧测试/适配接口，不作为正式 profile 的回退。产品 preset 不通过 compression:none 绕过缺失的压缩能力。

沿用已经验收、逐字节固定的私有 MSVCRT Zstandard1.5.7 DLL 和许可证。JSONL 使用无字典、未知大小的流压缩和 checksum；SQLite 使用独立的已有字典压缩格式。已知大小的一次性压缩会改变 frame header，不能替代 Node createZstdCompress。路径严格按原版 UTF16 code unit 和 ASCII 安全集合转义，包含 astral 和 lone surrogate。首次 durable append 原子发布独立 header frame 和事件 batch frame，后续只追加自己的 batch；读取忽略 packChunks 开关并保留原始 JSONL key 顺序、换行和逻辑文件名。

正式双侧驱动在固定原版上重新执行 579 个实际观察：561 个 frame/切点/checksum/全部 256 descriptor 向量、4 个 zstd/none × packed/unpacked 的精确 materialization 字节结果、4 个互读与冷准备结果、10 个原版读取原生生成 frame 的结果。双向比较完整 dev/ino/size/mtimeNs/ctimeNs revision；prepare 的 end-seed 不属于 durable prefix，也不发布 live Session。每次使用新 workspace/output，Source checkout 和输入前后哈希必须不变，原生运行来源模块/资源与 fresh Source/generated inputs 均闭合绑定；开发通过尚不代表正式签收。

受控测试覆盖 inert inspect 与 load 提交 torn-tail 修复、相反 encoding 无损拒绝、revision 改变重读、异步 I/O 取消后 worker 收尾、append fsync 失败恢复 prefix，以及 rollback 失败保留两个 cause。文件读取和写入在 owned worker 执行，取消不遗留打开的 worker。真实模型/history-tools profile 增加默认压缩选择，headless/PI 和自定义 SDK profile 验证完整压缩产物。原版 sdk-minimal bundle 显式配置 compression:none；该 bundle 及其对应测试继续检查 plaintext，未改动产品配置。首轮消费者中旧物理 suffix 断言失败，保持日志；后续按照各 profile 的实际原版配置检查产物，不改变业务断言。新增测试中错误的 registry/cleanup 方法名、旧 turn/end fixture 和门禁函数参数均在定向验证阶段纠正，初始失败日志不覆盖。

完整门禁增加 JSONL 互读/解压专项、原样 82 项 Zstd/兼容断言和必需回归，当前要求 372 lane、十七组 1210 原样断言、53 双侧驱动。原版前端 119 文件保持不变。SQLite 的 d5cc 完整失败候选、原版浏览器启动取消、缺少活动时间戳的部分字节流超时仍保留；新的通过样本不能将其归因或抹除。

提交前的定向验证包含 593 个实际测试：592 passed、1 failed；唯一失败是新断言错误地将 sdk-minimal 的显式 plaintext 配置视为默认压缩。按原版 bundle 配置纠正后，两项 SDK 定向测试均通过。原版 sdk-minimal bundle 未修改，其他 592 项已经通过的回归无需因这个测试断言变更重跑；提交后的完整冻结门禁仍须执行全部 tests。

任意 malformed optional metadata/public plugin ABI、跨进程/多工作区/长历史和完整 B/C/D 范围继续开放。accepted_upstream 为空，Win7 真机按用户决定延期；本记录不宣称整体迁移闭环。
