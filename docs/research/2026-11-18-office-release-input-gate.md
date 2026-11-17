# Office 离线输入进入统一门禁（C9-BY）

目标仍为 `38a6a5c965aa99ab525161efb7cc5cf1fe62fced`。本批补齐实际发行消费者，不改变此前原版转换观察或生产 pin。

`verify_release.py --office-runtime <root>` 在构建前核验并冻结实际 x64 离线目录的全部二进制与许可证，以显式参数传给 Portable 构建器。门禁结束前再次检查同一目录，防止资格运行期间输入改变。默认仍支持构建专用 `DSH_OFFICE_RUNTIME_INPUT_ROOT`。

`verify_portable.py` 从实际解压目录核验受批准的 Office manifest 和每个资源，并要求包内 provenance 与实际输入一致。统一门禁同时要求解压回执提供这份完整清单；缺失、篡改或不同清单不能通过。新增三个关键回归身份进入必需收集清单。

验证选择为运行时打包、实际资源/来源拒绝、CLI 输入传递与统一回执拒绝，覆盖提供端和直接消费者。最终 16 项通过，3.35 秒；实际保留的双架构原始输入另行逐资源核验通过，x64 94 项、x86 96 项。没有构建新的完整 Portable，也没有运行完整发行资格。

初次扩展运行包含旧完整回执正例，结果 11 passed / 6 failed：共享 `javascript_errors_runtime_fixture` 在构造回执时报告 `JavaScript errors actual import closure differs`，尚未进入 Office 校验。该旧探针需在下一批协调门禁消费者时复核，失败日志/XML保留；最终定向结果不冒充这个正例或完整门禁通过。

两个运行的自有 pytest 工作区、临时目录和隔离 home 已移除，共 111,285 字节。命令、XML和失败日志保留；既有双架构离线输入继续由 C9 持有，统一发行验收结束后清理。详见[检查回执](../../migration/candidates/rc022/office-release-gate-checks.json)。
