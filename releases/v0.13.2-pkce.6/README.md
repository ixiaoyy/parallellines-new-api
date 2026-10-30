# v0.13.2-pkce.6：Responses 缓存写入时长适配

在 pkce.5 上增加单一计费适配增量，覆盖三个已批准的官方直连模型。
不修改价格、倍率、长上下文门槛、舍入、身份、权限、余额或数据库结构。

发送前从已验证的原始请求保存统一缓存时长：省略设置使用官方默认 `30m`，
显式 `12h` 保留。混合断点、未知设置和服务端历史会话不推断时长。
仅当上游未提供时长明细且该请求能证明统一时长时，将真实 `cache_write_tokens`
归入对应档位。明细存在时继续严格校验；显式 null、字段不全、数量矛盾不被默认值掩盖。
流式和非流式 Responses 共用适配，Chat 及其他模型原有行为不变。

依据：[OpenAI 官方缓存时长及用量说明](https://developers.openai.com/api/docs/guides/prompt-caching#cache-lifetime)。

## 构建与对应源码

提交后执行 `python releases/v0.13.2-pkce.6/package-source.py <pkce5-source.tar.gz> <new-source.tar.gz>`。
归档基于固定旧源码及有序补丁，不包含运行数据或密钥。解压后 `source/` 为完整构建输入。
沿用 Go 1.26.1、Linux amd64、`CGO_ENABLED=0`、`GOEXPERIMENT=greenteagc`，
构建 `go build -buildvcs=false -ldflags '-s -w -X github.com/QuantumNous/new-api/common.Version=v0.13.2-pkce.6' -o new-api .`。
`web/dist` 使用 pkce.5 的 `frontend-assets.json` 所列原产物，不重建前端。
可用 `extract-frontend.py <pkce5-binary> <frontend-assets.json> <output>` 从旧版构建产物
恢复原有 125 个嵌入文件；原 `go:embed` 未嵌入的两个下划线开头文件仍不新增。
Responses 请求结构同时保留原生 `prompt_cache_options`，避免请求声明的时长在发给上游前丢失。
编译产物和完整对应源码随本次发布保留并供用户获取。

## 部署与恢复

仅更新现有 New API 服务镜像；保留 Chat、issuer、主站及全部环境、挂载和 secret 路径。
部署前保存现有服务块和镜像作为恢复点，沿用 Chat 仓库的局部 Compose 条件更新工具，
仅重建 New API。失败恢复本次旧服务块，不恢复数据库、不补扣之前失败的请求。
旧版 pkce.5 已含身份、计费和删除账号保护，可作为本次修复的恢复镜像，不能退到更早版本。

本次按用户要求不做离线测试、lint 或隔离 smoke；只执行交付必需的源码准备和生产编译。
部署后检查真实状态接口版本和策略开关，不发起付费请求。
真实聊天结算及截图那笔请求的退款结果仍需独立记录确认，不能由健康检查冒充验收。
