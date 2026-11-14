# pkce.10 正式发布交接

本轮按用户最新决定，不再处理本地 Docker、不补本地测试或重建应用；直接由发布负责人盘点实际服务器、运行候选并验收。此文不是已上线回执。Main、issuer、Chat 与公开代理由根任务统一协调，NewAPI 不单独切换登录权威。

## 可复用产物与最终提交绑定

已验证应用输入没有改变：

- 展开源码：`.build/unified-web-login-pkce10-20261114/ready/source`，1310 文件，按本版完整源码清单固定。
- Linux amd64 二进制：`.build/unified-web-login-pkce10-20261114/ready-output/new-api-linux-amd64`。
- 构建回执：同目录 `build-receipt.json`。记录版本 `v0.13.2-pkce.10`、199 个实际嵌入公开文件及二进制 SHA-256 `d0f64b597c2d4aeb29c79256fc2f1e434bc4e574512a92c8aefda4ce74b8aa1b`。
- 现有 `.candidate.tar.gz` 是未绑定提交的历史候选，早于后补发布资料，不能当正式归档发布。

正式对应源码包必须在负责人按用户批准的顺序完成最终提交后生成，确认该仓库的本地 HEAD、已推送目标和批准 SHA 一致；不借本文提前越过服务器候选验收或提交的授权条件。若先运行未提交的服务器候选，必须明确其候选状态，不给它填写虚假的最终 SHA。最终提交后只打正式包，不重编译应用：

```powershell
$sha = git rev-parse HEAD
python releases/v0.13.2-pkce.10/release.py package --source .build/unified-web-login-pkce10-20261114/ready/source --build-receipt .build/unified-web-login-pkce10-20261114/ready-output/build-receipt.json --output dist/release-v0.13.2-pkce.10/new-api-v0.13.2-pkce.10-corresponding-source.tar.gz --code-commit $sha
```

这是正式归档操作：核源码/ELF 与已有清单，要求每个 `release-inputs.json` 输入均与该 HEAD 的内容一致，回执写 `publishable:true` 和实际 `integration_commit`。它不安装、不构建、不联网运行应用。正式归档名固定；已有输出不覆盖。若源码、清单或二进制不一致，停止发布，不通过改清单或回执绕过。

## 本次待提交精确清单

以下所有变更均需进入同一个 NewAPI 提交；现有暂存只覆盖生产材料，不能漏掉未暂存/未跟踪的测试和说明引用。

```text
README.md
deploy/nginx-api.conf
docs/OPERATIONS.md
docs/UNIFIED-WEB-LOGIN-ACCEPTANCE.md
patches/new-api-v0.13.2-pkce10-unified-web-login.patch
patches/new-api-v0.13.2-pkce10-unified-web-login-tests.patch
patches/unified-web-login-manifest.json
releases/v0.13.2-pkce.10/DEPLOYMENT.md
releases/v0.13.2-pkce.10/Dockerfile.runtime
releases/v0.13.2-pkce.10/README.md
releases/v0.13.2-pkce.10/frontend-assets.json
releases/v0.13.2-pkce.10/release-inputs.json
releases/v0.13.2-pkce.10/release.py
releases/v0.13.2-pkce.10/source-files.json
releases/v0.13.2-pkce.10/unified-web-login.env.example
releases/v0.13.2-pkce.10/upstream.lock.json
scripts/seed-unified-web-test-db.go
scripts/test-unified-web-helpers.mjs
scripts/test-unified-web-local.mjs
```

已提交且未变的 `LICENSE`、`NOTICE.md`、历史配方、锁和脚本依赖由 `git archive HEAD` 一并进入正式对应源码包，展开源码内的许可证也由完整清单保留。不要为重提交而修改许可；部署修改版仍须向使用者提供这份精确对应源码，不能只留私有二进制。

## 服务器 compare-before

负责人必须记录实际服务与恢复点，不能把历史 pkce.8 当当前版本：

1. 实际 Compose project/service、容器、当前镜像 ID/digest、应用版本、二进制摘要、架构、数据路径/挂载、网络和宿主端口绑定。保留当前镜像、二进制、服务定义与配置回执；不清理。
2. 原 secret/env 文件路径、原生数据库、session/crypto secret、OIDC provider 1/slug/client、原 RP 注册和既有 Main `sub` 绑定。只记录脱敏结果，不展开密钥或整份 Compose。不得把测试库或测试配置上传覆盖正式数据。
3. 现有 profile/account sync、Chat relay、普通 API key 与内部凭据隔离、付费/免费模型和计费开关保持原值。核实际 Main 绑定情况；不按邮箱猜合并，不重建已有账号或余额。
4. Main 与 issuer 的新版状态、登录审批和退出票据合同先具备；NewAPI 两个新开关默认关闭。仅在跨项目接线就绪后显式启用 `MAIN_UNIFIED_WEB_LOGIN_ENABLED=true`，不得故障时自动回退本地密码。
5. 私有恢复若启用，先核真实 Root UID 白名单、原密码/MFA、`PasswordLoginEnabled` 和回环端口，再验证实际公开 HTTP/HTTPS vhost 拒绝整个恢复路径树。仓库模板不等于生效配置。不能仅靠 Host/转发头保证私有。

## 服务器最小封装与切换

按当前批准阶段上传已核二进制、相应源码包及回执到新的版本目录，候选不冒充正式版本。正式封装使用归档内本版 Dockerfile，只封装已编译应用；`SOURCE_REVISION`、源码回执、运行镜像标签与批准 SHA 必须一致：

```sh
docker build --platform linux/amd64 --build-arg SOURCE_REVISION="$APPROVED_SHA" -f "$RECIPE/releases/v0.13.2-pkce.10/Dockerfile.runtime" -t "$REVIEWED_IMAGE_TAG" "$NEW_CONTEXT"
```

`NEW_CONTEXT/new-api` 必须是上述同一二进制。底座由本版锁固定，不换版本。构建后负责人记录实际镜像 ID/digest，再只更新已盘点目标服务的 image/build；Compose 命令必须使用实际配置路径、项目名和 service，不猜路径或启动新默认栈。切换时保留既有数据、挂载、网络与秘密，不调用会关闭免费门的旧 install helper。

服务器运行验收覆盖真实登录/无重复凭据、匿名门禁、同浏览器换号/退出、其他设备会话不被踢出及 Root 私有恢复；使用批准的会话/账号，不动其他用户的数据，不调用模型。不通过主动中断生产 issuer、压测或造故障补验；相应 fail-closed 定向证据沿用已完成的本地检查。

## 恢复契约

- 发布失败，负责人按 compare-before 恢复捕获的原 image/build 与原配置值，并核健康；不恢复旧数据库、不清账务、密钥或凭据，不动其他服务。
- 已有任何 `internal_purpose` 行时，stock 上游和 pkce.1 缺少凭据隔离，不能作为恢复目标，包含已禁用/软删除行。只有确需评估旧二进制且已停止/排空新增签发时，才由负责人对实际数据库运行既有只读 `scripts/guard-legacy-rollback.py`；该脚本不会授权或执行恢复。
- 关闭新模式/恢复旧版本会恢复旧登录行为，是明确的运维恢复决定，不代表仍满足新的 Main-only 登录合同。跨项目的开关和代理状态由根任务一并判断，公开恢复路径 deny 不因回退而移除。
- NewAPI 单实例重启会丢失内存 Web 证明，原 Main 会话仍有效者可经原 OIDC 重接。不要扩副本或因重接而删除用户/数据；保留当前、候选、恢复版本和所有运行数据，清理另行授权。
