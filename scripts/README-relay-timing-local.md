# OAuth relay 本地耗时观测

承接 `build-performance-local.py` 已验证的前端输入，只追加独立 Go 性能补丁。
输出版本 `v0.13.2-pkce.8-local-relay-timing`，未发布；不修改 pkce.8 的发布锁、源码归档或资产清单。

## 日志字段和真实边界

原有一条 GIN access log 末尾追加以下固定字段，沿用同一 requestId，不增加逐帧日志、业务表或后台任务。

| 字段 | 测量范围 |
| --- | --- |
| `oauth_relay_total_ms` | 三条 OAuth adapter 路由入口到 handler 返回；不含此前全局中间件、TLS/反向代理，也不等待已提交的后台任务 |
| `oauth_relay_userinfo_verify_ms` | 本次主站 HTTPS UserInfo、读取响应及声明校验；不改变每请求核验或身份 TTL |
| `oauth_relay_account_resolve_ms` | 原绑定账号解析或账号同步、事务提交及原有缓存失效恢复；包括首次开户收尾函数的同步部分 |
| `oauth_relay_credential_ms` | 原内部凭据读取或首次创建 |
| `oauth_relay_distribute_ms` | 原 Distribute 中间件入口到 controller 入口；选渠失败计到该中间件返回；不包含 controller 内的后续换渠或生成 |
| `oauth_relay_upstream_headers_ms` | 首次实际返回 HTTP 响应头的那次通用 `client.Do` 调用耗时，含该调用内部连接/重定向；不含前次失败或重试间隔 |
| `oauth_relay_upstream_headers_attempt` | 上述响应头属于本请求第几次实际 `Do` |
| `oauth_relay_upstream_attempts` | 该 adapter 请求通过通用发送入口实际执行的 `Do` 总数 |

`-` 表示没有可报告的完成测量，不能当成零耗时。没有响应的网络错误不会伪造成响应头。
响应头耗时不等于首 token 时间；200/SSE 返回不代表整次生成成功，仍沿用原流错误、用量和计费结果。
原 `frt` 的起点和计算保持不动。普通 API 不创建计时记录，日志格式也不追加这些字段。
adapter access log 不复述 query，以免原入口拒绝的 query 凭据进入日志；不记录 bearer、身份声明或请求正文。

## 本地准备、测试、构建

```powershell
python scripts/build-relay-timing-local.py prepare `
  --base-archive .build/free-chat-deploy-20261102/new-api-v0.13.2-pkce.8-corresponding-source.tar.gz `
  --destination .build/relay-timing-local --with-tests

python scripts/build-relay-timing-local.py test `
  --source .build/relay-timing-local/source `
  --cache-dir .build/performance-cache `
  --output .build/relay-timing-local/isolated-tests.json

python scripts/build-relay-timing-local.py build `
  --source .build/relay-timing-local/source `
  --cache-dir .build/performance-cache `
  --output dist/relay-timing-local
```

需 PATH 中已有固定 Go 1.26.1；不全局安装、不隐式下载工具链或模块。使用原 go.mod/go.sum
恢复依赖后，测试和构建均 `GOPROXY=off`。测试只用内存 SQLite 与进程内 HTTP transport mock，
不访问真实 OAuth、模型或业务库。Go 二进制按原 Linux amd64、CGO=0、greenteagc 构建。

前端仍按上一批完整 Web 身份复用。缓存命中不再执行 Vite；缺失或输入改变时沿上一批配方明确处理，
不能拿 pkce.8 旧资产冒充优化后的前端。生产和验证补丁分开；不加 `--with-tests` 只应用生产增量。

## 保持不变与未实施

- provider/绑定/用户锁、完整资料碰撞判断、冲突时撤权、Redis 失效失败后的再次恢复均未改。
- 付费/免费门、预扣/结算/退款、上游时限、响应状态、重试和原错误边界未改；无新增数据库结构。
- 本轮不实施维护门、503、排空、取消请求或超时新政策。handler 返回后仍可能有异步退款、Redis 回写、
  批量账务和导出聚合任务；这些计时或 `http.Server.Shutdown` 不能证明金融写入已可靠排空。
- 发布、服务器运行、日志采集兼容和真实上游耗时尚未验收；新字段只有在未来获准发布后才可能出现在运行日志。
