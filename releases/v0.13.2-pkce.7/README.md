# v0.13.2-pkce.7：Chat 首次开户与主站角色同步

初始实现为本地交付；2026-11-02 已在现有服务器复用 Go 1.26.1 编译并部署，
版本与开关已核对。真实新用户及主站管理员登录验收仍待用户，不能用健康检查代签。
以 pkce.6 为基线，
不修改数据库结构、模型分组、价格、余额、已用额度或计费流程。

## 行为与身份边界

- 新开关 `MAIN_OAUTH_ACCOUNT_SYNC_ENABLED=true` 启用统一开户与角色同步。
  默认关闭，关闭时保留原有独立 API 登录开户、Chat 只接受已有绑定的行为。
- 每次 Chat 请求仍先核验固定主站 UserInfo、issuer、Chat audience、会话绑定和有效期。
  新能力另外要求 `preferred_username/name/email/email_verified/pl_role`；资料和角色
  不能来自请求头、用户名匹配、邮箱匹配、请求体或 ID token。
- 主站 `admin` 映射 API 管理员 `10`，`user/moderator` 映射普通用户 `1`。
  已有超级管理员 `100` 保持，不从主站角色自动产生超级管理员。
- Chat 首次请求和 API OAuth 登录复用同一个账号/绑定事务。按固定 provider 与精确
  `sub` 定位；无绑定才开户，重复访问不重复开户。原生注册开关、资料冲突、账号禁用、
  软删除、硬删除后遗留绑定及内部凭据撤销均继续限制访问。
- 新账号沿用 `QuotaForNewUser`；Chat 没有邀请上下文，邀请人固定为 `0`。
  不额外赠额，不重置已有余额、密码、分组或累计使用量。
- 已绑定账号在可信请求中同步当前资料及角色，只在值改变时更新用户字段。
  资料冲突明确失败，不合并账号、不生成替代名；已核验的降权仍可提交，
  冲突登录不会提升角色。沿用原有缓存失效入口，失败后重试仍会再次失效。

**撤权时机：**在下一次可信 Chat 请求或 API OAuth 登录时读取主站当前角色并写回。
已绑定账号的旧后台 cookie 在每次授权前读取 API 数据库当前角色，数据库同步降权后
旧 cookie 不能保留管理员权限。本版本没有主站主动推送或后台会话对主站的持续校验，
不能宣称即时或有固定上限的撤权；单纯使用旧 API 后台会话不会主动拉取主站角色。
需要立即撤销时仍应通过 API 原生管理员禁用账号或降权。

**解绑边界：**现有解绑会物理删除绑定，没有历史撤销标记。本次不改表、不伪造撤销记录。
开启自动开户后，不应把删除绑定当作长期封禁；后续可能再次开户（资料冲突时仍拒绝）。
长期禁止访问应使用账号禁用；撤销 Chat 调用使用现有内部凭据撤销入口。

## 顺序与配置

1. 先按 Chat 仓库 `docs/profile-sync-release.md` 发布主站 overlay 和 issuer：
   主站数据库当前 `role` 经受信 session-state 变为 UserInfo 的 `pl_role`。
2. Chat 有效 scope 使用 `openid profile email offline_access`，保持原生角色/分组映射关闭。
   旧会话缺 email 或新声明时，在 Chat 内重新使用平行线账号授权，无需去 API 站点开户。
3. 准备并构建本版本，保留现有 API provider ID、client、secret、回调及用户绑定。
   原生 API 登录申请 `openid profile email`。
4. 获得发布授权后，将本目录 `account-sync.overlay.yaml` 的两个开关合入原有 New API 服务。
   不覆盖其他环境、挂载、服务或已配置模型。旧版二进制不启用新开关。
5. 核对 Chat 三个模型的原生普通用户读取授权；开户和角色同步不替代模型可见权限。

## 准备源码与目标环境构建

以下命令仅为操作说明，不构成部署或服务器操作授权。源码准备不下载、不执行 Go。

```sh
python releases/v0.13.2-pkce.7/prepare-source.py \
  --base-archive dist/pkce6/new-api-v0.13.2-pkce.6-corresponding-source.tar.gz \
  --destination .build/pkce7 --with-tests
```

准备器核对 pkce.6 完整归档、增量补丁及每个生产文件的前后清单；拒绝覆盖已有目录。
`upstream.lock.json` 保留全部有序生产补丁，`verification_patch` 单独携带新增验证场景。

前端未修改。构建前复用现有 pkce.6 的原字节资产；若只有旧版 Linux 二进制，沿用：

```sh
python releases/v0.13.2-pkce.6/extract-frontend.py \
  EXACT_PKCE6_BINARY releases/v0.13.2-pkce.5/frontend-assets.json .build/pkce7/source/web/dist
cd .build/pkce7/source
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 GOEXPERIMENT=greenteagc go build -mod=readonly -buildvcs=false \
  -ldflags '-s -w -X github.com/QuantumNous/new-api/common.Version=v0.13.2-pkce.7' -o new-api .
```

沿用 Go 1.26.1、Linux amd64。没有新增 Go 或前端依赖。准备后的完整源码、生产补丁、
验证补丁、锁文件和说明应随实际发布一并保存并公开对应源码；本地未生成部署二进制。

## 验证与验收

用户要求不下载本地工具链，本机未执行 Go 编译或测试；本版已使用服务器现有工具链
完成编译，Go 验证用例仍未运行。新增场景已写入验证补丁，
目标环境如获准执行隔离测试，可在准备后的源码运行：

```sh
go test ./oauth ./controller ./middleware ./router \
  -run 'Test(MainAccount|ChatMainAccount|ChatOAuthRelay|MainProfile|SessionRevocation)' -count=1
```

测试仅使用合成身份、临时 SQLite 和受限 HTTP mock，不连接生产数据库或模型服务。
实际发布后仍须验证：

- 新用户只登录 Chat，后台只生成一个用户和绑定；零余额免费列出分组内三个允许模型。
- 主站管理员得到 API 管理员，普通用户及版主不提权；恢复超级管理员不变。
- 主站角色改变后触发可信请求/重新 OAuth 登录，确认数据库角色和旧 cookie 权限同时更新。
- 注册关闭、资料冲突、账号禁用/删除、错误 audience、过期会话和撤销凭据均不能绕过。
- 原生模型读取授权正常；不使用付费生成请求作为本次身份验收。

## 停用与恢复

保留本次之前的镜像和精确配置。停用 `MAIN_OAUTH_ACCOUNT_SYNC_ENABLED` 可停止新开户及
角色写回；已创建账号、绑定及已同步角色仍保留，不会自动逆转。需要恢复角色时由管理员
逐项处理，不能靠恢复旧数据库丢弃后续交易或审计记录。先停用此开关，再回退主站角色声明。
恢复旧 API 二进制只使用已含内部凭据保护的 pkce.6，不回退 stock/pkce.1。
