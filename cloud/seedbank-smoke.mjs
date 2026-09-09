/**
 * 씨앗 은행 라우트 스모크 — `node cloud/seedbank-smoke.mjs`
 *
 * 라이브 Blob 을 읽는다(계정 원장·씨앗 목록). 세션만 로컬 비밀값으로 위조해
 * 배포 없이 관문을 확인한다 — 실제 배포본의 AUTH_SECRET 은 건드리지 않는다.
 *
 * 보는 것: ①무로그인 401 ②관리자 200 ③구성원 403 ④`..` 경로 거슬러 오르기 차단
 *          ⑤관리자 홈에만 탭이 얹히는지.
 * ⚠ 읽기 전용이다 — 계정·씨앗을 고치지 않는다.
 */
import http from 'node:http';
import { readFileSync } from 'node:fs';
process.env.AUTH_SECRET = 'local-smoke-secret';
for (const line of readFileSync(new URL('.env.local', import.meta.url), 'utf8').split(/\r?\n/)) {
  const m = /^([A-Z_]+)\s*=\s*"?([^"\r\n]+)"?/.exec(line);
  if (m) process.env[m[1]] = m[2];
}
const { signSession, loadUsers } = await import('./lib/auth.mjs');
const app = (await import('./api/app.js')).default;

const store = await loadUsers(process.env.BLOB_READ_WRITE_TOKEN);
const emails = Object.keys(store.users);
console.log('계정:', emails.map(e => e + '(' + store.users[e].role + ')').join(', ') || '(없음)');
const admin = emails.find(e => store.users[e].role === 'admin');
const member = emails.find(e => store.users[e].role !== 'admin');

const srv = http.createServer(app);
await new Promise(r => srv.listen(0, r));
const port = srv.address().port;
const raw = async (p, email) => {
  const h = email ? { cookie: 'bna_s=' + encodeURIComponent(signSession(email, process.env.AUTH_SECRET)) } : {};
  const r = await fetch(`http://127.0.0.1:${port}${p}`, { headers: h, redirect: 'manual' });
  return { status: r.status, text: await r.text() };
};
const hit = async (p, email) => {
  const h = email ? { cookie: 'bna_s=' + encodeURIComponent(signSession(email, process.env.AUTH_SECRET)) } : {};
  const r = await fetch(`http://127.0.0.1:${port}${p}`, { headers: h, redirect: 'manual' });
  const ct = r.headers.get('content-type') || '';
  const body = ct.startsWith('image') ? `<${(await r.arrayBuffer()).byteLength}B ${ct}>` : (await r.text()).slice(0, 110);
  return `${r.status} ${body.replace(/\s+/g, ' ')}`;
};
console.log('무로그인 /api/seedbank   :', await hit('/api/seedbank'));
console.log('무로그인 /seedfiles/x.jpg:', await hit('/seedfiles/seed-0001.jpg'));
if (member) {
  console.log('구성원 /api/seedbank     :', await hit('/api/seedbank', member));
  console.log('구성원 /seedfiles        :', await hit('/seedfiles/seed-0001.jpg', member));
}
if (admin) {
  const j = await hit('/api/seedbank', admin);
  console.log('관리자 /api/seedbank     :', j.slice(0, 160));
  console.log('관리자 씨앗 이미지       :', await hit('/seedfiles/seed-0001.jpg', admin));
  console.log('관리자 파생 이미지       :', await hit('/seedfiles/seed-0006_kin.jpg', admin));
  console.log('경로 거슬러 오르기       :', await hit('/seedfiles/..%2Fsnapshot.json', admin));
  const home = await raw('/', admin);
  console.log('관리자 홈에 탭 주입      :', /tab-seedbank/.test(home.text) ? 'OK' : '없음(문제)');
}
if (member) {
  const home = await raw('/', member);
  console.log('구성원 홈에 탭 없음      :', /tab-seedbank/.test(home.text) ? '있음(문제)' : 'OK');
} else {
  // 못 본 구간은 결론보다 먼저 적는다 — 지금 원장엔 관리자 계정 하나뿐이라
  // '구성원은 403' 을 라이브로 확인하지 못했다. 판정 코드는 /admin 과 같은 줄이다.
  console.log('구성원 경로              : 미검증(구성원 계정이 아직 없음)');
}
srv.close();
