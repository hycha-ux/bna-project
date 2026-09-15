// 클라우드 스냅샷 미러 — 위클리 캡처용. Blob(snapshot.json + files/**)을 읽어
// web/ 화면을 실데이터로 로컬에서 띄운다 (로그인 없음, 쓰기 없음, 127.0.0.1 전용).
// 사용: node tools/cloud_mirror.mjs [port=8798]
//   토큰은 cloud/.env.local 의 BLOB_READ_WRITE_TOKEN (push-cloud 와 같은 파일).
//   없으면 사람이 한 번: `cd cloud && npx vercel env pull .env.local`
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { get } from '../cloud/node_modules/@vercel/blob/dist/index.js';
import * as REV from '../cloud/lib/reviews.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = Number(process.argv[2]) || 8798;
const envf = path.join(ROOT, 'cloud', '.env.local');
if (!existsSync(envf)) { console.error('cloud/.env.local 이 없다 — `cd cloud && npx vercel env pull .env.local`'); process.exit(1); }
const TOKEN = (/^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/m.exec(readFileSync(envf, 'utf8')) || [])[1];
if (!TOKEN) { console.error('BLOB_READ_WRITE_TOKEN 없음'); process.exit(1); }

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.json': 'application/json' };
async function blob(p) {
  const r = await get(p, { access: 'private', token: TOKEN });
  if (!r || r.statusCode !== 200 || !r.stream) return null;
  const chunks = []; for await (const c of r.stream) chunks.push(Buffer.from(c));
  return Buffer.concat(chunks);
}
let CACHE = { at: 0, snap: null };
async function snapshot() {
  if (CACHE.snap && Date.now() - CACHE.at < 60_000) return CACHE.snap;
  const b = await blob('snapshot.json'); if (!b) return null;
  CACHE = { at: Date.now(), snap: JSON.parse(b.toString('utf8')) }; return CACHE.snap;
}
const json = (res, code, v) => { res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' }); res.end(JSON.stringify(v)); };

createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x'); const p = url.pathname;
  if (req.method !== 'GET') return json(res, 405, { error: '미러는 읽기 전용' });
  if (p.startsWith('/files/')) {
    const b = await blob('files/' + p.slice(7)); if (!b) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'content-type': MIME[path.extname(p).toLowerCase()] || 'application/octet-stream' }); return res.end(b);
  }
  if (p.startsWith('/api/')) {
    const snap = await snapshot(); if (!snap) return json(res, 503, { error: '스냅샷 없음' });
    const ov = {};
    if (p === '/api/config') return json(res, 200, { ...snap.config, readonly: true, cloud: true, no_create: true, gen_request: false, cloud_msg: '미러(읽기 전용)' });
    if (p === '/api/queue') return json(res, 200, snap.queue);
    if (p === '/api/gen_requests') return json(res, 200, { requests: [], status_ko: {} });
    if (p === '/api/batches') return json(res, 200, REV.applyToList(snap.batches, ov, snap.items));
    if (p === '/api/library') return json(res, 200, REV.applyToLibrary(snap.library, ov, snap.items));
    if (p === '/api/lessons') return json(res, 200, snap.lessons ? { ...snap.lessons, sync: { at: snap.generated_ts, at_text: snap.generated_at, interval_sec: 600 }, pending_promotions: [], pending_handoffs: [], no_promote: true } : { error: '학습 집계 없음' });
    if (p === '/api/overview') { const o = snap.overview || {}; const want = url.searchParams.get('days') || '14'; return json(res, 200, o[want] || o[Object.keys(o)[0]] || {}); }
    let m = /^\/api\/batches\/([^/]+)\/progress$/.exec(p); if (m) return json(res, 200, (snap.progress || {})[m[1]] || {});
    m = /^\/api\/batches\/([^/]+)$/.exec(p); if (m) { const v = (snap.items || {})[m[1]]; return v ? json(res, 200, REV.applyToBatch(v, ov)) : json(res, 404, { error: '없는 배치' }); }
    return json(res, 404, { error: '없는 경로: ' + p });
  }
  let f = path.join(ROOT, 'web', p === '/' ? 'index.html' : p);
  if (!f.startsWith(path.join(ROOT, 'web')) || !existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': MIME[path.extname(f).toLowerCase()] || 'application/octet-stream' }); res.end(readFileSync(f));
}).listen(PORT, '127.0.0.1', () => console.log('cloud mirror http://127.0.0.1:' + PORT));
