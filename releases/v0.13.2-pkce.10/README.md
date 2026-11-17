# v0.13.2-pkce.10：主站统一 Web 登录候选

构建锁冻结的准备阶段状态为 `prepared-candidate-unpublished`。原统一登录 prerelease 的二进制和 Git 摘要属于历史交付；本轮多语言部署交付新构建、准确新提交及完整对应源码归档，不改应用版本和准备状态。此文不证明正式站已激活或真实登录验收已完成。

## 行为与兼容

- `MAIN_UNIFIED_WEB_LOGIN_ENABLED=false` 默认保持 pkce.9 行为。开启后，公开首页、价格与说明仍可匿名浏览；公开登录、注册、找回和其他凭据入口收敛到 Main `/auth`。普通 `/api/user/login` 对 Root 也拒绝密码。
- 沿用原 Main OIDC 客户端、S256 PKCE 与 `sub` 绑定。Main 已登录时自动走原授权流程，不再输入凭据。换号先清私有缓存；Main 不可用时不伪退出。
- 新 Main 证明只用随机浏览器句柄引用；绑定、主体和有效期保存在最多 10000 项的进程内存。保留原生 session 的 ID/角色兼容字段，不在 cookie 放 token、RP 密钥或 Main binding/sub/expiry。重启丢失证明后经 Main 重接，不放行旧本地 cookie。仍只允许单实例。
- 私有 Web 请求实时核对原生 provider/sub 绑定和发行方存活，不缓存正向结果。失效拒绝授权；权威故障返回 503，不伪装游客。普通 API key、Chat relay、原生 ID、角色同步、额度/余额、计费和内部凭据隔离均保留。
- 退出先向发行方换一次性 Main 同浏览器退出票据；失败不声称已经跨站退出。重接只清当前 RP，不退出 Main 或其他设备。FableSpace 不在本次范围。

## 配置与前置合同

样例见 `unified-web-login.env.example`。只变更受控服务配置，不覆盖真实密钥、数据库或既有免费模型/计费开关。

1. Main 与 issuer 先启用统一浏览器合同；Main `/auth/chat` 产生新版绑定。旧 `unified_browser:false` 不能升格。
2. 复用原 custom provider ID 1、slug `pingxingxian`、client `parallellines-newapi` 及原受信字段/端点。Basic 请求使用该 RP 原凭据，不用 Chat bridge secret。
3. UserInfo 明确给出 `pl_binding`、整数 `pl_auth_exp`、布尔 `pl_unified_browser:true`。Basic `POST /auth/oidc/main-session-state` 接收 `{binding_id,subject}`；有效返回 `active:true,sub,binding_id,auth_expires_at,unified_browser:true`，失效 200 false，权威故障 503。
4. Basic `POST /auth/oidc/unified-logout-ticket` 同参数，返回最多 60 秒有效的 Main `/auth/unified/logout?ticket=...`，回跳固定 NewAPI origin 根路径。新增调用连接 2 秒、响应头 3 秒、总 5 秒、响应 16KiB 上限；不重试、不跟重定向。
5. Main `/auth/unified/state?client=newapi&request_id=<32lowerhex>` 只向精确 NewAPI origin 发状态；RP 检查 origin、iframe window、nonce、版本、类型和 32..128 位 URL-safe 字符串 `auth_epoch`。Main 代理须允许这个指定 iframe。

## 私有 Root 恢复

默认关闭。必须显式 `MAIN_WEB_ROOT_RECOVERY_ENABLED=true`，且 `MAIN_WEB_ROOT_RECOVERY_USER_IDS` 是最多 16 个正 UID 的白名单；数据库当前角色必须确为 Root。沿用原密码与 MFA/备用码；待 MFA 最多 5 分钟，恢复会话最多 1 小时。原 `PasswordLoginEnabled` 须允许密码验证；公开入口仍拒绝，不增加 Root 普通登录豁免。

网络条件必须同时成立：

- Backend 宿主端口只绑定 `127.0.0.1`，沿用现有 Compose 回环映射，经受控运维隧道访问 `/root-recovery`。
- 公开 HTTP/HTTPS 代理无条件拒绝 `/root-recovery` 与 `/api/user/root-recovery` 整个前缀，包含大小写、编码、重复斜线和归一化变体。本仓 `deploy/nginx-api.conf` 已加；Main 实际 API vhost 也必须同步后才可启用。
- 应用只接受原始 Host 的 `localhost`、`127.0.0.1`、`::1`，不采信转发头。该检查不能替代私有监听和公开代理 deny。
- 专用 API 为 `/api/user/root-recovery/login`、`/api/user/root-recovery/2fa`。无公开导航，不根据缺少 OIDC 绑定猜恢复身份。

## 准备与构建

### 2026-11-17 中英界面修订

当前候选的有序补丁链追加 `new-api-v0.13.2-pkce10-interface-i18n.patch`，清单为 `patches/interface-i18n-manifest.json`。原 `prepare`、`verify`、`build` 入口直接消费这份补丁与更新后的源码、前端资产清单，不需要另选可选脚本。版本及 `prepared-candidate-unpublished` 状态不变。

- 复用原生语言菜单和偏好保存；顶栏显示当前语言，手机也可点击切换。首次按浏览器识别，已保存的选择优先于 URL、旧 Cookie 和浏览器，不增加跨站同步。
- 统一登录、私有恢复、会话检查状态及相关错误提示补齐中英。保留其他原生语言、OAuth/恢复状态、匿名价格页、账号、额度与计费路径；未知服务端错误保留原文。
- 默认/自定义页脚之外提供 `对应源码 / Corresponding source`，固定指向本fork的 `i18n-20261117` Release。`/login` 页脚在会话Boundary之外且未隐藏，无需真实登录即可找到入口；不重复增加登录页链接，不改上游署名、API或数据库。发布前将新二进制和本次准确完整源码归档上传至该Release，说明中列出准确下载URL。
- 本轮仅离线复用已有依赖构建前端；本地 Chromium 全网络拦截覆盖中英桌面/390px、切换/刷新、手动选择优先、登录失败、会话故障门禁、恢复页 MFA 状态及原用户设置保存协议。截图和记录位于 `.build/i18n-20261117/evidence/`，不是线上验收。
- 历史 `ready-output` 二进制及其回执保留，**不含本次界面修订，不能当作当前候选构建产物**。当前部署必须按下列配方重新构建，并将新二进制、源码归档和准确 Git 提交绑定交付；不能以本地代码或历史回执声称已上线。React Doctor 未安装，未为此安装依赖。

需要 Python >=3.12、现有 Go 1.26.1、Bun 1.4.4。配方不安装、不下载、不连接业务系统。根锁仍是可复用 pkce.3，不可替换当前候选。

本版锁定完整 pkce.9 `source-files.json`，再顺序应用独立生产/验证/中英界面补丁；前端使用本版源码和既有冻结依赖构建，不能复用 pkce.9 dist。准备时精确核对本版 `frontend-assets.json`。

```powershell
python releases/v0.13.2-pkce.10/release.py prepare --base-source <pkce9-source> --frontend-dir <pkce10-built-dist> --destination <new-directory>
python releases/v0.13.2-pkce.10/release.py verify --source <new-directory>/source
python releases/v0.13.2-pkce.10/release.py build --source <new-directory>/source --cache-dir <existing-cache> --output-dir <new-output>
```

当前多语言部署按 `NOTICE.md` 准备完整对应源码。`package-source.py` 从明确的新提交读取 Git 配方，将清单精确匹配的完整展开源码、冻结前端、原许可证/声明及同次构建回执放入归档；拒绝真实环境、密钥、数据库、依赖缓存、调试文件与额外源码文件。归档、摘要及可供服务用户获取的准确公开地址由发布负责人绑定到本轮新二进制，不使用旧标签冒充本次源码。

```powershell
python releases/v0.13.2-pkce.10/package-source.py --source <prepared-source> --build-dir <new-output> --revision <full-new-commit> --output dist/<unique-corresponding-source>.tar.gz
```

此前额外归档的移除记录保留为历史，不代表本轮新版本已有对应源码。许可原文不变，不将某种 GitHub 呈现方式自动等同于全部许可义务已满足。恢复沿 pkce.9 内部凭据隔离要求，不默认回退 stock 上游或覆盖数据库。关闭模式会显式恢复旧登录行为，不能自动失败回退。

实际镜像封装使用本版 `Dockerfile.runtime`，传入已核对的 `SOURCE_REVISION`，把相同构建回执的 Linux 二进制以 `new-api` 文件放入新构建上下文。该文件只复制已构建产物，不下载或编译依赖；不能使用带旧版本标签的历史 Dockerfile。真实本地链路的 runtime 接线与验收状态另见 [验收记录](../../docs/UNIFIED-WEB-LOGIN-ACCEPTANCE.md)。

原统一登录交接按当时选择直接在服务器运行和验收，不再本地 Docker/额外测试。原二进制、Git 版本和升级/恢复要求见 [正式发布交接](DEPLOYMENT.md)；该二进制不含上方新增界面修订，不能把历史交接当作当前候选的构建或上线结果。发布仍由根任务在单独授权后统一执行。

## 检查与限制

本地 Go 检查覆盖严格 Main claims、默认关兼容、opaque store、固定 Basic 端点、失效/故障区别、无存活缓存、旧 cookie/换绑拒绝、原生 token、Root 白名单/真实角色/Host，以及原密码和实际备用码路径（仅内存合成 SQLite）。前端使用已有依赖构建，并以 headless Chromium 全网络拦截检查匿名桌面/390px、统一入口、私有门禁、原 PKCE、换号清缓存、权威故障和恢复页；已检查实际截图。

React Doctor 未安装，未安装或运行。构建保留上游 Browserslist 过期、lottie eval 和大 chunk 警告，未扩成依赖升级。

本地 stub 与内存数据库不证明真实 issuer、生产 Cookie/代理、跨站退出、恢复入口或计费已验收。真实链路和实际配置仍须在后续明确授权的目标环境发布前检查；此候选没有生产副作用。
