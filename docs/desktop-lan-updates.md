# 内网 Desktop 更新通道

Desktop 使用本发行版的独立完整安装器通道。x86 和 x64 分别提供 HTTPS feed；客户端验证 Ed25519 签名、版本、架构、有效期、安装器字节数和 SHA-256，然后停止 Host，交给 Windows 管理员安装向导安装并重启。`Standard` 安装器用于更新，AIO 不是更新载体。

## 准备配置

在仓库外保存长期 Ed25519 私钥；只将对应公钥嵌入发行包。为内网服务器配置证书链和正确的 DNS/SAN。客户端配置如下，PEM 字段须替换成真实证书/公钥内容，并通过 JSON 序列化保留换行：

```json
{
  "schemaVersion": 1,
  "channel": "win7-electron22",
  "manifestUrl": "https://updates.example.internal/dsh/x64/feed.json",
  "publicKey": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n",
  "caCertificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
}
```

`caCertificate` 是可选的 PEM CA 证书链，最大 8192 字节。公共受信任 CA 可省略该字段。显式 CA 只用于更新器的 feed、重定向和安装器 HTTPS 请求；TLS 主机名验证继续启用。实际 Electron22 测试表明不能将 `NODE_EXTRA_CA_CERTS` 当作本发行版的可靠部署前提，因此私有 CA 使用该配置字段。CA 证书与 Ed25519 发布签名公钥承担不同职责。

配置通过 `scripts/build_desktop.py --update-config <json>` 嵌入。未提供配置的包保持更新关闭。现有包不自动接收新地址或密钥；首次启用通道、换 CA 或换签名公钥，先通过独立安装包发布新配置。

## 发布顺序

1. 从已验收候选取得精确的 Standard 安装器，保留字节数和 SHA。安装器名称必须是 `dsh-desktop-standard-setup-v<VERSION>-<x86|x64>.exe`。
2. 先把安装器发布到 HTTPS 地址，再运行 `node scripts/sign_desktop_update.cjs --installer <exe> --version <version> --architecture <x86|x64> --artifact-url <https-exe-url> --manifest-url <https-feed-url> --private-key <external-pem> --output <new-feed-json>`。
3. 原子替换对应架构的 feed。服务器不要对响应施加内容编码；允许的 HTTPS 重定向也必须提供可信证书。签名有效期最多 90 天，服务器和客户端需要正确时钟。
4. 在一台普通用户客户端检查更新，核对下载 SHA，完成 UAC 和安装向导，确认重启指向安装根目录下的 `app`。再检查会话、设置和快捷方式，确认旧程序文件已清理。

更新器只接受更高的产品版本。同版本的修复重打包使用独立安装器覆盖安装。下一次正式更新必须同时推进安装器内版本和签名 feed 版本。使用旧版内网更新器首次升级到固定安装目录时，安装完成后从开始菜单启动一次，因为旧版更新器只接受 `versions` 目录下的自动重启路径。

## 部署前验证

本机演练入口：

```powershell
node scripts/verify_desktop_update_feed.cjs --installer <actual-standard-exe> --electron <matching-electron22-exe> --output <fresh-owned-directory>
```

该观察器启动独立 HTTPS 服务和真实 Electron22/Node16 客户端，验证未受信任证书拒绝、显式私有 CA、签名、真实安装器下载/散列，以及实际 PowerShell 辅助进程对改动内容的拒绝。临时签名密钥仅在内存中生成，测试证书来自仓库测试夹具。成功下载的安装器保留在本次输出中，可交给管理员生命周期验证；部署包继续绑定原始安装器身份。

这项本机演练不发布内网服务，也不安装证书。用户提供内网地址和长期密钥后，实际部署还需验证 DNS、证书链/主机名、代理、防火墙、普通用户权限、过期/错误架构/损坏下载、安装失败后诊断和重试，以及交互式管理员安装与重启。Windows7 真机验证按当前决定延期。
