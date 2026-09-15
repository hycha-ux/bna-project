/**
 * 진행 실시간 라우트 스모크 — `node cloud/liveprog-smoke.mjs [배치ID]` (2026-09-15 티모)
 *
 * seedbank-smoke 와 같은 방식: 라이브 Blob 을 읽고 세션만 로컬 비밀값으로 위조해 app.js 를 이 PC 에서 띄운다.
 * 보는 것: ①무로그인 401 ②progress 라우트가 실시간 파일을 고르고 live 필드를 붙이나 ③목록 라우트가 안 죽나
 *          ④형식이 틀린 ID 는 실시간 파일을 안 찾는다(404 또는 스냅샷 폴백).
 * ⚠ 읽기 전용이다 — Blob 에 쓰지 않는다. 실시간 파일은 `push-progress.mjs` 로 먼저 올려 둬야 ②가 used=true 다.
 */
import http from 'node:http';
import { readFileSync } from 'node:fs';
process.env.AUTH_SECRET = 'local-smoke-secret';
for (const line of readFileSync(new URL('.env.local', import.meta.url), 'utf8').split(/\r?\n/)) {
  const m = /^([A-Z_]+)\s*=\s*"?([^"\r\n]+)"?/.exec(line);
  if (m) process.env[m[1]] = m[2];
}
const ID = process.argv[2] || '20260915-104807-dbf2';
const { signSession, loadUsers } = await import('./lib/auth.mjs');
const app = (await import('./api/app.js')).default;
const store = await loadUsers(process.env.BLOB_READ_WRITE_TOKEN);
const someone = Object.keys(store.users).find((e) => !store.users[e].blocked);

const srv = http.createServer(app);
await new Promise((r) => srv.listen(0, r));
const port = srv.address().port;
const get = async (p, email) => {
  const h = email ? { cookie: 'bna_s=' + encodeURIComponent(signSession(email, process.env.AUTH_SECRET)) } : {};
  const r = await fetch(`http://127.0.0.1:${port}${p}`, { headers: h, redirect: 'manual' });
  let j = null; const t = await r.text(); try { j = JSON.parse(t); } catch { /* html */ }
  return { status: r.status, j };
};

const fails = [];
const ok = (c, label) => { console.log((c ? 'PASS  ' : 'FAIL  ') + label); if (!c) fails.push(label); };
const anon = await get(`/api/batches/${ID}/progress`);
ok(anon.status === 401 || anon.status === 302, `무로그인은 막힌다 — ${anon.status}`);
const pr = await get(`/api/batches/${ID}/progress`, someone);
ok(pr.status === 200 && pr.j?.summary && pr.j?.live, `진행 라우트 200 + live 필드 — ${pr.status} ${JSON.stringify(pr.j?.live)}`);
ok(pr.j?.live?.used === true && Number.isFinite(pr.j?.live?.age_s), '올려 둔 실시간 파일을 골랐다(used=true, 신호 나이 있음)');
const ls = await get('/api/batches', someone);
ok(ls.status === 200 && Array.isArray(ls.j), `목록 라우트 200 — ${ls.j?.length}건`);
const bad = await get('/api/batches/..%2Fsnapshot/progress', someone);
ok(bad.status === 404 || bad.status === 200, `형식이 틀린 ID 도 서버를 안 죽인다 — ${bad.status}`);
srv.close();
console.log(fails.length ? `실패 ${fails.length}건` : '전부 통과');
process.exit(fails.length ? 1 : 0);
