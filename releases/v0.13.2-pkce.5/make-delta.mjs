import fs from 'node:fs';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
const [basePath, targetPath, outPath, baseSha, targetSha] = process.argv.slice(2);
if (!targetSha || !/^[a-f0-9]{64}$/.test(baseSha) || !/^[a-f0-9]{64}$/.test(targetSha))
  throw Error('Usage: node make-delta.mjs BASE TARGET OUTPUT EXPECTED_BASE_SHA EXPECTED_TARGET_SHA');
const base = fs.readFileSync(basePath), target = fs.readFileSync(targetPath);
const hash = b => crypto.createHash('sha256').update(b).digest('hex');
if (hash(base) !== baseSha || hash(target) !== targetSha) throw Error('Frozen binary SHA mismatch');
const size = 64, mod = 65521, blocks = new Map();
function adler(b, p) {
  let a = 1, s = 0;
  for (let i = p; i < p + size; i++) { a += b[i]; s += a; }
  return [a % mod, s % mod];
}
const key = (a, b) => ((b << 16) | a) >>> 0;
for (let p = 0; p + size <= base.length; p += size) {
  const [a, b] = adler(base, p), k = key(a, b), list = blocks.get(k) ?? [];
  // Bound pathological collision search without trusting the weak checksum.
  if (list.length < 32) list.push(p);
  blocks.set(k, list);
}
const ops = [];
let p = 0, start = 0, [a, b] = adler(target, 0);
while (p + size <= target.length) {
  const options = blocks.get(key(a, b));
  let match = -1;
  if (options) match = options.find(v => base.subarray(v, v + size).equals(target.subarray(p, p + size))) ?? -1;
  if (match >= 0) {
    if (start < p) ops.push(['i', target.subarray(start, p).toString('base64')]);
    let length = size;
    while (match + length < base.length && p + length < target.length && base[match + length] === target[p + length]) length++;
    const last = ops.at(-1);
    if (last?.[0] === 'c' && last[1] + last[2] === match) last[2] += length;
    else ops.push(['c', match, length]);
    p += length; start = p;
    if (p + size <= target.length) [a, b] = adler(target, p);
  } else {
    if (p + size < target.length) {
      a = (a - target[p] + target[p + size] + mod) % mod;
      b = (b - size * target[p] + a - 1) % mod;
      if (b < 0) b += mod;
    }
    p++;
  }
}
if (start < target.length) ops.push(['i', target.subarray(start).toString('base64')]);
// Relocated machine code often differs by a few address bytes. Store these
// bounded literals as XOR against the preceding matched base position.
let basePosition = 0;
const compactOps = ops.map(op => {
  if (op[0] === 'c') { basePosition = op[1] + op[2]; return op; }
  const literal = Buffer.from(op[1], 'base64');
  if (basePosition + literal.length > base.length) return op;
  const difference = Buffer.allocUnsafe(literal.length), offset = basePosition;
  for (let n = 0; n < literal.length; n++) difference[n] = literal[n] ^ base[basePosition + n];
  basePosition += literal.length;
  return ['x', offset, difference.toString('base64')];
});
const rebuilt = Buffer.concat(compactOps.map(op => {
  if (op[0] === 'c') return base.subarray(op[1], op[1] + op[2]);
  if (op[0] === 'i') return Buffer.from(op[1], 'base64');
  const difference = Buffer.from(op[2], 'base64');
  for (let n = 0; n < difference.length; n++) difference[n] ^= base[op[1] + n];
  return difference;
}));
if (!rebuilt.equals(target) || hash(rebuilt) !== targetSha) throw Error('Local reconstruction mismatch');
const delta = { format: 'pl-bytecopy-xor-v1', base_sha256: baseSha, target_sha256: targetSha, base_size: base.length, target_size: target.length, ops: compactOps };
const archive = zlib.gzipSync(Buffer.from(JSON.stringify(delta)), { level: 9 });
fs.writeFileSync(outPath, archive, { flag: 'wx' });
const evidence = { delta_bytes: archive.length, delta_sha256: hash(archive), base_sha256: baseSha, target_sha256: targetSha,
  operations: ops.length, copied_bytes: ops.filter(v => v[0] === 'c').reduce((s, v) => s + v[2], 0), local_bytewise_verified: true };
fs.writeFileSync(outPath + '.evidence.json', JSON.stringify(evidence, null, 2) + '\n', { flag: 'wx' });
console.log(JSON.stringify(evidence));
