# Web 设置专项验收（2026-09-30）

## 故障与修复

用户发现模型设置请求 `/api/settings/describe` 返回 HTTP 500，插件配置页同时为空。正式 Web profile 复现为 `agent-presets` 设置描述符包含不可 JSON 序列化的 `_SettingsSchema` 对象。它只提供 `to_json()`，且返回普通 JSON Schema；设置服务要求 Schemastery 的 `toJSON()` / `{uid, refs}` 格式。之前只用人工注册命名空间的 Remote 单测漏过了整个正式组合的序列化。

`ed240400` 将该命名空间改为与固定上游相同的 `Schema.object({default: Schema.string()})`。未在 HTTP 层吞掉字段或将对象转成字符串，也未修改任何前端源码或构建产物。

`tests/test_settings_remote.py` 新增正式启动、一次性 token 换 cookie、真实 HTTP describe/update、schema 反序列化与错误类型拒绝的回归。设置及预设专项 15 项通过。

## 插件停用状态的原版语义

- `reference/packages/bundle/base/cordis.patch.yml` 默认禁用宿主 `hmr`。`client-hmr` 负责浏览器模块热更新，是独立的启用项。
- `reference/packages/bundle/web-app/cordis.patch.yml` 明确禁用宿主 `tool-fs`、`tool-pwsh`、`tool-bash` 等行；工具改由所选会话预设挂载。
- `reference/packages/host/plugin-inventory/src/index.ts` 枚举 `ctx.loader.entries()`。预设直属子树不在宿主枚举里，原版 `agent-presets/src/mount.ts` 已明确记录这一点并单独审计激活情况。
- 原版配置页只呈现既有 settings namespace 又有 `settings.plugin.item` 卡片的插件。当前标准 Web 宿主显示“终端”和“Subagent”卡片；不应为凑齐插件列表而虚构设置。

`tests/test_web_settings_inventory.py` 验证实际宿主停用行、活动 `client-hmr`、标准预设挂载无 inactive rows，以及会话真实工具注册（终端、文件、搜索、skill、todo、subagent）；另在完全关闭并重新启动 Host 后检查终端超时与默认预设持久化。宿主停用行保持原版语义。

## 原版浏览器验收

在隔离的 `.web-acceptance-home`、本地模拟模型和 3081 端口完成：

1. 模型设置正常显示 DeepSeek 提供方，无 describe 500。
2. 插件配置显示终端和 Subagent；终端超时 120000 → 121000，保存、刷新读回成功，再通过“恢复默认”保存回 120000。
3. 原版表单创建不含密钥的自定义 `web-acceptance` 提供方与 `acceptance-model`。刷新后仍存在，并进入聊天模型选择器。测试地址为不可用的本机端口，仅验证目录设置，不发送模型请求。

浏览器截图和完整回归日志位于忽略目录 `.venv`；未修改用户正常 DSH_HOME 或真实凭据。以上不代表模型发现网络请求、全部提供方协议、全部设置卡片、Win7 真机或 portable 发行已完成认证。既有其他 Web 差距仍见 [核心基线记录](2026-09-29-web-usable-baseline.md)。

## 完整回归

`.venv\Scripts\python.exe -m pytest tests`：**3616 passed, 11 skipped, 1 warning**，363.64 秒，退出码 0。完整日志为 `.venv/web-settings-suite.log`。仍有 Windows Proactor 管道析构警告，以及测试 HTTP 客户端断开产生的连接中止日志；不宣称无警告通过。

`scripts/migration.py check` 通过，`ready` 无待就绪输出；未重新签发历史 parity 证据。
