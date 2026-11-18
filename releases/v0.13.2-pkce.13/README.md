# v0.13.2-pkce.13：Flux 房间模型选择与网关错误诊断

基线是 [v0.13.2-pkce.12](../v0.13.2-pkce.12/README.md)。本版本目录提供对应公开源码与锁定配方，不另外打包完整源码。模型选择界面需与同次 Synapse 和 Element 版本配合。冻结配方不代表已部署。

- 新的 issuer 接口为 POST /api/tavern-flux/intents/model-options 和 POST /api/tavern-flux/intents/set-model。两个接口均核对房间、邀请人 Matrix 身份和主站主体；活动房仅原授权付款人可看、改模型。修改额外要求 model_id 和 expected_model_id，一次比较旧值并确认该房仍活动、同一账号付款。
- 固定候选为 gpt-6-luna、gpt-6.1-terra、gpt-6.1-sol，还须在已配置的专用渠道、付款人当前原生用户组可用，并有可核验的纯文本定价。当前模型失去资格时不会擅自替换；模型选择不改原付款人、额度上限、累计费用、有效期或撤销条件。
- POST /api/tavern-flux/intents/invite 可以指定 model_id。旧客户端缺省时仍使用已配置默认；匹配的活动邀请重试保留最新选择。旧版 Bot 仍发送配置的专用路由标识作为模型字段，网关仅在这条专用入口把它换成当前房授权的有效模型。
- 切换前已预留的调用照原报价、模型和付款人结算；报价后尚未预留的旧模型调用遇切换时拒绝，不留事件记录、不扣费。无新迁移，普通计费和其他机器人保持原样。
- 502 仍以原错误代码表示失败；响应和日志还记录实际收到的供应商 HTTP 状态（未收到时响应不返回该字段）和调用毫秒数。不记录供应商正文、聊天、密钥，也不放宽现有响应和用量核验。

## 本地离线准备与构建

用 pkce.12 配方生成的已验证 source 作为基线。局部补丁顺序见本版本 upstream.lock.json。前端仍用锁定的 Bun 1.4.4；只更新对应源链接，用本次源执行 bun run build 后把 web/dist 提供给配方。Go 构建用 Go 1.26.1 和已经就绪的模块缓存。

    python releases/v0.13.2-pkce.13/release.py prepare --base-source <verified-pkce12-source> --frontend-dir <built-pkce13-dist> --destination <new-directory>
    python releases/v0.13.2-pkce.13/release.py verify --source <new-directory>/source
    python releases/v0.13.2-pkce.13/release.py build --source <new-directory>/source --cache-dir <existing-cache> --output-dir <new-output>

产物为 Linux amd64 二进制和核对实际内嵌资源的回执。运行镜像只替换 /new-api，不封装源码目录、私有角色素材、配置、凭据和数据库。

## 回退

先停 Flux 新调用和模型设置，结清原有预留或等旧预留恢复处理结束；保留 pkce.13 的镜像和账本。pkce.12 仍能结算同一钱包账，但只支持默认模型；留有非默认模型的活动授权在 pkce.12 上不会继续调用。不要为了恢复修改既有授权或回滚钱包数据。可能需要同步还原 Synapse 与 Element 的上版入口。
