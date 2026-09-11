/**
 * 프로브 — 대시보드 '생성' 버튼과 **같은 길**로 요청 하나를 대기열에 넣는다(돈이 나간다).
 * 0911 사고 요청과 같은 스펙(코 필러·셀카형·실제·1장)으로 재현 확인용.
 *
 *   node tools/_probe_genreq_0911.mjs --dry     # 무엇을 넣을지만
 *   node tools/_probe_genreq_0911.mjs           # 실제로 넣는다
 */
import path from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DRY = process.argv.includes('--dry');

function blobToken() {
  const f = path.join(ROOT, 'cloud', '.env.local');
  if (!existsSync(f)) return null;
  for (const line of readFileSync(f, 'utf8').split(/\r?\n/)) {
    const m = /^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/.exec(line);
    if (m) return m[1];
  }
  return null;
}

const body = { treatment: 'filler_nose', mode: 'selfie', count: 1, cost_cap: 1, simulate: false };
console.log('넣을 요청:', JSON.stringify(body));
if (DRY) { console.log('--dry — 넣지 않았다'); process.exit(0); }

const token = blobToken();
if (!token) { console.error('Blob 토큰 없음'); process.exit(1); }
const GR = await import('../cloud/lib/genreq.mjs');
const r = await GR.create(token, body, { email: 'teemo@probe' }, null);
if (r.error) { console.error('실패 —', r.error); process.exit(1); }
console.log('요청 생성:', r.ok.id, r.ok.status);
