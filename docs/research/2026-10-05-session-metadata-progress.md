# 存储元数据与错误归属推进

实际固定原版的 41 个畸形 header 向量分别经过 parser/scanner 和真实 Context 提供端的 loadStored/readRaw/list/readFrom/inspect。首轮 plaintext 的 205 个公共读取结果出现 45 处差异，原始 Source/native JSON 和差异清单保存在 `.goose/out/acp-a4-work/jsonl-metadata-physical-*-v1.json`，没有把历史报告视为签收证据。

原生存储 Header 把可选 null 当成字段缺失，丢失 cwd/parentSession/seedLength 的 presence；cwd:null 因此被错误接受到 _no-cwd。非字符串 cwd 的原版路径计算只对空 length 拒绝，无 length 的 boolean/number/object 落到 --root--；原生以前过早报路径错误。冷准备的 Header 校验位于 corruption 包装之外，格式拒绝也缺少公共 name。修复在存储 Header 保留 optional presence、按原版路径行为计算、在规范冷提供端完成 Header 验证，并保留 typed name/cause。公用普通 SessionHeader 的创建默认值不变。

正式 JSONL 驱动扩至 1030 个实际观察：此前 579 个 frame/互读/冷恢复观察，加上 41 个 parser/scanner 成对结果和 41 × 2 encoding × 5 operation 的 410 个公共结果。两侧使用同一原版生成的 malformed artifact，逐字节校验读取后仍未修改；Source 文件、generated inputs、candidate 模块/资源和 isolated runtime 来源全部绑定。首轮扩大后的比较发现观察器直接读内部 store，多出原生 committedBytes bookkeeping（20 处）；这不是去掉比较字段解决。提供端补齐实际公开 loadStored 的精确 meta/events/revision/optional tornMarker 形状，观察器改为调用该公开接口；parser/scanner 仍严格比较 committedBytes。首轮失败回执不覆盖。

新的只读 formal-v2 全部 1030 观察匹配。20 项两种物理格式的 null/refusal/location/no-mutation 回归与相邻提供端测试共 71 passed，当前验收门禁要求 398 必需 lane；原版组与配对驱动数仍为十七组 1210 原样断言和 53 个。真实解压采用同一 fresh Source 驱动，拒绝缺失、重复、顺序改变、artifact 改写和来源不符；不能复用旧 579 观察签发新产品。

扩大后的 Source-bound receipt 拒绝用例与完整门禁单元验证共 570 passed（207.92 秒）；包含实际新 1030 观察及原有格式/SQLite/Session 等回执来源检查。Source 与 119 前端文件没有修改，未放宽现有判据。该部分独立提交后继续完整发行验收。

任意事件/公共 extension ABI、跨进程竞争与历史规模、B/C/D 仍开放；上次 a6cf 原版浏览器启动取消没有被这些存储修复归因。工具定向修复已提交 03652743，其新增门禁验证为 554 passed；首次运行误用未固定 Node，第二轮发现 lane 常数未同步，均保留失败日志，第三轮纠正后通过。此记录只说明开发进展，尚无新的完整签收或 accepted_upstream。
