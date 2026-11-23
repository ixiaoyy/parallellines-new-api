# v0.13.2-pkce.15：配置驱动多角色计费网关（零硬编码、零前端补丁）

从 [v0.13.2-pkce.14](../v0.13.2-pkce.14/README.md) 冻结配方增量交付，落地 [TAVERN-PAID-ROLES-CONTRACT.md](../../docs/TAVERN-PAID-ROLES-CONTRACT.md) 中的 Go 侧通用化改造：

1. **角色标识通用校验**：`model/tavern_flux.go` 的 `ValidTavernRoleID` 改为正则 `^[a-z0-9][a-z0-9-]{0,31}$`，与 Synapse 公开角色目录及三边校验脚本一致，不再硬编码 `flux-the-cat` / `sakana`。
2. **受限私有凭据文件 `TAVERN_PAID_ROLES_FILE`**：`controller/tavern_flux.go` 新增 `loadTavernRoleBearers()`，优先读取 `0600` 私有文件（拒绝软链、超 64 KiB、宽松权限、未知字段、重复 `role_id`、重复令牌或与 `TAVERN_FLUX_ISSUER_BEARER` 碰撞）。未设置 `TAVERN_PAID_ROLES_FILE` 时自动回退至既有 `TAVERN_FLUX_BOT_BEARER` 与 `TAVERN_SAKANA_BOT_BEARER`，实现零破坏平滑升级。
3. **常量时间全量反查与通用消费日志**：`TavernFluxServiceAuth(false)` 对所有已启用角色令牌执行常量时间比较反查唯一 `role_id`；`controller/tavern_flux_native.go` 保留 Flux 原 `TokenName`（`Tavern Flux`），其余角色统一记录 `Tavern <role_id>` 与 `tavern_role`。
4. **零数据库迁移、零前端重建**：完全复用 `pkce.14` 的 `(active_room_id, role_id)` / `(room_id, event_id, role_id)` 表结构与已冻结的 `web/dist` 前端产物，不再叠加任何业务前端 UI 补丁。

## 本地离线准备与构建

```sh
python releases/v0.13.2-pkce.15/release.py prepare --base-source <verified-pkce14-source> --destination <new-directory>
python releases/v0.13.2-pkce.15/release.py verify --source <new-directory>/source
python releases/v0.13.2-pkce.15/release.py build --source <new-directory>/source --cache-dir <existing-cache> --output-dir <new-output>
```

源码配方封版不代表已在生产部署；上线前须使用 `scripts/verify-tavern-paid-roles-config.mjs` 与 `parallellines-entertainment/deploy/verify-role-mapping.mjs` 核对三边 `role_id` 映射，并按 `pkce.14` 账本安全约束完成升级前排空与快照。
