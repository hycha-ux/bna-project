// 클라우드 검수 원장(Blob reviews/)에 아직 PC 로 안 내려온 판정이 있는지 **읽기만** 한다 (2026-09-21).
//   node tools/_probe_cloud_reviews_0921.mjs [배치ID…]
// 쓰기·지우기 없음. 토큰 값은 출력하지 않는다(push-cloud 와 같은 로더).
import { overlay } from '../cloud/lib/reviews.mjs';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = readFileSync(path.join(ROOT, 'cloud', '.env.local'), 'utf8');
const m = env.match(/^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/m);
if (!m) { console.error('BLOB_READ_WRITE_TOKEN 없음'); process.exit(1); }
const want = process.argv.slice(2);
const map = await overlay(m[1]);
const keys = Object.keys(map || {});
console.log(`클라우드 검수 원장 ${keys.length}건`);
for (const k of keys) {
  if (want.length && !want.some((w) => k.startsWith(w))) continue;
  const r = map[k];
  console.log(k, r.pick, JSON.stringify(r.tags || []), r.updated_at);
}
