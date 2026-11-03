# v0.13.2-pkce.9：性能与完整公开前端打包

当前是待发布候选，未因源码准备而上线。2026-11-03 的只读公开状态检查仍返回 pkce.8。
正式切换必须核对真实容器、镜像、二进制、数据绑定、现有开关及可用 pkce.8 恢复版本。
不使用旧 `deploy-chat-free.py install` 套版本号：该流程会关闭免费门，不适合本次 image-only 升级。

## 范围

- 前端 28 个页面按路由加载；保留中文回退，另外 6 种既有语言按需加载。
- OAuth adapter 原 GIN access log 增加固定阶段耗时，保持原 `frt`；不记录 bearer、声明或正文。
- 资料碰撞检查由同谓词 COUNT 改为 SELECT id LIMIT 1；锁、事务、软删除、大小写、空值、
  冲突撤权/不提权和缓存失败恢复保持原义。普通无冲突路径没有可确认提速，收益只限能提前命中的冲突检查。
- `all:web/dist` 使 Go 真正包含已验公开构建的两份下划线模块。清单拒绝额外文件、map、秘密文件名和链接；
  对真实 main package embed.FS 核对 197 份公开文件、965 条解析后的模块/样式/HTML 引用及两份模块的 HTTP 内容。
- 不改身份 TTL、付费/免费/缓存计费、上游时限、数据库结构或任何现有运行环境值。
  不包含排空、维护门、503、flush 或其他计费重构。共享 Nginx 由发布负责人单独协调。

## 固定输入和构建

以 pkce.8 完整对应源码为基线，按 lock 的四个增量顺序准备。前端直接复用前批已验的公开资产，
不重新安装/编译前端。Go 仍为已校验的 1.26.1、Linux amd64、CGO=0、greenteagc。

```powershell
python releases/v0.13.2-pkce.9/release.py prepare `
  --base-archive .build/free-chat-deploy-20261102/new-api-v0.13.2-pkce.8-corresponding-source.tar.gz `
  --frontend-dir dist/profile-exists-local-20261103/web `
  --destination .build/pkce9-release

# 只运行本版新增的真实 embed.FS 检查，不重跑已完成的业务用例。
python releases/v0.13.2-pkce.9/release.py check-assets `
  --source .build/pkce9-release/source --cache-dir .build/performance-cache `
  --output .build/pkce9-release/embed-assets-check.json

# 仅为正式 Version 编译 Go；前端必须复用已核验资产，绝不回退重跑 Vite。
python releases/v0.13.2-pkce.9/release.py build `
  --source .build/pkce9-release/source --cache-dir .build/performance-cache `
  --output dist/pkce9
```

`inspect-frontend.mjs` 是本版冻结资产清单时使用的已有 Babel parser 检查器，不执行 bundle，
不安装依赖；正常使用已固定清单准备/构建不要求再次运行它。`source-files.json` 固定完整展开源码，
包括测试与公开 dist，拒绝未列入的本地运行文件或依赖目录。

## 对应源码与版本绑定

代码提交前只能生成显式 `.candidate.tar.gz`，其 receipt 标记 `publishable:false`、无 integration commit。
代码提交后指定准确 SHA 才能生成正式对应源码；精确 allowlist 必须与该提交逐字相同。
两份其他工作中的文档只从 Git 已提交快照取值，不混入未提交内容。源码包不含 .build、node_modules、
运行环境、真实身份、业务数据库、密钥或日志。

```powershell
python releases/v0.13.2-pkce.9/release.py package `
  --source .build/pkce9-release/source `
  --output dist/new-api-v0.13.2-pkce.9-corresponding-source.tar.gz `
  --build-receipt dist/pkce9/build-receipt.json `
  --code-commit VERIFIED_40_CHARACTER_COMMIT
```

公开 release/tag、归档、运行镜像标签/ID、应用版本和 source revision 必须对应同一批准提交。
打包还直接读取最终 Linux ELF 中的真实 embed 文件表，逐份校验公开资产，包含下划线模块。
`Dockerfile.runtime` 只封装已构建二进制，记录固定版本与真实 SOURCE_REVISION；它不编译或下载依赖。
本机不启动 Docker Desktop。需要时在已批准发布窗口，用现有服务器 Docker 将已验二进制封装成新镜像。

## 发布与恢复

image-only helper 只更新已核目标 `newapi` 的 image/build；不写环境、挂载或秘密，不修改其他服务。
切换前保留当前 pkce.8 镜像/二进制/服务配置及一致恢复备份；切换后核 `/api/status`、静态模块、
镜像/版本/二进制以及原开关与数据绑定，不调用真实 OAuth 或模型。
失败按同一状态记录恢复原 pkce.8 image/build，不恢复旧数据库、不清账务或凭据。
这里不声称具备请求排空或完整异步任务 flush。

服务器清理仅能先盘点本产品且未被引用的临时物、镜像或缓存。当前、候选和恢复版本、业务数据、
备份、密钥、日志、活跃服务及共享构建缓存一律不自动删除；删除清单另由负责人确认。
