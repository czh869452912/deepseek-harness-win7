# 前端原始构建记录同步（C9-CB）

协调导入前发现，旧脚本只更新完整资源清单，留下旧 `scripts/frontend-build-record.json`，后续 `prepare_reference.restore_frontend` 会拒绝恢复新原版输入。

导入器现在先核对旧记录与旧清单一致，将旧记录一同纳入已验证备份，原字节导入 Source 的 `.dsh-build/client-build-environment.json`，并在结束前确认 Source 与产品记录均未变化。冷恢复没有明确历史 carrier 时不再自动填入另一版历史归档身份。

18 项定向检查通过，包括实际 Git Source 导入、旧记录篡改不覆盖、备份原字节、新记录原字节及导入后冷恢复。生产旧树仍因此前四份已核验暂存成员不满足旧版严格正例，原有 `actual_pinned` 检查本轮未选择，协调导入后再运行。没有更换实际前端或 pin，没有重标任何历史构建。

合成 Git 目录、测试备份 ZIP、pytest 工作区、tmp 和 home 均已清理；只对自有单硬链接普通测试文件解除只读属性，没有改变共享对象。命令、XML和日志保留。详见[检查回执](../../migration/candidates/rc022/frontend-build-record-checks.json)。
