# NewAPI 统一登录真实链路验收记录

## 当前状态与职责

用户最新决定不再处理本地 Docker 或补额外本地测试，直接在服务器运行和验收。Main、issuer、Chat、HTTPS 代理和发布由根任务统一管理；此仓交付已验证 NewAPI 候选与正式发布材料，不自行连接服务器。此记录当前尚未声称真实跨站链路通过；正式交接见 [pkce.10 发布说明](../releases/v0.13.2-pkce.10/DEPLOYMENT.md)。

已存在的本地 Go、11 条网络拦截浏览器、5 条 helper、Linux 构建和资产闭包证据继续有效，但不作为本轮真实 issuer 验收结论。不得用请求桩代替真实 Main/issuer，不调用模型，不使用生产数据。

## 固定来源与实际候选（原隔离计划，已停止执行）

- 候选为 `releases/v0.13.2-pkce.10/`，完整展开源码使用本版 `source-files.json`。
- 实际 Linux 二进制已有 `.build/unified-web-login-pkce10-20261114/ready-output/new-api-linux-amd64`，镜像底座沿本版锁中的不可变 `runtime_base`，由共享 runtime owner 检查可用性。
- 保持 `https://pingxingxian.space/auth/oidc`、`parallellines-newapi` 和回调 `https://api.pingxingxian.space/oauth/pingxingxian`，不为测试修改业务常量或改成 localhost issuer。
- 隔离 Docker 网络中，HTTPS 代理的网络别名覆盖固定 Main/API/Chat 域名，容器内固定 443 直接到共享代理；代理转发到真实候选服务。NewAPI 以只读本地 CA 文件设置进程级 `SSL_CERT_FILE`，正常验证证书链和域名，不设置 TLS skip、不改系统信任库。
- 显式清空测试容器中的外部 HTTP/HTTPS/ALL 代理，确保固定域名只经隔离网络别名到本地代理；只有必要测试网络，不连接真实提供方。
- NewAPI 容器宿主端口只发布到 `127.0.0.1`。公开 HTTPS 入口必须拒绝整个恢复路径树；恢复从独立本机私有入口验收。

## 已完成的隔离测试库准备（历史，不再追加执行）

使用 `scripts/seed-unified-web-test-db.go`。它只依赖候选现有模块、默认 preview，不安装依赖。测试 owner 先创建全新指定目录和 `.pl-unified-test-root` 标记，标记内容为 `parallellines-unified-local-test`，并提供本次随机合成 Root 密码文件和与 issuer 注册一致的 NewAPI client secret 文件；不得填生产凭据。

从已准备候选 `source` 目录运行：

```powershell
go run <repo>/scripts/seed-unified-web-test-db.go --test-root <absolute-marked-test-root>
go run <repo>/scripts/seed-unified-web-test-db.go --test-root <absolute-marked-test-root> --root-password-file <synthetic-password-file> --client-secret-file <synthetic-newapi-rp-secret-file> --execute
```

工具排他创建 `data/new-api.db`，已有数据库/MFA 文件一律拒绝。只种原生 Root UID 1、实际 MFA、固定 provider 1、初始化状态和必要原生选项；Main A/B 必须经真实 OIDC 首次开户，不预置绑定。随机 MFA/备用码仅写入测试目录 `data/root-recovery-mfa.json`，不回显。失败产物保留，不自动清理。此工具已用独立新 SQLite 完成 preview/execute 检查，不证明跨站登录。

共享 runtime 配置 NewAPI：`SQLITE_PATH=/data/new-api.db`，无其他 SQL/Redis DSN；`MAIN_UNIFIED_WEB_LOGIN_ENABLED=true`、`CUSTOM_OAUTH_PKCE_PROVIDERS=pingxingxian`、`MAIN_OAUTH_ACCOUNT_SYNC_ENABLED=true`；恢复测试显式 `MAIN_WEB_ROOT_RECOVERY_ENABLED=true`、`MAIN_WEB_ROOT_RECOVERY_USER_IDS=1`。使用随机本次 session/crypto secret，保留零渠道、零模型调用。真实环境开关必须另核，不能拿测试配置覆盖正式站。

## 必须取得的真实证据

1. Main A 登录后进入 API，实际 PKCE、token、UserInfo、Main binding 校验完成；`/api/user/self` 属于 A。
2. 同一浏览器在 Main、圈子、Chat、API 之间切换不再输凭据；游客公开页可看，受限操作仍登录门禁。
3. Main A 切 B，旧 API 私有状态清除且 B 对应不同原生 ID；回到 A 仍是原 ID，角色/余额不串号。
4. API 发起真实全站同浏览器退出；Main、Chat、圈子及 API 不再授权该浏览器。另一个独立浏览器会话不被踢出。
5. 普通 `/api/user/login` 对真实 Root 密码也拒绝；私有 `/root-recovery` 的密码和 MFA 成功；同路径公开 HTTPS/变体拒绝。
6. 正常发布重启后丢失证明的重接与旧绑定拒绝符合合同；issuer 故障的 fail-closed 继续使用既有定向证据，不为补验主动中断生产服务或造故障。

真实证据的运行目录、用例结果和未完成项由本轮 runtime 回执补充。发布仍需根任务统一核正式环境前置版本、当前镜像/二进制/数据挂载、恢复版本和公开代理的实际生效状态。

## 本轮进度

2026-11-15，共享测试 owner 指定 `unified-acceptance-20261115` 隔离目录后，seed 已完成 preview 和显式 execute，仅写该目录 `data/`。只读核对得到 Root UID 1、角色 100、1 个用户、provider 1、1 条初始化状态、MFA 开启和 4 条未使用备用码。未手工读取或回显任何合成凭据值。Main A/B 尚待真实 OIDC 自动开户。

本轮尚未启动本地 NewAPI 或共享 issuer。后续用户已明确停止本地 Docker 修复及额外本地验证；不会继续探测 daemon，也未把种库结果当作跨站验收。实际服务器版本、运行及结果仍由根任务取得后补充。
