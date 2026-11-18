# v0.13.2-pkce.12：Flux 房间一键邀请

基线是 [v0.13.2-pkce.11](../v0.13.2-pkce.11/README.md)。本版本仓是对应公开源码与锁定配方，不另外打包完整源码。需与同版 Synapse 邀请入口及 Element 界面配合。冻结配方不证明已部署。

- 受信 Synapse 以独立 issuer 凭据调用 POST /api/tavern-flux/intents/invite。请求包含 room_id、inviter_mxid、subject、room_label、32 位小写十六进制 request_id，以及必须显式提供的整数 limit_usd_micros。响应只包含 intent_id 和 confirmed 或 active 状态；新 intent ID 对调用方不透明。
- 首次授权绑定邀请人的现有已启用 New API 钱包。未绑定或账号停用返回 403 flux_wallet_unavailable，不自动建账，不要求打开 New API 网页。未通过服务鉴权返回 401。状态或现有房授权冲突返回 409，不换付款人、不续期、不覆盖额度。
- 新授权中显式 0 表示房间未设总费用上限；钱包余额和每笔原生用量上限仍是硬限制。正数按当前原生额度换算，不允许向下取整后为 0 或超出原 1000000 原生额度。匹配的同请求重试返回原授权；设定不同的原生上限须新请求，仍有效的房授权不会被替换。
- Synapse 仍须验证真正的同房邀请，网关才激活 24 小时有效授权。邀人以外的发言人或房成员不扣费；撤销拒绝新调用，在途预留原账可结算或退回。现有 New API 网页确认仍须正额度；普通成员、其他机器人、常规 API、Chat OAuth 和订阅行为不变。本版没有新迁移。

## 本地离线准备与构建

用 pkce.11 配方生成的已验证 source 作为基线。局部补丁顺序见本版本 upstream.lock.json。前端使用基线锁定的 Bun 1.4.4 依赖，只改变对应源代码入口的版本链接；用本次源执行 bun run build 后把 web/dist 输入本配方。Go 构建用 Go 1.26.1 和已经就绪的模块缓存。

    python releases/v0.13.2-pkce.12/release.py prepare --base-source <verified-pkce11-source> --frontend-dir <built-pkce12-dist> --destination <new-directory>
    python releases/v0.13.2-pkce.12/release.py verify --source <new-directory>/source
    python releases/v0.13.2-pkce.12/release.py build --source <new-directory>/source --cache-dir <existing-cache> --output-dir <new-output>

产物是 Linux amd64 二进制和包含实际内嵌公开资源核验的回执。运行镜像只替换经核验的 /new-api，沿用原镜像基线；源码、原角色卡、头像、配置、凭据、钱包数据不装入运行镜像。

## 回退

先停止 Flux 新请求和新邀请。让 pkce.12 网关结清全部在途预留，或等旧预留恢复处理完成，零上限记录无待结算时方可回到 pkce.11。旧版无法处理新版授权 ID 的查询和撤销，且不会继续消费新版零上限授权；保留 pkce.12 镜像、原生钱包和原账本以便恢复管理，不改写授权、不回退数据库或覆盖真实流水。其他机器人和普通业务不需停用。
