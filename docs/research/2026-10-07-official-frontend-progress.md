# 原版完整前端构建、设置 Schema 与过程副本维护

实际 `/api/settings/describe` 返回 HTTP500，完整浏览器响应记录为 `handler failure: JSON data must have string keys`。此前原生 Schema.toJSON 使用整数 refs 表键，普通 json.dumps 隐式转换掩盖了提供端类型差异；严格 Unicode JSON 载体暴露该问题。现在仅公共 refs 表键按原版 JavaScript 对象改为字符串，uid 和节点关系仍是整数，不放宽协议编码器。真实 canonical Web 所有已装载设置命名空间经过认证 HTTP，原始 Controller 返回值也直接通过严格编码及 Schema 重建检查。旧原生专属整数索引测试改为实际公开字符串键。

另外发现已有前端构建未使用原版 official 环境。保持固定 Source cd5ef8148158c3a752a658978873241fdf8e2bbc 的全部跟踪文件不变，执行原版 `pnpm run build:official`，核验其完整构建环境记录，再导入 119 个 shell 和 99 个 client 文件。218 文件组合摘要为 `db1e666fe85de8d1781e4f778ea25ad4a7ba4cf8f6dcdb4d635954411d097ab2`。未修改 TSX、CSS 或浏览器业务代码。导入器先保存旧构建的完整 ZIP，逐文件原子替换解除旧硬链接，只删除已核验的过时 shell 文件；这不是整个目录事务。客户端加入 -text 属性，Windows checkout 不再改写被签收的客户端字节。

前检和真实解压均检查完整 shell/client 集合、构建环境及摘要，拒绝遗漏、修改、额外文件、重复行或错误构建环境。正式发布收据另外绑定冻结 frontend 凭据、两组文件数量和完整摘要。320 项实际 Schema/设置/协议/Permission/维护消费者通过；另一次 87 项前检和维护测试、53 项必需/解压正例与拒绝控制、4 项原版浏览器生命周期测试通过，覆盖重叠，不累计为总数。新鲜 Permission 55 项完整 Source/Root 观察匹配。全量已收集 10007 项，新干净完整冻结尚未签收。

新鲜 Source 与 Root 的 minimal、standard、cordis 六条原版 Edge 浏览器旅程均完成 fresh/cold 两阶段。实际工具执行后进入下一模型请求，standard/cordis 完成问答与审批，三者完成取消、物理关闭和冷恢复；两个品牌通知与 provider 延后也通过真实控件。各报告保留全部捕获值、请求、事件和受信任点击。该功能资格不宣称全部 wire DTO 逐字段等价，也没有独立便携解释器的这六条旅程。minimal 原始注册顺序差异仍在报告中；此前三预设实际模型组装会排序且已完整匹配，不能以原始顺序推定模型请求差异。

已结束的预检副本清理扩展到精确 packages/*/*/lib/client.js 和 map；原件与复制件均须对应冻结散列，变更件和未知文件保留。十四用例旧记录与十八用例新记录分别要求完整、唯一且无失败/跳过的 XML；未完成或活跃执行不能清理。pytest 单项收尾、完整门禁与维护 CLI 共用规则。新增真实客户端副本控制证明改变原件或复制件不能越过双散列条件。维护本轮没有额外合格文件，过期清单继续按既有规则自动保留最新两份，无须再次授权。

318 文件归档 `migration/evidence/artifacts/OFFICIAL-FRONTEND-QUALIFICATION-20261007-8D129C7D.zip`，SHA256 `b2ef057fe8308932708b76b1ef47576bda9b8ba27c9585a0886b6a1002d75abc`。包含精确旧/新构建、原始 HTTP500 与通知失败、完整成功旅程、观察器启动缺少参数的拒绝、测试 XML/日志、完整前端凭据与提供端字节。立即持久化后关闭的 checkpoint 诊断也保留：同场景原版部分 cache 文件同样没有写出，不引入“所有 cache 必须在立即关闭前写完”的更强合同或额外缺陷豁免。真实 durable log/恢复及关闭竞争仍须正式范围验证。

下一步执行正常预算的干净完整门禁、全部配对/原样 Source/真实解压/原版浏览器；继续七个父范围的正式契约和剩余实际组合。最新完整签收仍是 83026446 的 65 个有界合同，036 和 056—064 未因此自动完成。Win7 与目标浏览器认证保持用户延期。
