# 账号资料冲突查询：本地存在性增量

本轮只把 `mainProfileCollision` 的 `COUNT(*)` 改成 `SELECT id ... LIMIT 1`，使用项目已有的
`Find` + `RowsAffected` 方式。零行正常返回无冲突；数据库错误仍返回原安全错误。
谓词保持 `id <> ? AND (username = ? OR LOWER(email) = ?)`，`Unscoped`、参数归一化均不变。
函数外的 provider/绑定/用户锁、事务、冲突降权/禁止提权、缓存失效失败恢复逐字保持原值。

没有改身份 TTL、计费、其他重复读、数据库结构/索引、已发布锁或旧归档。没有实施排空、维护门、503 或 flush。
产物标记 `v0.13.2-pkce.8-local-profile-exists` 和 `published:false`；当前仅为本地候选。

## 重现

```powershell
python scripts/build-profile-exists-local.py prepare `
  --base-archive .build/free-chat-deploy-20261102/new-api-v0.13.2-pkce.8-corresponding-source.tar.gz `
  --destination .build/profile-exists-local --with-tests

python scripts/build-profile-exists-local.py check `
  --source .build/profile-exists-local/source --cache-dir .build/performance-cache `
  --output .build/profile-exists-local/correctness-tests.json

# 与其他 CPU 基准/冷构建错开；固定样本，不挑最好的一次。
python scripts/build-profile-exists-local.py compare `
  --source .build/profile-exists-local/source --cache-dir .build/performance-cache `
  --output .build/profile-exists-local/query-comparison.json

python scripts/build-profile-exists-local.py build `
  --source .build/profile-exists-local/source --cache-dir .build/performance-cache `
  --output dist/profile-exists-local
```

顺序承接已验证的前端和 timing 配方。只允许本次批准的账号碰撞函数覆盖上一批该文件的
不变断言，其他文件仍核对；账号文件的函数外前缀/后缀也必须与上一批完全相同。
Go 继续使用已核验 1.26.1 和原模块缓存，测试/构建 `GOPROXY=off`，不安装或升级依赖。
前端命中上一批同身份缓存，没有重新执行 Vite。

## 2026-11-03 本地结果

正确性通过：16 组同谓词用例覆盖本人、普通冲突、软删除、ASCII 大小写 email、空字符串、
SQL NULL、空表、多命中及数据库错误。SQLite 实际执行确认每次 1 条查询、候选只取 id 且带 LIMIT 1；
MySQL/PostgreSQL 仅作无连接 DryRun SQL 生成核对，不代表真实数据库/排序规则验证。
另验证原锁意图及事务接线、冲突撤权/不提权、首次提交后 DEL 失败再以相同资料请求恢复 DEL。
Redis 使用进程内 RESP 脚本连接，不监听端口、不连接真实 Redis。

公平小基准：相同内存 SQLite、原 User 模型索引、单连接、6000 行；固定 32 对交错批次，
每批 64 次，另预热每种查询 128 次。每场景每种查询共 2176 次，总计 17408 次冲突检查，
45 秒上限，实际比较约 22.1 秒。Windows amd64、Go 1.26.1、GOMAXPROCS=1；测量的是查询检查函数，
不包含账号同步整链路或公网请求。

| 场景 | COUNT 中位数，微秒/次 | 候选中位数，微秒/次 | 解读 |
| --- | ---: | ---: | --- |
| 无冲突 | 1175.65 | 1216.80 | 中位数较高 3.50%，均值仅高 0.23%；配对中位变化 -0.94%，候选更慢 12/32 对，未见稳定超噪声回退，也没有可确认提速 |
| 首行命中 | 1514.69 | 20.30 | 可提前停止；仅代表这个合成冲突场景 |
| 末行命中 | 1408.24 | 1345.06 | 两者仍扫描到末尾，配对变化分散，不能据一次汇总值声称稳定提速 |
| 全部命中 | 1540.57 | 22.70 | 候选找到首条即停，COUNT 仍统计所有匹配 |

无冲突配对变化 P05/P95 为 -10.55%/+22.69%；末行命中为 -29.16%/+28.08%。四场景的 SQLite
计划均显示 `SCAN users`，没有引入新索引或宣称消除了普通无冲突全扫描。
首次单查询计时出现快路径零值量化，原报告保留，不用于百分比收益声明；随后统一用固定批次计时。
批次快路径仍受宿主计时分辨率影响，不使用 -100% 的尾部读数或保证倍率，也不把局部结果当整体请求提速。

## 验证边界与恢复

- 最终候选定向测试和 Linux amd64/CGO=0 编译通过；测试在 Windows 原生 Go 上运行，未启动 Linux 服务。
- 不访问真实 OAuth、模型、生产数据库或 Redis；没有部署，也没有 CDN 或远端变更。
- 前一批 timing/前端配方及本地产物均保留。撤销本增量时回到前一配方或已保留的前一本地产物，
  不恢复业务数据库、不迁移数据；正式上线和恢复仍须另行授权与目标环境验收。
