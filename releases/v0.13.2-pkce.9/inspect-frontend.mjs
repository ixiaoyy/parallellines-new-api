// 只检查已验公开 dist；使用构建锁已有 Babel parser，不安装依赖或执行 bundle。
import { createHash } from 'node:crypto';
import { lstatSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { posix, resolve } from 'node:path';

const [distArgument, parserArgument, identity, outputArgument] = process.argv.slice(2);
if (!distArgument || !parserArgument || !/^[0-9a-f]{64}$/.test(identity || '') || !outputArgument) throw new Error('dist parser source-identity output are required');
const require = createRequire(import.meta.url);
const { parse } = require(resolve(parserArgument));
const dist = resolve(distArgument);
const files = {};
const contents = new Map();
const extensions = new Set(['png', 'webp', 'ico', 'html', 'txt', 'js', 'css', 'woff2', 'woff', 'ttf']);

function inventory(directory, prefix = '') {
  for (const name of readdirSync(directory).sort()) {
    const path = resolve(directory, name);
    const relative = prefix + name;
    const stat = lstatSync(path);
    if (stat.isSymbolicLink() || name.startsWith('.') || /(?:^|[._-])(?:env|secrets?|private|credentials?|backup|runtime)(?:[._-]|$)/i.test(name)) throw new Error('non-public asset: ' + relative);
    if (stat.isDirectory()) { inventory(path, relative + '/'); continue; }
    if (!stat.isFile() || !extensions.has(name.split('.').at(-1).toLowerCase())) throw new Error('unexpected public asset type: ' + relative);
    const data = readFileSync(path);
    files[relative] = { bytes: data.length, sha256: createHash('sha256').update(data).digest('hex') };
    if (/\.(?:js|css|html)$/.test(name)) contents.set(relative, data.toString('utf8'));
  }
}
inventory(dist);

const references = new Map();
const external = new Set();
const nonliteral = [];
function reference(from, value, kind, rootRelative = false) {
  if (!value || /^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(value)) { if (value) external.add(value); return; }
  const clean = value.split(/[?#]/, 1)[0];
  const target = clean.startsWith('/') ? posix.normalize(clean.slice(1)) : rootRelative ? posix.normalize(clean) : posix.normalize(posix.join(posix.dirname(from), clean));
  if (target.startsWith('../') || !files[target]) throw new Error(`missing public reference: ${from} -> ${value}`);
  references.set(`${from}\0${target}\0${kind}`, { from, target, kind });
}
function walk(node, from) {
  if (!node || typeof node !== 'object') return;
  if (['ImportDeclaration', 'ExportAllDeclaration', 'ExportNamedDeclaration'].includes(node.type) && node.source) reference(from, node.source.value, 'esm');
  if (node.type === 'ImportExpression') {
    if (node.source.type === 'StringLiteral') reference(from, node.source.value, 'dynamic-esm');
    else nonliteral.push({ from, offset: node.start });
  } else if (node.type === 'CallExpression' && node.callee?.type === 'Import') {
    if (node.arguments[0]?.type === 'StringLiteral') reference(from, node.arguments[0].value, 'dynamic-esm');
    else nonliteral.push({ from, offset: node.start });
  }
  // Vite 预加载映射中的 asset 字面量也必须可用，包含路由伴随的 CSS。
  if (node.type === 'StringLiteral' && /^\/?assets\/[A-Za-z0-9_.\/-]+\.(?:js|css|woff2?|ttf|png|webp|ico)$/.test(node.value)) reference(from, node.value, 'vite-asset', true);
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach((child) => walk(child, from));
    else if (value && typeof value === 'object') walk(value, from);
  }
}
for (const [from, code] of contents) {
  if (from.endsWith('.js')) walk(parse(code, { sourceType: 'module', createImportExpressions: true }), from);
  if (from.endsWith('.css')) {
    const css = code.replace(/\/\*[\s\S]*?\*\//g, '');
    for (const match of css.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^\s)]*))\s*\)/g)) reference(from, match[1] ?? match[2] ?? match[3], 'css-url');
    for (const match of css.matchAll(/@import\s+["']([^"']+)["']/g)) reference(from, match[1], 'css-import');
  }
  if (from.endsWith('.html')) {
    for (const match of code.matchAll(/(?:src|href)=["']([^"']+)["']/g)) reference(from, match[1], 'html');
  }
}
if (nonliteral.length) throw new Error('nonliteral dynamic imports require explicit review: ' + JSON.stringify(nonliteral));
const manifest = { schema: 1, public_assets_only: true, source_identity: identity, file_count: Object.keys(files).length, files, references: [...references.values()].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))), external_reference_count: external.size, nonliteral_dynamic_imports: nonliteral.length };
writeFileSync(resolve(outputArgument), JSON.stringify(manifest, null, 2) + '\n');
console.log(JSON.stringify({ files: manifest.file_count, references: manifest.references.length, nonliteral_dynamic_imports: 0, public_assets_only: true }));
