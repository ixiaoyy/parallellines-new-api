# 酒馆多角色计费凭据配置契约（New API 侧）

依据全站架构总纲 `ARCHITECTURE.md`（2026-11-19），New API 回归**纯模型路由与标准化计费网关**定位：

- **不建中央角色服务**。
- **不把 Bot 密钥和公开角色目录放进同一份配置**。
- **不再往 New API 前端塞新角色的专属 UI 补丁**。

## 三边职责与 `role_id` 对应关系

| 组件 | 负责范围 | 配置文件归属 |
| --- | --- | --- |
| **Synapse（`parallellines-entertainment`）** | 公开角色身份（MXID）、展示名称、简介与邀请规则；对外提供 `/_synapse/client/tavern-flux/v1/roles` | 公开目录（如 `/data/tavern-paid-roles.json`），**禁止包含任何密钥字段** |
| **Element（`parallellines-entertainment`）** | 只读消费 Synapse 返回的角色目录 | 无静态角色清单 |
| **New API（本仓库）** | 仅登记各 `role_id` 的独立 `bearer_token` 与计费权限；底层 SQLite 账表已由 `v0.13.2-pkce.14` 泛化为 `(active_room_id, role_id)` 与 `(room_id, event_id, role_id)` | 受限私有文件 `TAVERN_PAID_ROLES_FILE`（权限 `0600`，不入 Git，模板见 [tavern-paid-roles.example.json](../deploy/tavern-paid-roles.example.json)），向后兼容既有 `TAVERN_FLUX_BOT_BEARER` / `TAVERN_SAKANA_BOT_BEARER` |
| **独立 Bot 容器** | 自己管理人设、角色卡与群聊玩法 | `runtime/bot/<role-id>/` 私有运行目录 |

## 凭据守卫与发布前校验

1. 每个启用角色的 `bearer_token` 必须至少 32 字符、彼此互不相同，且不得与 Synapse issuer 凭据相同。
2. 停用单个角色只需将对应条目的 `"enabled": false`，不影响其他角色或既有账本流水。
3. 发布新增角色前，使用三边映射校验脚本核对 Synapse 公开目录、New API 私有凭据映射与目标 Bot 列表的 `role_id` 一致性（校验输出只返回 `role_id` 列表，绝不输出任何密钥原文）：

```powershell
node ../parallellines-entertainment/deploy/verify-role-mapping.mjs `
  --synapse-roles /path/to/public-paid-roles.json `
  --newapi-roles /path/to/private-tavern-paid-roles.json `
  --bot-roles flux-the-cat,sakana
```

## 下一版 `pkce.15` Go 侧通用化改造清单（终结硬编码）

`v0.13.2-pkce.14` 已完成数据库表主键泛化（`(active_room_id, role_id)` 与 `(room_id, event_id, role_id)`），后续切 `pkce.15` 只需替换以下 3 处 Go 逻辑（**不改数据库表结构、不新增前端 UI 补丁**）：

1. **`model/tavern_flux.go` — `ValidTavernRoleID(role string) bool`**
   - 从 `role == TavernRoleFlux || role == TavernRoleSakana` 改为正则校验 `^[a-z0-9][a-z0-9-]{0,31}$`（与 Synapse / 校验脚本完全一致）。
2. **`controller/tavern_flux.go` — 新增 `loadTavernRoleBearers() map[string]string`**
   - 优先读取 `TAVERN_PAID_ROLES_FILE`（校验 `0600` 权限、非符号链接、解析 `roles[]`，仅加载 `enabled != false` 且令牌长度 32–256、ASCII 可打印、互不重复且不等于 `TAVERN_FLUX_ISSUER_BEARER` 的条目）。
   - 未设置 `TAVERN_PAID_ROLES_FILE` 时，完全回退读取既有 `TAVERN_FLUX_BOT_BEARER` 与 `TAVERN_SAKANA_BOT_BEARER`，保证零破坏升级。
3. **`controller/tavern_flux.go` — `TavernFluxServiceAuth(false)` 与 `fluxRoleEnabled(role)`**
   - 对全部已加载角色令牌执行常量时间比较（`subtle.ConstantTimeCompare`）反查唯一 `role_id`，存入 `fluxAuthenticatedRole`；完全忽略请求头或正文自报角色。

