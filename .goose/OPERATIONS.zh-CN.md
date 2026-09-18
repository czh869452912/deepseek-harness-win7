# Goose 多智能体操作指南

本文对应当前 `.goose/run-project.ps1` 和调度器实现。所有命令在仓库根目录的 PowerShell 中执行。

## 2026-09-18：主审与收敛策略

- 当前默认实现为 DeepSeek Flash，主审与仲裁均为 `custom_openai_sol / gpt-5.6-sol`，各自使用独立阶段会话；尚未配置 Astra，也未自动新增 Luna 辅助调用。
- 首次审查保持独立完整审查。修复轮只传递先前的源码证据、问题账本、裁决和变更路径；仍需核对未解决问题、未覆盖条款和受影响消费者。模型或验收范围变化时重新建立完整覆盖。
- 控制器保存稳定 finding key、原始 ID 别名、轮次和分类。重复/重开的问题进入仲裁；非收敛任务每三轮也触发仲裁。相似匹配只触发裁定，绝不会自动判定 PASS。
- 已验收任务因依赖变化重新入队时，先把保留成果与当前集成基线组合，执行只读审查及定点测试；失败后才进入 `INTEGRATION_REPAIR`。暂停保留组合候选。最终集成仍执行完整测试。
- 缓存结果绑定模型/provider、反馈、文件、提交和验收范围；缺少新绑定字段的历史缓存不会直接复用。中断会话还需提示内容一致才恢复。
- 契约失效传播继续保守处理。本次没有自动缩小现存任务库中的契约路径或重写验收要求；减少的是失效之后不必要的重新迁移。
- 新控制器需停止旧进程后再启动才生效。本次变更没有恢复 worker、发布主分支或改写现有任务库。模型质量收益仍需后续真实试点衡量，回归测试通过不能替代模型对照评估。

## 1. 先理解三个独立部分

| 部分 | 作用 | 如何启动 |
| --- | --- | --- |
| 调度器和 worker | 按依赖分配任务，迁移、审查、仲裁、串行集成 | `-Action run` 或 `-Action pilot` |
| 网页看板 | 查看状态、日志、Thinking，编辑角色模型 | `-Action console` |
| 主分支发布 | 将通过组合测试的集成结果快进到本地 master | `prepare-main` + `publish-main`；pilot 成功后自动执行 |

看板不会启动、暂停或恢复 worker；关闭浏览器也不会停止调度器。每个仓库同时只运行一个调度器，`-Jobs` 控制它内部的并行任务组数。

## 2. 环境与首次使用

需要仓库的 `.venv\Scripts\python.exe`（Python 3.8，安装项目测试依赖，包括 pytest、pytest_asyncio）、可用的 Git、Goose，以及已配置的 provider/凭据。这里的 Win7/Python 3.8 目标指被迁移的项目；Goose 自身能否运行取决于所用发行版。

```powershell
# 查看仓库是否有待保存的变更
 git status --short
# 首次克隆时初始化固定版本的 reference
 git submodule update --init --recursive
# 检查解释器与测试依赖
 .\.venv\Scripts\python.exe -c "import sys, pytest, pytest_asyncio; print(sys.version)"
# 按本机实际安装位置指定 Goose；只影响当前 PowerShell
 $env:GOOSE_EXE = Join-Path $env:USERPROFILE '.local\bin\goose.exe'
 & $env:GOOSE_EXE --version
# 首次发现任务，不调用模型执行迁移
 .\.goose\run-project.ps1 -Action init
 .\.goose\run-project.ps1 -Action status
```

也可以将 Goose 加入 PATH，或在命令上使用 `-GooseExe <实际路径>`。角色中的 provider 名必须与本机 Goose 已有配置一致；API 密钥仍由 Goose/环境变量管理。

启动前提交希望 worker 使用的源码、编排与模型配置变更。候选工作区从提交建立；主分支发布还要求输入工作区干净。已有任务继续使用原来的数据库和工作区，不要为了“重启”删除 `.goose/runs`。

## 3. 开启与观察

建议分两个 PowerShell 窗口。

**窗口 A：看板服务（常驻前台）**

```powershell
.\.goose\run-project.ps1 -Action console -Port 8766
```

浏览器打开 <http://127.0.0.1:8766/>。已有看板服务时直接访问，不要重复启动同一端口。端口被占用时可改用 `-Port 8767` 并访问对应地址。

**窗口 B：启动或恢复调度器**

```powershell
# 先串行处理，便于观察；仍会持续领取其他符合条件的任务
.\.goose\run-project.ps1 -Action run -Jobs 1
# 后续恢复无交叉任务并行时使用（两条命令择一运行）
# .\.goose\run-project.ps1 -Action run -Jobs 2
```

`run -Task ...` 不会筛选任务；只选任务使用下文的 pilot（包含自动发布）。

`run` 自动处理尚未完成的架构规划、过期进程记录、计划修复及可领取任务。`-Jobs 1` 不代表“只做一个任务”；`-Jobs 2` 也不保证始终有两个 worker，因为依赖和写入范围可能要求串行。

如脚本被执行策略拦截，可对这一次调用使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .goose/run-project.ps1 -Action run -Jobs 1
```

额外窗口可查看终端总览或单任务日志：

```powershell
.\.goose\run-project.ps1 -Action overview
.\.goose\run-project.ps1 -Action follow -Task vendor/cordis
```

`overview` 和 `follow` 都是常驻观察命令，不会执行任务。调度终端默认 `-OutputMode summary`；需要完整带任务前缀输出时用 `plain`，只通过看板观察时可用 `quiet`。多个 worker 时优先使用看板的单任务视图，工具返回和 Thinking 可展开。

## 4. 暂停、继续、重启

### 正常暂停全部 worker

在另一个 PowerShell 中执行：

```powershell
.\.goose\run-project.ps1 -Action pause
```

这条命令提交暂停请求后立即返回，不代表所有进程已经退出。等待原调度终端显示 `PAUSED: task state preserved; rerun to continue` 并返回提示符，再检查：

```powershell
.\.goose\run-project.ps1 -Action status
```

暂停会停止领取新任务，停止所属模型进程树，保留轮次、源码改动、工作区、结果和日志。清理、测试或集成收尾可能需要时间。调度终端按 Ctrl+C 也会尝试保留任务并清理子进程，但推荐独立窗口发出 `pause`。

### 恢复执行

```powershell
.\.goose\run-project.ps1 -Action run -Jobs 1
```

没有单独的 `resume` 或 `restart` action。正常重启就是“pause → 等待退出 → 再 run”。改并行数也采用这个流程；不要同时再启动一个调度器。

已完成阶段仅在代码、作用域及审查版本仍匹配时复用。被打断的原生 Goose 会话在文件、HEAD、作用域、provider 和 model 均匹配时续接；条件改变会重新执行相应阶段，保留既有文件。恢复不等于承诺完全不再调用模型。

### 异常退出或电脑重启后

先确认旧调度器已经退出，再运行 `status` 和 `run`。启动时会自动回收 owner 进程已死亡的 RUNNING / FAILED_INFRA 记录。需要单独检查回收结果时：

```powershell
# 只回收死亡 owner 的记录，不启动 worker
.\.goose\run-project.ps1 -Action recover
# 查清并解决具体失败原因后，才显式恢复某任务
.\.goose\run-project.ps1 -Action recover -Task vendor/loader
```

指定任务的 recover 会将其（以及同 owner 的关联任务）置回 READY，并清除错误字段，保留工作区和历史；它不会解决代码缺陷、依赖冲突或仲裁问题。不要反复 recover 来绕过门禁，也不要对已集成任务随意执行。活跃调度器的锁会阻止另一个控制器接管，不要手工删除锁强行并行启动。

### 只重启看板

在看板服务窗口按 Ctrl+C，再执行 `-Action console -Port 8766`，然后刷新浏览器。这不会重启 worker。仅刷新网页会重建显示窗口，不删除日志。

## 5. 单任务试点与合并发布

### 只推进一个任务组，并自动发布

```powershell
# vendor/loader 仅为任务 ID 示例，先在看板确认状态和依赖
.\.goose\run-project.ps1 -Action pilot -Task vendor/loader
```

pilot 强制单 worker，只领取所选任务在启动时所属的原子组，不自动启动外部依赖或其他 READY 任务。依赖未完成或需要仲裁时会停下供检查；运行中要求扩大原子组也不会悄悄拉入其他任务。

**pilot 成功集成后会自动创建并测试发布候选，快进本地 master，最后保持调度暂停。** 因此要在干净的 master 上使用，并提前提交要保留的配置/源码变更。它发布的是当时整个集成分支的组合结果，不保证只包含所选任务。暂停返回成功退出码不代表发布成功，应检查 PUBLISHED 和任务 INTEGRATED。

当前 PowerShell 包装器仅对 `prepare-main` 转发 `-Target`；pilot 按 master 发布，不要用 `pilot -Target ...` 期待切换目标分支。

### 批量执行后手动发布

普通 run 将通过审查和组合测试的任务加入集成分支，不自动移动 master。需要合并已有成果时：

```powershell
# 先在另一窗口请求暂停，并等待原调度器退出
.\.goose\run-project.ps1 -Action pause
.\.goose\run-project.ps1 -Action status
# 确认处于 master，提交希望保留的本地变更
 git status --short
 git branch --show-current
# 在隔离候选中组合最新 master 与集成分支，并跑完整测试
.\.goose\run-project.ps1 -Action prepare-main -Target master
# 仅在 prepare-main 成功且候选为 READY 后执行
.\.goose\run-project.ps1 -Action publish-main
```

prepare-main 不改 master；publish-main 要求当前分支就是目标分支，基线和候选 HEAD 未改变，相关工作区干净。准备后又提交了代码/配置，需重新 prepare-main。上述操作不执行远端 push，也不构建 portable 发行包。

任务集成冲突进入 INTEGRATION_REPAIR：保留组合候选和双方证据，由单一集成人调整，共享契约争议先交 judge，重审受影响部分并跑全套测试。不要让双方各自重写同一个契约。

主分支的 prepare-main 若失败，会保留 publication.json 中的候选及测试/冲突信息；它不会自动解决最终发布冲突。应交给维护者根据保留的冲突和测试证据修复合并来源，再重新 prepare-main。当前没有“接收手工修复发布候选”的 CLI；重新 prepare-main 会创建新候选，不会自动带上旧候选里的手工修改。不要强行修改状态为 READY 或跳过检查。

## 6. 模型分配与任务状态

看板右上角“模型分配”编辑统一文件 `.goose/agent-config.json`：

| 角色 | 职责 |
| --- | --- |
| architect | 架构/依赖规划、PLAN_REPAIR |
| migrator | 实现迁移，也用于组合候选 integrator |
| reviewer | 独立审查，也用于 integration_review |
| judge | 裁定共享契约、分歧和升级问题 |

保存后新启动的阶段读取新配置；正在执行的请求不会热切换。暂停后更换模型会使旧原生会话续接条件不再匹配，下一阶段调用使用新的配置。模型配置属于 Git 管理文件；发布前记得提交自己确认的修改。看板不存 API 密钥，也不增加代理服务。

| 状态 | 含义与处理 |
| --- | --- |
| READY | 等待依赖、写入预约检查，或暂停后保留；不表示正在运行 |
| RUNNING | 已被调度器领取；结合阶段、工具和活动时间判断进展 |
| PLAN_REPAIR | 计划格式/图结构有问题，修计划并保留已有实现结果 |
| NEEDS_ARBITRATION | 需要结合上游证据裁定，不宜直接反复 recover |
| NEEDS_REVALIDATION | 契约或基线变化使旧证据失效，需重验证 |
| VERIFIED | 审查完成，尚需组合测试/集成；不是已发布 |
| INTEGRATION_REPAIR | 单一集成人处理组合候选冲突或回归 |
| FAILED_INFRA | 环境、进程或协议异常；先检查错误再恢复 |
| INTEGRATED | 已进入集成分支；还需看 publication 是否 PUBLISHED |

调度器显示 WAITING 并退出，表示当前没有可领取任务但仍有未完成任务；查看阻塞原因，解决后再 run。COMPLETE 表示任务图内全部任务已集成，仍需另看主分支发布和发行包验收。

长时间没有终端文本不等于死锁。检查实际模型、最近工具、Thinking、原始日志和测试进程；心跳只说明控制器仍在观察。图中未显式授权的依赖环会阻塞，不会自动合成一个无限扩张的 worker；需要架构计划明确依赖或 atomic_group。

## 7. 日志、保留范围与常见问题

| 路径 | 内容 |
| --- | --- |
| `.goose/runs/project/state.sqlite3` | 权威任务图、状态、证据与事件 |
| `.goose/runs/project/index.html`、`status.json` | 静态状态快照；实时查看优先使用看板 |
| `.goose/runs/project/publication.json` | 发布目标、基线、候选路径和状态 |
| `.goose/runs/project/worktrees/`、`candidates/` | 任务工作区、隔离组合候选 |
| 每个任务的 `run_dir` 下 `progress.jsonl`、`status.json` | 分任务进度与最新活动 |
| 每个任务的 `run_dir` 下 `NN-phase.events.jsonl`、结果/上下文 JSON | 完整原始流、阶段结果、恢复证据 |

run_dir 可能位于某个候选工作区内部，以实际任务记录为准，不要只在 `.goose/runs` 第一层找日志。历史重试原始流会另外归档。

流式输出每 500ms 或 8KiB 合批，工具边界和结束时刷新；网页按逻辑段合并，最多显示最近 300 段，每段最近 64Ki 字符。显示裁剪不删除磁盘原始记录；“从头回放”也受显示窗口限制。原始流采用缓冲写入，正常暂停会收集尾部，强制杀进程/掉电可能丢失未刷新的缓冲。

- **看板不更新**：确认 console 服务仍在运行、端口正确，刷新网页；单独重启看板即可。
- **任务不领取**：检查 scheduler 是否 PAUSED、waiting_on、waiting_for_writer、依赖环和仲裁状态。增加 Jobs 不会解除门禁。
- **发布提示 dirty / baseline changed**：保留并检查本地修改，提交后重新 prepare-main；不要 reset 删除工作。
- **旧 portable 冒烟失败**：已有 dist 产物可能与源码版本不一致。查看具体测试日志，区分源码验证和发行包重建；不能把旧产物失败直接当作模型迁移失败。
- **切换电脑**：Git 可携带源码、计划、模型分配文件；现有 SQLite、原生会话和 worktree 元数据仍含本机路径，不能仅复制 runs 就视为可续接。跨主机 checkpoint 导入/导出和 reference 多 tag campaign 尚未实现。新电脑需配置本机环境；不要直接把已有迁移任务当成全新任务重做。

架构计划维护和底层格式说明见 [工作流参考](README.md)。日常继续任务不需要反复执行 plan；只有确实要调整依赖、所有权或验收契约时，才在调度停止后执行 `-Action plan` 或 `-Action apply -PlanFile <计划文件>`。
