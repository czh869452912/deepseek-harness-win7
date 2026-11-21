# 旧会话目录升级与恢复

Canonical profile 启动、Web 热重载和 Desktop 共用默认编码保留策略。默认根目录仅有明文历史、且没有显式压缩配置时，沿用 `none`；空目录和已有压缩目录默认 `zstd`。Minimal 已显式选择 `none`，继续遵循该配置。

0.2.2 基线读取可迁移的 v0 至 v3 会话时，在内存中准备 v4。获得写句柄并恢复追加后，才发布同编码的 v4 文件，保留前代文件的原字节和 mtime。遇到更新的格式时，后端拒绝打开该会话和回退到旧代。跨进程写入由后端独占租约保护。

0.1.5 基线的 Windows 版本还会在 `.credentials.yaml.lock` 中留下一个 NUL 字节，并在工作区注册表中把已清除的 `pendingMutation` 写为 `null`。当前源码可以独占打开这种旧凭据锁后继续写入，并在读取工作区时将空标记视为已清除。有进程持有文件时仍等待释放，实际存在的工作区事务继续走恢复流程。

## 显式配置与混合目录

自定义根目录和显式 `compression` 优先，不自动猜测或改写。修改前先退出使用该目录的 CLI、Web、Desktop，备份 profile patch 和会话目录。明文旧根目录的完整配置示例：

```yaml
- id: session-persistence-jsonl
  config:
    root: C:/Users/your-name/.dsh/sessions
    compression: none
```

压缩根目录使用 `compression: zstd`。Cordis 的 config 替换整个对象，必须同时保留 root 及需要的其他字段。只读打开核对历史后，再恢复执行。

同一根目录混有 `.jsonl` 和 `.jsonl.zstd` 时，默认保护仍会拒绝启动。不要通过删除旧历史或改扩展名处理。先保留整个目录，以独立的空根目录和匹配配置恢复应用启动；分别备份并按编码整理到两个独立根目录，再用显式配置分别核对。不要在其他进程仍持有写句柄时移动历史，也不要将同一会话的前代和当前代拆开。未来格式另留备份，交给支持该格式的版本读取。

Desktop patch 位于 `$DSH_HOME/profiles/desktop/cordis.patch.yml`；Web/CLI 使用对应 profile patch，也可通过 canonical `--patch <path>` 提供临时覆盖。运行时选择默认编码不修改这些用户文件。
