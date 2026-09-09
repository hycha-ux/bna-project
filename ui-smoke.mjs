/**
 * 화면 스모크 — 진짜 브라우저로 열어 보고 확인한다.
 *
 *   node ui-smoke.mjs            # 로컬 API 를 띄웠다 내리고, 헤드리스로 검사
 *   node ui-smoke.mjs --keep     # 이미 8799 에 서버가 떠 있으면 그걸 쓴다
 *
 * 왜 만들었나. 2026-09-08 "새로고침하면 리스트가 사라진다" — 순수 함수 회귀(review/auth)는
 * 전부 통과하는데도 화면이 깨졌다. **화면 동작은 화면으로만 잡힌다.**
 * 여기 넣은 검사는 전부 그날 실제로 났던 결함이다. 하나씩 늘려라.
 *
 * ⚠ Chrome 이 없으면 조용히 건너뛴다(exit 0) — 이 검사 때문에 다른 회귀가 막히면 안 된다.
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PORT = 8799;
const BASE = `http://localhost:${PORT}`;
const KEEP = process.argv.includes('--keep');
const CHROME = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].find(existsSync);

if (!CHROME) {
  console.log('SKIP  Chrome 없음 — 화면 스모크 건너뜀');
  process.exit(0);
}

const fails = [];
const ok = (cond, label, extra = '') => {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + label + (extra ? ` — ${extra}` : ''));
  if (!cond) fails.push(label);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = async () => {
  try { return (await fetch(BASE + '/api/config', { signal: AbortSignal.timeout(1200) })).ok; } catch { return false; }
};

// ── 로컬 API ────────────────────────────────────────────────────────────────
let api = null;
if (!(await alive())) {
  if (KEEP) { console.log('FAIL  --keep 인데 서버가 없다'); process.exit(1); }
  const py = ['.venv/Scripts/python.exe', 'python3', 'python'].find((c) => c.startsWith('.') ? existsSync(path.join(ROOT, c)) : true);
  api = spawn(py, ['-m', 'bna.api', '--port', String(PORT)], {
    cwd: ROOT, env: { ...process.env, PYTHONPATH: 'src' }, stdio: 'ignore',
  });
  for (let i = 0; i < 40 && !(await alive()); i++) await sleep(500);
  if (!(await alive())) { console.log('FAIL  로컬 API 가 20초 안에 안 떴다'); api.kill(); process.exit(1); }
}

// ── 브라우저 ────────────────────────────────────────────────────────────────
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=9350', '--no-first-run',
  '--window-size=1440,900', '--user-data-dir=' + path.join(ROOT, '.ui-smoke-profile'), 'about:blank'], { stdio: 'ignore' });
await sleep(3500);

// ⚠ Node 내장 WebSocket 을 쓴다(의존성 0). `ws` 패키지를 새로 깔지 마라 —
//    이 파일은 리포에 npm 의존성이 없어도 돌아야 한다.
const tabs = await (await fetch('http://127.0.0.1:9350/json/list')).json();
const ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
let id = 0; const pend = new Map(); const errs = [];
ws.addEventListener('message', (e) => {
  const j = JSON.parse(e.data);
  if (pend.has(j.id)) { pend.get(j.id)(j); pend.delete(j.id); }
  if (j.method === 'Runtime.exceptionThrown') errs.push(j.params.exceptionDetails.text);
});
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, q = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: q })); });
const ev = async (e) => (await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
await send('Runtime.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

const goto = async (hash) => {
  await send('Page.navigate', { url: BASE + '/' + (hash || '') });
  await sleep(5000);
};

try {
  // ① 새로고침하면 작업 목록이 보여야 한다 (2026-09-08 "리스트가 사라지는 버그")
  await goto('#jobs');
  const rows = await ev("document.querySelectorAll('#batches tbody tr').length");
  const listShown = await ev("!document.body.classList.contains('list-folded') && !!document.querySelector('#batches-wrap')?.offsetHeight");
  ok(rows > 0, '새로고침하면 작업 목록에 줄이 보인다', `줄 ${rows}개`);
  ok(listShown, '새로고침 직후 목록이 접혀 있지 않다');

  // ② 줄을 눌러도 목록은 그대로 있고 상세로 이동한다
  //    (2026-09-08 성연서님 "UX 가 더 안 좋아졌다" → 커밋 55095cc 로 접기를 통째로 없앱다.
  //     이 두 줄은 그때 같이 고치지 않아 09-09 까지 빨간불로 남아 있었다 —
  //     상시 빨간불은 진짜 실패를 가린다.)
  await ev("document.querySelector('#batches tbody tr')?.click()");
  await sleep(1600);
  ok(!(await ev("document.body.classList.contains('list-folded')")), '줄을 눌러도 목록이 접히지 않는다');
  ok(await ev("!!document.querySelector('#batches-wrap')?.offsetHeight"), '줄을 눌러도 목록이 그대로 보인다');
  await ev("document.querySelector('#list-toggle')?.click()");
  await sleep(600);
  ok(await ev("!document.body.classList.contains('list-folded')"), '펼치기 버튼이 실제로 목록을 되살린다');

  // ③ 검수 모드는 스크롤이 없어야 한다 (2026-09-08 지시)
  await ev("document.querySelector('#gal-view [data-v=review]')?.click()");
  await sleep(1800);
  const overflow = await ev(`document.documentElement.scrollHeight - innerHeight`);
  const inner = await ev("JSON.stringify([...document.querySelectorAll('*')].filter(e=>e.scrollHeight-e.clientHeight>4 && ['auto','scroll'].includes(getComputedStyle(e).overflowY)).map(e=>(e.id||e.className||e.tagName).toString().slice(0,24)))");
  ok(overflow <= 0, '검수 모드에서 문서 스크롤이 없다', `${overflow}px`);
  ok(inner === '[]', '검수 모드에서 칸 안쪽 스크롤도 없다', inner);

  // ④ AI 점수는 숫자로 나온다 ({score, note} 객체를 숫자로 다루면 [object Object])
  const scoreTxt = await ev("[...document.querySelectorAll('#rev .score b')].map(b=>b.textContent).join(',')");
  ok(scoreTxt !== '' && !/object|NaN/i.test(scoreTxt), 'AI 점수가 숫자로 보인다', scoreTxt || '(없음)');

  // ⑤ 상세 모달은 가운데 뜨고 딤을 누르면 닫힌다
  await ev("document.querySelector('#rev [data-detail]')?.click()");
  await sleep(1000);
  const box = await ev("(function(){var d=document.querySelector('#dlg');var r=d.getBoundingClientRect();return JSON.stringify([Math.round(r.left),Math.round(r.right),innerWidth])})()");
  const [left, right, vw] = JSON.parse(box || '[0,0,1]');
  ok(Math.abs(left - (vw - right)) <= 4, '상세 모달이 가로 가운데에 뜬다', `왼쪽 ${left} / 오른쪽 여백 ${vw - right}`);
  ok(await ev("(function(){var d=document.querySelector('#dlg');d.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:3,clientY:3}));return !d.open})()"),
     '딤(바깥)을 누르면 모달이 닫힌다');

  // ⑥ 화면 설명문은 다시 들어오지 않는다 (2026-09-08 "다 삭제 불필요해")
  await goto('#jobs');
  ok(!(await ev("document.body.innerText.includes('여기서 되는 것')")), '지운 안내 카드가 되살아나지 않았다');

  ok(errs.length === 0, 'JS 오류가 없다', errs.join(' / ') || '없음');
} finally {
  ws.close(); chrome.kill(); if (api) api.kill();
}

console.log();
console.log(fails.length ? `실패 ${fails.length}건` : '전부 통과');
process.exit(fails.length ? 1 : 0);
