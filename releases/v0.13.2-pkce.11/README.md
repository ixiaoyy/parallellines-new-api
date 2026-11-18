# v0.13.2-pkce.11：Flux 房间钱包计费候选

**本地候选，未上线。** 同一 Flux 可在多个已授权私密加密房工作；每房只使用其邀请人确认的钱包额度，不使用订阅、其他房间付款人或发言人额度。普通成员、其他机器人、原生 API Key 和 Chat OAuth 的邀请、授权及计费保持原样。真实双房验收前保持 `TAVERN_FLUX_ENABLED=false`。

## 授权及费用边界

- Synapse 以独立服务凭据请求 `/api/tavern-flux/intents` 准备十分钟内有效的意向；授权页面 `/tavern-flux/authorize?intent_id=…` 使用现有正常 Web 登录，再核对原生 New API 账号与邀请人主站身份。现有 Chat 客户端的 OAuth 权限与原生 API Key 行为不变。
- 本人提交原生整数额度上限（`1..1000000`）后进入 `confirmed`；Synapse 确认实际 Matrix 房间、邀请人和邀请事件后才能激活唯一授权，授权最长 24 小时。已确认人不能重试出更高额度；别人不能替换仍有效的授权。
- 登录者从 `/api/tavern-flux/rooms` 只看自己的活动/已确认授权，使用列表项 `intent_id` 调用 `DELETE /api/tavern-flux/rooms/:id` 撤销。撤销或过期后不接新调用，不把在途账迁到其他付款人。
- 一次迁移添加 `tavern_flux_grants`、`tavern_flux_invocations` 及遗留预留查询索引；不改现有钱包、订阅或普通令牌表。私有事件账只存房间与事件标识、预留及实际额度，不存原卡、消息、OAuth Token 或人类模型 Key。
- `/tavern-flux/v1/chat/completions` 先校验房授权及邀请人的原生账号，用原生文本报价算保守预留。事件去重、房间上限和原付款人钱包占资在同一事务提交。仅在确认真实结算后返回回复；无效用量、模型失败或实际价高于预留，原账退回，不追加扣款，不退回普通路由、共享 Key、信任额度或违规费补扣。用量落到原付款人的原生汇总和日志。
- 当前专用渠道须填 `TAVERN_FLUX_CHANNEL_ID`，并与 `TAVERN_FLUX_MODEL_ID` 匹配。只允许付款人的原生组内已启用、单 Key、HTTPS 直连的 OpenAI 文本 Chat Completions；不使用代理、渠道覆盖、模型映射、Responses 转换、阶梯或零价配置。普通批扣开启时拒绝 Flux 新预留，既有预留仍可结算或退回。
- 启用或显式关停后，新网关主实例每分钟至多尝试退回 8 笔超过 15 分钟、确未结算的占资。只退款给原付款人并留同一事件的终态，不能重放。撤销只停止新请求；已按原授权完成预留的在途调用仍以原付款人结算，回退前必须排空或确认退款结束。

## 准备当前源码

以 `v0.13.2-pkce.10` 已冻结、全量校验通过的完整源码为基线，不走仓库根旧版本。使用 Python 3.12+，不安装、不下载、不使用生产配置：

```powershell
python releases/v0.13.2-pkce.11/release.py prepare --base-source <verified-pkce10-source> --frontend-dir <built-pkce11-dist> --destination <new-directory>
python releases/v0.13.2-pkce.11/release.py verify --source <new-directory>/source
python releases/v0.13.2-pkce.11/release.py build --source <new-directory>/source --cache-dir <existing-cache> --output-dir <new-output>
```

配方只接受本版新构建的 `web/dist`，并核对冻结的完整源码和实际 Linux 二进制的内嵌前端文件。使用现有 Go 1.26.1 和已就绪的离线模块缓存，不重新下载依赖。镜像只封装本次编译产物；生产交付时需另绑准确的 Git 提交、对应源码归档及不可变镜像，不用历史产物冒充本版。

本地 Go 回归已验证实际 HTTP 网关及隔离 SQLite 钱包：两个房间分别由不同人支付；A 房撤销后一律拒绝新请求，B 房不受影响，达到上限后不再请求模拟模型；同房其他成员余额不变。覆盖重复事件、超预留退款、同一钱包并发和崩溃占资回退。Linux amd64 网关编译通过，已检查实际二进制内嵌的 200 个公开前端资源。上述检查未使用真实账号、模型 Key 或生产服务。

## 上线与恢复门槛

完整授权、两个实际加密房经真实 Matrix 和 Bot 镜像进入该路由，以及目标价目、退款和撤销，须在明确获准的隔离环境验收。离线 SQLite 与合成上游回复能验证实扣账务，不能证明真实 Matrix 加密、上游计量、生产缓存、渠道支出或服务部署。

2026-11-18 已补做本机 Docker 加密双房联调：真实 Synapse、锁定 Baibot Linux 镜像、本版网关及模拟模型。两房分别激活，普通成员在两房发出实际加密 `@`；A 邀请人钱包由 1000 到 990，B 邀请人由 1000 到 980，发言者仍为 1000。两房上限均为 20；A 房撤销后不再调用模型，B 到上限后的加密请求被拒绝，最终 3 笔结算、3 次 HTTPS 模拟模型请求、没有未结算预留。证据在 `D:\work\pingx\.tmp\flux-e2e-ffa247-20261118\accepted-wallet-evidence.json`。实际生产渠道、缓存、额度和上线回退仍未执行验证。

发布前先留生产数据库一致性备份、New API 旧镜像与配置、Synapse 原邀请模块及 Flux 私有设备状态。仅添加该 Bot 的模块、授权 UI 与结算路由，不重建共享网关或变更其他机器人。停用时先停止 Flux、设 `TAVERN_FLUX_ENABLED=false` 禁新请求；保留新网关把旧预留排空或退回，独立检查真实钱包与账本后才切回旧镜像。不删除账本、不用旧数据库覆盖后来真实流水。旧生产脚本锁定历史镜像与源码，不直接执行。
