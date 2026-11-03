import assert from 'node:assert/strict';
import { createReadStream, existsSync, mkdirSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { extname, resolve, sep } from 'node:path';

// 仅服务本次构建目录；所有 API 都是合成响应，浏览器禁止访问外部主机。
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_PATH);
const dist = resolve(process.env.PERFORMANCE_DIST);
const evidence = resolve(process.env.PERFORMANCE_EVIDENCE);
mkdirSync(evidence, { recursive: true });
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const server = createServer((request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
  let file = resolve(dist, '.' + pathname);
  if (!(file === dist || file.startsWith(dist + sep))) { response.writeHead(403).end(); return; }
  if (!existsSync(file) || !statSync(file).isFile()) file = extname(pathname) ? '' : resolve(dist, 'index.html');
  if (!file || !existsSync(file)) { response.writeHead(404).end(); return; }
  response.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
  createReadStream(file).pipe(response);
});
await new Promise((done) => server.listen(0, '127.0.0.1', done));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
const results = [];
const status = { setup: true, version: 'v0.13.2-pkce.8-local-performance', system_name: 'New API · Local verification', logo: '/logo.png', password_login_enabled: true, custom_oauth_providers: [], announcements: [] };

async function contextFor(user = null, viewport = { width: 1440, height: 1000 }) {
  const context = await browser.newContext({ viewport, locale: 'zh-CN' });
  await context.addInitScript((user) => { localStorage.setItem('i18nextLng', 'zh-CN'); if (user) localStorage.setItem('user', JSON.stringify(user)); }, user);
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== base) { await route.abort(); return; }
    if (url.pathname.startsWith('/api/')) {
      assert.equal(route.request().method(), 'GET', 'smoke must not submit mutations');
      const data = url.pathname === '/api/status' ? status : url.pathname === '/api/user/self' ? user : url.pathname === '/api/notice' ? '' : [];
      await route.fulfill({ json: { success: true, data } });
      return;
    }
    await route.continue();
  });
  return context;
}

try {
  const context = await contextFor();
  const page = await context.newPage();
  const errors = [];
  const requested = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => requested.push(new URL(request.url()).pathname));
  await page.goto(base + '/login');
  await page.locator('input[name="username"]').waitFor();
  await page.waitForFunction(() => document.querySelector('header img[alt="logo"]')?.classList.contains('opacity-100'));
  await page.screenshot({ path: resolve(evidence, 'login-zh.png'), fullPage: true });
  assert.ok(!requested.some((name) => /\/assets\/(en|fr|ja|ru|vi|zh-TW)-/.test(name)), 'Chinese cold load should not fetch other languages');
  await page.evaluate(() => window.__i18n.changeLanguage('en'));
  const english = await page.evaluate(() => window.__i18n.t('用户名或邮箱'));
  assert.notEqual(english, '用户名或邮箱');
  await page.getByText(english, { exact: true }).waitFor();
  assert.ok(requested.some((name) => /\/assets\/en-/.test(name)));
  await page.screenshot({ path: resolve(evidence, 'login-en.png'), fullPage: true });
  await page.route('**/assets/fr-*.js', (route) => route.abort());
  await page.evaluate(() => window.__i18n.changeLanguage('fr'));
  await page.locator('input[name="username"]').waitFor();
  assert.deepEqual(errors, []);
  results.push({ case: 'Chinese cold login; English on-demand switch; failed French chunk falls back to Chinese', passed: true, pageErrors: errors });
  await context.close();

  for (const [name, user, expected] of [['anonymous', null, '/login'], ['ordinary-user', { id: 999, username: 'local-smoke', role: 1, setting: '{}' }, '/forbidden']]) {
    const context = await contextFor(user);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(base + '/console/models');
    await page.waitForURL(base + expected);
    if (expected === '/login') await page.locator('input[name="username"]').waitFor();
    else await page.getByText('您无权访问此页面，请联系管理员', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    results.push({ case: name + ' admin deep link guard', passed: true, finalPath: expected });
    await context.close();
  }

  const mobile = await contextFor(null, { width: 390, height: 844 });
  const mobilePage = await mobile.newPage();
  await mobilePage.goto(base + '/login');
  await mobilePage.locator('input[name="username"]').waitFor();
  await mobilePage.waitForFunction(() => document.querySelector('header img[alt="logo"]')?.classList.contains('opacity-100'));
  assert.ok(await mobilePage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  await mobilePage.screenshot({ path: resolve(evidence, 'login-mobile.png'), fullPage: true });
  results.push({ case: '390px mobile login without horizontal overflow', passed: true });
  await mobile.close();
  writeFileSync(resolve(evidence, 'browser-smoke.json'), JSON.stringify({ origin: base, realApiOrModelCalls: false, results }, null, 2) + '\n');
  console.log(JSON.stringify(results, null, 2));
} finally {
  await browser.close();
  await new Promise((done) => server.close(done));
}
