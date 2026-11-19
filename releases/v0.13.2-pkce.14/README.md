# v0.13.2-pkce.14：同房独立付费角色

从 [v0.13.2-pkce.13](../v0.13.2-pkce.13/README.md) 冻结配方增量交付。同一私密加密房可各自授权 Flux 和 Sakana。按角色独立保留邀请人、模型、限额、用量和 24 小时有效期；原授权不续期、不换付款人。同一事件可由两个角色各处理一次，每个角色内部仍防重；各角色请求按自己的授权结算。如果两角色由同一个人邀请，则共享其原生钱包余额这一硬上限。

旧 Flux 的服务、URL、令牌、请求及邀请 ID 保持兼容。受信发行方的新请求可在现有邀请、激活及模型选择接口显式传入 role_id（flux-the-cat 或 sakana）；缺省仍是 Flux。Bot 仍使用原网关 URL，服务端用各自令牌确定角色，忽略外部自报角色。Sakana 使用独立的 TAVERN_SAKANA_BOT_BEARER；缺失、无效或与 Flux、发行方令牌相同均只停用 Sakana。两角色共用现有受限渠道和 Bot 请求模型标识，实际送出的模型按各自授权决定。普通计费、订阅、Chat OAuth 及其他机器人不变。

## SQLite 前向迁移和恢复

本版仅修改两张现有角色账表。活动授权唯一键改为 (active_room_id, role_id)，邀请事件唯一键保留。调用主键改为 (room_id, event_id, role_id)，钱包崩溃恢复及 grant_id 查询索引保留。事务将所有已有角色记录归入 flux-the-cat，不改原 ID、账本金额、授权有效期、事件状态、付款记录或钱包余额；目标结构未知、存在半次迁移或 SQLite 旧调用表有额外索引/触发器时停止。源码配方冻结不证明已经在生产应用。

切换前停用新请求，排空各角色预留、留生产一致性快照和升级前镜像，确认仅在核准 SQLite 实例执行。通过升级后快照核对已有记录、索引、钱包，以及两个角色可分别授权和退款。生产可以只停用 Sakana（保留 pkce.14 和账本）；禁止把 pkce.13 连到已改结构的数据库，旧版本不识别角色，可能误选授权或重新建立旧唯一索引。仅尚未接受任何切换后业务写入的预检失败可使用原一致性快照恢复；已有真实资金操作时保留账本，用支持新结构的版本修复，不回写旧数据。

## 本地离线准备

以前版已验证 source 作为基线。前端只改对应源码链接，使用原锁定 Bun 1.4.4 构建 web/dist；使用 Go 1.26.1 和已就绪的离线模块缓存。

    python releases/v0.13.2-pkce.14/release.py prepare --base-source <verified-pkce13-source> --frontend-dir <built-pkce14-dist> --destination <new-directory>
    python releases/v0.13.2-pkce.14/release.py verify --source <new-directory>/source
    python releases/v0.13.2-pkce.14/release.py build --source <new-directory>/source --cache-dir <existing-cache> --output-dir <new-output>

本目录提供对应源码配方，不另传源码归档。构建产物为 Linux amd64 二进制与实际内嵌前端资源核验回执。运行镜像只替换 /new-api；不包含角色原卡、头像、钱包数据、凭据或配置。数据库功能验收使用本地合成 SQLite 和模拟模型，不调用生产渠道。
