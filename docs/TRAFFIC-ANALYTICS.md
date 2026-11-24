# 可选匿名流量采集

本接入复用当前锁定 New API `v0.13.2` 原生 `InjectUmamiAnalytics`，适用于现有 `v0.13.2-pkce.10` 配方；不修改 Go/React 业务源码、二进制、冻结发布锁、计费、角色、API Key 或 Chat relay。无需新应用版本或前端构建。

## 原生接线与默认状态

原生启动逻辑仅在 `UMAMI_WEBSITE_ID` 非空时，将 `UMAMI_SCRIPT_URL` 作为 `defer` 脚本放入 Web HTML，并附 `data-website-id`。新增可选 `deploy/traffic-analytics-api.overlay.yaml` 复用该槽：

- `API_TRAFFIC_SITE_ID` 未设置或为空时，原生不注入脚本，默认不采集。
- 明确设为 `api` 才启用本 collector；其他值不受支持。
- 脚本固定为 `https://pingxingxian.space/traffic-collector.v1.js`。collector 仅兼容 `data-website-id=api`，缺省采集端点固定为 `https://pingxingxian.space/api/v1/site/traffic`。

这是本项目自己的流量采集，不使用 Umami 服务或发送给第三方。启用前必须确认目标没有正在使用的其他 Umami 配置；如已有，不得以此覆盖，应另行审核独立注入方案。未检查真实服务器环境。

## 性能、隐私与已知限制

New API 原生只提供 `defer`，脚本下载本身不保证空闲后才开始；共享 collector 必须在空闲时初始化，按最多 20 条、30 秒/离开的小批量发送，无轮询、不重试，失败丢弃不阻塞页面。网关不执行统计查询，不给生成请求增加调用或同步入库。

采集只使用规范公开路径与随机匿名标识，不读取查询参数、片段、标题、API Key、账号、输入或模型内容，提交不附认证。规范化、跨系统匿名访客口径及有界请求由共享 collector 负责，不在网关重复实现。API 原生管理分析与计费仍保留；此接入只汇总浏览器流量，不代表模型调用量，也不补采历史数据。

目标代理须允许精确主站 script/connect 来源，并保持不泄露完整私有 URL 的 Referrer-Policy；不为采集全局放宽 CSP（内容安全策略）。本地配置存在不证明目标 CSP、页面或接口可用。

## 发布与关闭

主站 collector/接收端先就绪，目标 CSP 与已有 Umami 配置核对后，才在获得目标环境授权时设置 `API_TRAFFIC_SITE_ID=api`，向现有 Compose 项目显式合入此可选 overlay。沿既有镜像、数据卷、网络与服务名发布，不替换当前服务为根 pkce.3 基线，也不输出完整含密钥 Compose 配置。

2026-11-17 中英联合消费已核对：当前 pkce.10 正式 `prepare/build` 入口已消费 `new-api-v0.13.2-pkce10-interface-i18n.patch` 与 `interface-i18n-manifest.json`。联合交付必须使用这条更新后的链所生成的镜像，再叠加本可选环境覆盖；不能拿先前的冻结前端或二进制覆盖中英结果。当前 `.build/i18n-20261117/prepared/source` 的 Go 注入、源与已构建 HTML 保留原生 Umami 占位，统计覆盖不需要再改该补丁链。这里只核对本地消费与接线，未新增或运行完整构建、未确认目标运行环境。

本任务未构建、重启、上传或部署。关闭时清空 `API_TRAFFIC_SITE_ID` 并按原流程发布，或移除此 overlay 并恢复此前原生分析配置；只清环境接入，不删除运行数据。目标验收须包括默认关无脚本、启用后固定 script 标签及匿名批量、原登录/价格/控制台可用、采集失败不影响业务。

模型使用量、成功率、Token 与额度可继续复用原生 `/api/data/`、`/api/data/users`、`/api/log/stat`，但综合看板的服务端最小权限接入尚未建立，本轮不引入 Root/管理凭据。额度不能未经换算配置核实就标成人民币，Chat 与网关 Token 不相加。
