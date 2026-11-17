// 中英界面回归：只启动临时回环静态站；所有 API 和跨站请求均由浏览器夹具拦截。
// 用法：node scripts/check-interface-i18n.mjs <dist> <evidence-dir>
// --source-link-only 仅检查无需登录的中英源码入口，不重复原业务回归。
// --source-controls-only 仅检查语言控件的中英无障碍名称和当前源码链接。
// 复用现有 Playwright：PLAYWRIGHT_MODULE 指向已安装包，CHROMIUM_EXECUTABLE 可指定已有浏览器。
import assert from 'node:assert/strict';
import { createReadStream, existsSync, mkdirSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { extname, resolve, sep } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
assert.ok(process.argv[2] && process.argv[3], 'dist and evidence directory are required');
const dist = resolve(process.argv[2]), evidence = resolve(process.argv[3]);
mkdirSync(evidence, { recursive: true });
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const server = createServer((request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname;
  let file = resolve(dist, '.' + pathname);
  if (!file.startsWith(dist + sep) && file !== dist) return response.writeHead(403).end();
  if (!existsSync(file) || !statSync(file).isFile()) file = extname(pathname) ? '' : resolve(dist, 'index.html');
  if (!file) return response.writeHead(404).end();
  response.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream' });
  createReadStream(file).pipe(response);
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}) });
const results = [];
const sourceLinkOnly = process.argv.includes('--source-link-only');
const sourceControlsOnly = process.argv.includes('--source-controls-only');

/** 创建隔离浏览器夹具，参数控制浏览器语言、宽度、会话故障及原生登录模式；返回合成请求记录。 */
async function fixture({ locale = 'en-US', width = 1440, unavailable = false, native = false, user = null, footer = null } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 960 }, locale });
  if (user) await context.addInitScript(value => {
    if (!localStorage.getItem('user')) localStorage.setItem('user', JSON.stringify(value));
  }, user);
  if (footer !== null) await context.addInitScript(value => localStorage.setItem('footer_html', value), footer);
  const calls = [], errors = [], blocked = [];
  let recoveryStep = 0;
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === 'https://pingxingxian.space' && url.pathname === '/auth/unified/state') {
      const state = { type: 'pl:unified-session', version: 1, request_id: url.searchParams.get('request_id'), available: !unavailable, authenticated: false };
      return route.fulfill({ contentType: 'text/html', body: `<script>const state=${JSON.stringify(state)};const emit=()=>parent.postMessage(state,${JSON.stringify(origin)});addEventListener('message',emit);emit();<\/script>` });
    }
    if (url.origin !== origin) { blocked.push(url.href); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    calls.push({ method: route.request().method(), path: url.pathname, body: route.request().postDataJSON() });
    let data = [], success = true, message;
    if (url.pathname === '/api/status') data = { setup: true, main_unified_web_login_enabled: !native, system_name: 'New API', logo: '/logo.png', custom_oauth_providers: [], announcements: [] };
    else if (url.pathname === '/api/setup') data = { status: true };
    else if (url.pathname === '/api/oauth/pingxingxian/start') success = false;
    else if (url.pathname === '/api/user/root-recovery/login') { success = ++recoveryStep > 1; message = '恢复账号不可用'; data = { require_2fa: true }; }
    else if (url.pathname === '/api/user/self') data = user;
    else if (['/api/notice', '/api/home_page_content', '/api/about', '/api/user-agreement', '/api/privacy-policy'].includes(url.pathname)) data = '';
    return route.fulfill({ json: { success, data, ...(message ? { message } : {}) } });
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  return { context, page, calls, errors, blocked };
}

/** 通过实际顶栏菜单切换语言，不直接写浏览器偏好，验证真实交互入口。 */
async function switchLanguage(page, name) {
  await page.locator('header button[aria-label]').filter({ hasText: /EN|中文|繁中|FR|JA|RU|VI/ }).click();
  await page.getByRole('menuitem', { name, exact: true }).click();
  await page.getByRole('menuitem', { name, exact: true }).waitFor({ state: 'hidden' });
}

/** 保存截图并检查渲染/手机宽度；不以截图替代功能断言。 */
async function capture(fixture, name) {
  await fixture.page.waitForTimeout(250);
  assert.equal(await fixture.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `${name}: horizontal overflow`);
  assert.deepEqual(fixture.errors, [], `${name}: browser runtime errors`);
  await fixture.page.screenshot({ path: resolve(evidence, `${name}.png`), fullPage: true });
}

try {
  if (sourceControlsOnly) {
    for (const locale of ['en-US', 'zh-CN']) {
      const f = await fixture({ locale, width: locale === 'en-US' ? 1440 : 390 });
      await f.page.goto(origin + '/login');
      const caption = locale === 'en-US' ? 'Corresponding source' : '对应源码';
      const aria = locale === 'en-US' ? 'Change Language' : '切换语言';
      const language = f.page.getByRole('button', { name: aria, exact: true });
      const source = f.page.getByRole('link', { name: caption, exact: true });
      await language.waitFor();
      await source.waitFor();
      assert.equal(await language.getAttribute('title'), aria);
      assert.equal(await source.getAttribute('href'), 'https://github.com/ixiaoyy/parallellines-new-api/releases/tag/i18n-20261118');
      assert.deepEqual(f.errors, []);
      await language.screenshot({ path: resolve(evidence, `controls-${locale}-language.png`) });
      await source.screenshot({ path: resolve(evidence, `controls-${locale}-source.png`) });
      results.push({ case: `language aria and immutable source href, ${locale}`, passed: true });
      await f.context.close();
    }
  } else if (sourceLinkOnly) {
    for (const locale of ['en-US', 'zh-CN']) {
      for (const custom of [false, true]) {
        const f = await fixture({ locale, width: locale === 'en-US' ? 1440 : 390, footer: custom ? '<span>Fixture custom footer</span>' : null });
        await f.page.goto(origin + '/login');
        const caption = locale === 'en-US' ? 'Corresponding source' : '对应源码';
        const link = f.page.getByRole('link', { name: caption, exact: true });
        await link.waitFor();
        assert.equal(await link.getAttribute('href'), 'https://github.com/ixiaoyy/parallellines-new-api/releases/tag/i18n-20261118');
        assert.equal(await link.getAttribute('target'), '_blank');
        assert.equal(await link.getAttribute('rel'), 'noopener noreferrer');
        assert.equal(await f.page.locator('.custom-footer').count(), custom ? 1 : 0);
        assert.equal(await f.page.locator('a[href="https://github.com/QuantumNous/new-api"]').count(), 1);
        assert.equal(await f.page.locator('input[type=password]').count(), 0);
        assert.ok(!f.calls.some(call => call.path === '/api/oauth/pingxingxian/start'));
        await link.scrollIntoViewIfNeeded();
        await capture(f, `source-link-${locale}-${custom ? 'custom' : 'default'}`);
        results.push({ case: `anonymous source link, ${locale}, ${custom ? 'custom' : 'default'} footer`, passed: true });
        await f.context.close();
      }
    }
  } else {
  for (const width of [1440, 390]) {
    const f = await fixture({ width });
    await f.page.goto(origin + '/login');
    await f.page.getByRole('button', { name: 'Sign in with ParallelLines', exact: true }).waitFor({ timeout: 10000 }).catch(async error => {
      await f.page.screenshot({ path: resolve(evidence, 'failed-initial.png'), fullPage: true });
      console.log(await f.page.evaluate(() => ({ body: document.body.innerText, language: window.__i18n?.language, resolved: window.__i18n?.resolvedLanguage, saved: localStorage.getItem('i18nextLng') })), f.calls, f.errors);
      throw error;
    });
    assert.equal(await f.page.locator('input[type=password]').count(), 0);
    assert.equal(await f.page.evaluate(() => document.documentElement.lang), 'en');
    await capture(f, `login-en-${width}`);
    await switchLanguage(f.page, '简体中文');
    await f.page.getByRole('button', { name: '使用平行线账号登录', exact: true }).waitFor();
    await capture(f, `login-zh-${width}`);
    await f.page.goto(origin + '/login?lng=en');
    await f.page.getByRole('button', { name: '使用平行线账号登录', exact: true }).waitFor();
    assert.equal(await f.page.evaluate(() => localStorage.getItem('i18nextLng')), 'zh-CN');
    await switchLanguage(f.page, 'English');
    await f.page.reload();
    await f.page.getByRole('button', { name: 'Sign in with ParallelLines', exact: true }).waitFor();
    await f.page.getByRole('button', { name: 'Sign in with ParallelLines', exact: true }).click();
    await f.page.getByRole('alert').filter({ hasText: 'ParallelLines sign-in is temporarily unavailable' }).waitFor();
    assert.equal(f.calls.filter(x => x.path === '/api/oauth/pingxingxian/start').length, 1);
    assert.ok(!f.calls.some(x => x.path === '/api/user/login'));
    results.push({ case: `en-US first visit, manual zh/en, refresh, saved choice beats URL, login error, ${width}px`, passed: true });
    await f.context.close();
  }
  const zh = await fixture({ locale: 'zh-CN' });
  await zh.page.goto(origin + '/login');
  await zh.page.getByRole('button', { name: '使用平行线账号登录', exact: true }).waitFor();
  results.push({ case: 'Chinese browser first visit remains Chinese', passed: true });
  await zh.context.close();

  const failure = await fixture({ unavailable: true });
  await failure.page.goto(origin + '/console/token');
  await failure.page.getByRole('status').filter({ hasText: 'Unable to confirm your sign-in status' }).waitFor();
  assert.ok(!failure.calls.some(x => x.path.startsWith('/api/token')));
  await capture(failure, 'boundary-error-en');
  await switchLanguage(failure.page, '简体中文');
  await failure.page.getByRole('status').filter({ hasText: '暂时无法确认登录状态' }).waitFor();
  results.push({ case: 'session failure stays blocked and translates without restarting authentication', passed: true });
  await failure.context.close();

  const recovery = await fixture({ width: 390 });
  await recovery.page.goto(origin + '/root-recovery');
  await recovery.page.getByRole('heading', { name: 'Administrator sign in' }).waitFor();
  await recovery.page.getByLabel('Account', { exact: true }).fill('synthetic-root');
  await recovery.page.getByLabel('Password', { exact: true }).fill('synthetic-password');
  await recovery.page.locator('form button[type=submit]').click();
  await recovery.page.getByRole('alert').filter({ hasText: 'Recovery account is unavailable' }).waitFor();
  await recovery.page.locator('form button[type=submit]').click();
  await recovery.page.getByLabel('Verification or backup code', { exact: true }).waitFor();
  await capture(recovery, 'recovery-2fa-en-mobile');
  await switchLanguage(recovery.page, '简体中文');
  await recovery.page.getByLabel('验证码或备用码', { exact: true }).waitFor();
  assert.ok(recovery.calls.filter(x => x.path.startsWith('/api/user/root-recovery')).every(x => x.path === '/api/user/root-recovery/login'));
  results.push({ case: 'private recovery English labels, backend error, original 2FA state survives Chinese switch', passed: true });
  await recovery.context.close();

  const user = { id: 7, username: 'synthetic-user', role: 1, setting: JSON.stringify({ language: 'en' }) };
  const account = await fixture({ native: true, user });
  await account.page.goto(origin + '/');
  await account.page.locator('header button[aria-label]').filter({ hasText: 'EN' }).waitFor();
  await switchLanguage(account.page, '简体中文');
  await account.page.waitForFunction(() => JSON.parse(JSON.parse(localStorage.getItem('user')).setting).language === 'zh-CN');
  assert.ok(account.calls.some(x => x.method === 'PUT' && x.path === '/api/user/self' && x.body.language === 'zh-CN'));
  await account.page.reload();
  await account.page.locator('header button[aria-label]').filter({ hasText: '中文' }).waitFor();
  results.push({ case: 'native logged-in language save and refresh retain original API contract', passed: true });
  await account.context.close();
  }
  writeFileSync(resolve(evidence, 'results.json'), JSON.stringify({ productionRequests: 0, results }, null, 2) + '\n');
  console.log(JSON.stringify(results, null, 2));
} finally {
  await browser.close();
  await new Promise(done => server.close(done));
}
