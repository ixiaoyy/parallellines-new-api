# v0.13.2-pkce.8：Chat 的 OpenRouter 免费模型

本版在 pkce.7 基线上新增免费 Chat 入口。构建、源码推送和实际激活分别记录，不以源码准备成功
代替上线验收。本机按用户决定不下载 Go；已复用发布服务器现有 Go 1.26.1 完成编译及相关用例，
Go 用例运行在断网命名空间和临时内存数据库中，没有访问真实模型或业务库。

## 新增行为与不变项

- 独立门 `CHAT_OPENROUTER_FREE_ENABLED=true` 才向 Chat 列出并允许调用 `openrouter/free`。
  **默认关闭**。现有 OAuth relay 地址、身份核验和请求路由不变，同时支持原生
  `/chat/completions` 与 `/responses` 的流式、非流式调用。
- Chat 可选集合增加这一个模型，仍要求用户当前分组有启用渠道。模型列表可见不替代
  真实调用时的定价、渠道和最终请求校验；没有渠道或配置不满足时明确失败。
- 仅在固定主站 UserInfo、原生内部凭据及 `TokenAuth` 全部成功后扩展本次请求权限。
  原持久 `OAuthRelayModelLimits` 仍精确为三个原模型；不迁移、重发、恢复或放宽旧凭据，
  不清全局缓存。禁用、过期、软删除和撤销凭据继续拒绝，内部凭据仍不能用于普通 API。
- 沿用 pkce.7 的统一开户/角色同步开关与边界，不另建账号、赠额或修改余额。
  `openrouter/free` 的已核验零价 Chat 请求可使用已有 `FreeModel` 分支跳过预扣，
  因而不要求钱包或订阅已有余额。全局免费预扣设置不变。
- 原三个付费模型、默认模型、Responses 协议、标准用量校验、钱包/订阅预扣及结算不变。
  普通 API 的既有 OpenRouter 渠道也不受这个 Chat 激活门或免费例外影响。

## 免费资格和失败处理

每次发送前校验当前渠道、最终 URL/Host、实际生效定价和最终 JSON。要求：

1. 精确模型 `openrouter/free`，类型为 OpenRouter，官方基址 `https://openrouter.ai/api`。
   首次定价及每次实际发送均核验，成功出站后冻结本次零价资格；重试不能沿用上一渠道资格。
   在途请求不被后续全局改价追溯收费，结算核对本次快照及实际费用，下一请求按新配置检查。
2. 最终生效模型价格为零。非零固定价优先于倍率，不可用零分组倍率绕过；
   阶梯表达式不属于该零价合同，不能仅凭表达式初值为零取得资格。
3. 不允许重定向到其他模型、付费回退数组、收费服务端工具、插件或输出音频。
   普通客户端 `function` 工具声明继续允许；未核准的非空 `extra_body` 不透过免费守卫。
   守卫位于转换、参数覆盖、请求头覆盖和原始透传之后，不能再覆盖成付费请求。
4. 新入口禁用 HTTP 跳转，整个已认证免费请求共享最长 60 秒的 context；
   各次上游请求也不超过 60 秒，不改变共享 HTTP client 或原三个模型的时限。

正常费用和用量仍按真实响应走原结算，不强行把账单改成零。上游 `usage.cost` 若提供，
在写回非流响应或每个 SSE 帧前检查；显式非零/无效费用明确失败且不自动重试。
费用字段缺失不伪造为零，也不能据本地零定价宣称核实了上游真实发票。
结算发现非零本地费用时，在用量与余额写入前拒绝，不静默改价。

流读取错误、超时、客户端断开或缺协议终止证据不能被 token 估算伪装为成功：
Chat 流要求实际 `finish_reason` 和 `[DONE]`；Responses 要求真实终帧及正常结束。
新免费流在确认结束前不发成功终止帧，失败沿既有错误边界返回 HTTP/SSE 错误。
已经发送的文本增量无法撤回，不能把部分文本当作整次成功。

**用户确认的违规费例外：**仅已核验 Chat、通过最终出站守卫且本次零价资格快照仍有效的
`openrouter/free` 请求免附加违规费。违规响应仍被拒绝，原有错误规范化和错误审计继续；
日志额外标记 `chat_free_violation_fee_exempt`。尚未通过守卫、新请求定价非零、换渠、普通 API
以及其他模型均无此例外。原三个付费模型和全局 Grok 扣费配置不变。

OpenRouter 官方说明 `openrouter/free` 可直接用于 Responses，并仅在免费模型间路由：
[Free Models Router](https://openrouter.ai/docs/guides/routing/routers/free-router)。
本地模拟验证不能替代目标环境同身份链的真实免费调用验收。

## 准备源码和本地可运行检查

复用 pkce.7 准备器与同一固定 pkce.6 完整归档，先重建 pkce.7，再应用本版生产增量。
不覆盖已有目录，不下载依赖，不执行 Go，不连接数据库或服务。

```sh
python releases/v0.13.2-pkce.8/prepare-source.py \
  --base-archive dist/pkce6/new-api-v0.13.2-pkce.6-corresponding-source.tar.gz \
  --destination .build/pkce8 --with-tests

python releases/v0.13.2-pkce.8/verify-release.py \
  --base-archive dist/pkce6/new-api-v0.13.2-pkce.6-corresponding-source.tar.gz \
  --destination .build/pkce8-verification
```

生产补丁、前后 manifest、有序 lock 与独立验证补丁分开保存。`--with-tests` 同时带入
pkce.7 原有验证和本版用例；无此参数只准备生产增量。Python 检查证明补丁可复现和
指定旧契约文件未改，不证明 Go 可编译或业务用例通过。

得到目标环境验证授权且已有 Go 1.26.1 时，可在准备的源码运行下列**离线合成用例**；
它们只使用内存 SQLite、合成身份和受限 HTTP mock，不执行真实模型请求：

```sh
go test ./service ./relay/channel/openai ./router ./middleware ./model ./relay/helper \
  -run 'Test(ChatFree|ChatOAuthRelay|OAuthRelayCredential|OAuthRelayRevoke|OpenAIStandard)' -count=1
```

本次新增 Go 用例覆盖零余额 Chat 的四种协议形态、真实最终 body 的模型/回退/工具覆盖、
原始透传、非零费用、流读取失败/缺终帧、激活门、旧内部凭据复用/撤销/普通 API 禁用，
以及免费 Chat 违规拒绝不扣附加费、普通 API 同模型仍保留原违规费、在途改价/启用阶梯不追溯收费、
下一请求按新价拒绝和重试重新取得免费资格。相关六个包的隔离检查已通过；验证中只补齐测试夹具
所需的启动超时与订阅表，没有修改生产默认超时、原付费余额规则或数据库结构。
原三模型只验证本地拒绝/计费接线，禁止为验收发起付费生成请求。

前端未修改，复用原 pkce.6/7 字节资产。若固定归档未带可嵌入的 `web/dist`，先按
[pkce.7 构建说明](../v0.13.2-pkce.7/README.md) 从已核对的旧二进制提取原资产，
不要放入占位产物或用另一次前端构建替换。构建沿用 Go 1.26.1、Linux amd64、CGO=0：

```sh
cd .build/pkce8/source
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 GOEXPERIMENT=greenteagc go build -mod=readonly -buildvcs=false \
  -ldflags '-s -w -X github.com/QuantumNous/new-api/common.Version=v0.13.2-pkce.8' -o new-api .
```

## 激活、验收和恢复

以下只是发布说明，不构成服务器、上传、部署、重启或真实请求授权：

1. 先发布 API 代码，并保持本目录 overlay 的 `CHAT_OPENROUTER_FREE_ENABLED=false`。
   保留原渠道、密钥、三个付费模型及所有其他环境配置。
2. Chat 消费者配置、免费模型可见权限、默认模型和后台任务隔离经独立验收后，
   另获授权再把门设为 `true`。不要只改模型列表就宣称后台任务不会使用付费模型。
3. 只以免费模型验收当前身份的模型列表、零余额、新旧凭据、Chat/Responses 流式和
   非流式、违规拒绝与错误日志。原三模型和默认项只作配置/本地接线核对，不调用付费模型。
4. 回滚先关闭免费门并等待已经获准的免费请求结束（共享 60 秒上限），再回退 Chat。
   防止旧 Chat 把免费模型的后台任务重新发给原付费默认模型。
5. 不恢复旧数据库，不旋转内部凭据。API 只能回到保留 pkce.7 账号/会话保护的版本；
   完整源码、补丁、锁、验证与说明随实际发布保存并提供对应源码。

真实激活、Chat 免费调用及线上日志/余额结果以当次发布回执和验收为准；不能由上述隔离检查推定。
