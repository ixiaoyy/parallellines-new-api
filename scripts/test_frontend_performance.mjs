import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';

// 复用现有 Babel/i18next，不安装工具；两个模块路径须由调用方明确提供。
const require = createRequire(import.meta.url);
const { parse } = require(process.env.BABEL_PARSER_PATH);
const i18next = require(process.env.I18NEXT_PATH);
const source = resolve(process.env.PERFORMANCE_SOURCE);
const baseline = resolve(process.env.PERFORMANCE_BASELINE);
const read = (root, file) => readFileSync(resolve(root, file), 'utf8');
const { createLocaleBackend } = await import(pathToFileURL(resolve(source, 'web/src/i18n/localeBackend.js')));
const ast = (root, file) => parse(read(root, file), { sourceType: 'module', plugins: ['jsx'] });

function walk(value, visit) {
  if (!value || typeof value !== 'object') return;
  if (typeof value.type === 'string') visit(value);
  for (const child of Object.values(value)) {
    if (Array.isArray(child)) child.forEach((item) => walk(item, visit));
    else if (child && typeof child === 'object') walk(child, visit);
  }
}

function routeContracts(root) {
  const routes = [];
  walk(ast(root, 'web/src/App.jsx'), (node) => {
    if (node.type !== 'JSXElement' || node.openingElement.name.name !== 'Route') return;
    const path = node.openingElement.attributes.find((item) => item.name?.name === 'path').value.value;
    const components = [];
    walk(node, (child) => {
      if (child.type === 'JSXOpeningElement' && !['Route', 'Suspense', 'Loading'].includes(child.name.name)) components.push(child.name.name);
    });
    routes.push({ path, components });
  });
  return routes;
}

test('全部路由、深链接参数、权限守卫和页面对应关系保持原值', () => {
  assert.deepEqual(routeContracts(source), routeContracts(baseline));
});

test('页面改为 lazy 导入，等待边界覆盖原本没有 Suspense 的后台路由', () => {
  const app = ast(source, 'web/src/App.jsx');
  for (const node of app.program.body.filter((item) => item.type === 'ImportDeclaration')) {
    assert.ok(!node.source.value.startsWith('./pages/') || ['./pages/NotFound', './pages/Forbidden'].includes(node.source.value));
    assert.ok(!node.source.value.startsWith('./components/auth/'));
  }
  let lazyCount = 0;
  let coveredRoutes = false;
  walk(app, (node) => {
    if (node.type === 'CallExpression' && node.callee.name === 'lazy') lazyCount++;
    if (node.type === 'JSXElement' && node.openingElement.name.name === 'Suspense') {
      coveredRoutes ||= node.children.some((child) => child.type === 'JSXElement' && child.openingElement.name.name === 'Routes');
    }
  });
  assert.equal(lazyCount, 28);
  assert.ok(coveredRoutes);
  ast(source, 'web/src/index.jsx');
  assert.match(read(source, 'web/src/index.jsx'), /<React\.Suspense fallback=\{<Loading \/>\}>/);
});

test('只有中文回退静态加载，另外六种既有语言都有按需入口', () => {
  const config = ast(source, 'web/src/i18n/i18n.js');
  const imports = config.program.body.filter((item) => item.type === 'ImportDeclaration' && item.source.value.includes('/locales/'));
  assert.deepEqual(imports.map((item) => item.source.value), ['./locales/zh-CN.json']);
  const text = read(source, 'web/src/i18n/i18n.js');
  for (const language of ['en', 'fr', 'zh-TW', 'ru', 'ja', 'vi']) assert.ok(text.includes(`import('./locales/${language}.json')`));
});

test('以目标版本 i18next 验证切换、资源复用和缺词中文回退', async () => {
  let calls = 0;
  const instance = i18next.createInstance();
  instance.use(createLocaleBackend({ en: async () => { calls++; return { default: { translation: { greeting: 'hello' } } }; } }));
  await instance.init({ lng: 'en', fallbackLng: 'zh-CN', supportedLngs: ['en', 'zh-CN'], load: 'currentOnly', partialBundledLanguages: true, resources: { 'zh-CN': { translation: { greeting: '你好', fallback: '中文回退' } } } });
  assert.equal(instance.t('greeting'), 'hello');
  assert.equal(instance.t('fallback'), '中文回退');
  await instance.changeLanguage('zh-CN');
  assert.equal(instance.t('greeting'), '你好');
  await instance.changeLanguage('en');
  assert.equal(calls, 1);
});

test('加载失败或资源缺命名空间时完成失败边界，仍可显示中文', async () => {
  for (const load of [async () => { throw new Error('offline'); }, async () => ({ default: {} })]) {
    const instance = i18next.createInstance();
    instance.use(createLocaleBackend({ fr: load }));
    await instance.init({ lng: 'fr', fallbackLng: 'zh-CN', supportedLngs: ['fr', 'zh-CN'], load: 'currentOnly', partialBundledLanguages: true, resources: { 'zh-CN': { translation: { greeting: '你好' } } } });
    assert.equal(instance.t('greeting'), '你好');
    assert.ok(instance.isInitialized);
  }
});
