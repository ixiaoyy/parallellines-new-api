# API 本地性能构建

本配方以已发布的 `v0.13.2-pkce.8` 对应源码为输入，应用独立前端性能补丁。
输出版本是 `v0.13.2-pkce.8-local-performance`，**未发布，不可直接替代当前线上镜像**。
已发布的 release 锁、资产清单和原构建入口保持不动；下一次正式 release 应显式接入本补丁。

## 准备和构建

先准备全新目录，归档摘要必须与 pkce.8 的 `source-archive.json` 一致：

```powershell
python scripts/build-performance-local.py prepare `
  --base-archive .build/free-chat-deploy-20261102/new-api-v0.13.2-pkce.8-corresponding-source.tar.gz `
  --destination .build/performance-local
```

需要既有 Bun 1.4.4；完整二进制还需要既有 Go 1.26.1。工具链不全局安装，不隐式下载。
在新目录 `source/web` 按原 `bun.lock` 恢复依赖时使用 `bun install --frozen-lockfile`，不更新锁。
然后回到本仓库运行：

```powershell
python scripts/build-performance-local.py build `
  --source .build/performance-local/source `
  --cache-dir .build/performance-cache `
  --output-dir dist/performance-local
```

只验证前端可加 `--frontend-only`，不要求 Go。
`--web-deps` 可选地链接另一份已按**同一锁**恢复的 `node_modules`，不会安装或修复依赖。
输出目录必须不存在；失败后检查具体产物，不覆盖已有成果。

## 缓存和边界

- Go 优先复用进程显式 `GOCACHE` / `GOMODCACHE`，其次复用当前 Go 的既有默认目录；
  无 Go 时只准备 `--cache-dir` 下的目录。记录实际路径，避免每个新发布目录都冷编译。
- 设置 `GOTOOLCHAIN=local`、`GOPROXY=off`。缺失工具链或模块明确失败；需要恢复依赖时
  单独按固定锁处理，不由构建失败触发隐式安装。
- 前端缓存身份涵盖完整 Web 源码、配置和锁，不包含 `node_modules` / `dist`。
  首次必须构建本次修改；后续相同身份、且缓存产物摘要一致才复用。旧 pkce.8 前端不能
  充当本次优化成果。缓存不完整或被改动时明确报出具体目录，人工核对后仅清理该缓存键。
- `build-receipt.json` 标记未发布，记录缓存命中、分段耗时、入口 JS/CSS 的原始和逐文件
  gzip 字节。只统计 HTML 入口及 modulepreload，不能替代实际路由下载、FCP/LCP 或线上测速。
- Nginx 本地配置只允许 `200` 的指纹 `/assets/` 长缓存。HTML、鉴权、用户资料、余额、
  个性模型列表、生成和 SSE 均 `no-store`；不配置全站 Cache Everything，不开启代理响应缓存。
  这只是源站边界，不代表已修改 CDN 控制台或已在 CDN 命中。

## 离线回归

```powershell
python -m unittest discover -s scripts -p test_build_performance_local.py -v
```

`scripts/test_frontend_performance.mjs` 使用既有 Babel parser 和目标版本 i18next 23.16.8：
设置 `PERFORMANCE_SOURCE`、`PERFORMANCE_BASELINE`、`BABEL_PARSER_PATH`、`I18NEXT_PATH` 后
运行 `node --test scripts/test_frontend_performance.mjs`。它检查路由/权限映射、语言切换与失败回退；
不冒充完整 React 渲染或生产 OAuth 验收。

真实构建的隔离浏览器烟测使用 `scripts/smoke-performance-local.mjs`：设置
`PLAYWRIGHT_PATH` 为已有 Playwright 包路径，`PERFORMANCE_DIST` 为输出的 `web` 目录，
`PERFORMANCE_EVIDENCE` 为截图和结果目录，再运行 `node scripts/smoke-performance-local.mjs`。
它只启动临时回环静态服务，API 全部使用合成响应，外部网络请求一律阻断；完成时关闭服务和浏览器。
