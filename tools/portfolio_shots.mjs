// 포트폴리오용 대시보드 캡처 — 1440×900 · 레티나 2배(2880×1800) · 클라우드 실데이터.
// 사용:  1) node tools/cloud_mirror.mjs 8798     (cloud/.env.local 에 BLOB_READ_WRITE_TOKEN 필요)
//        2) node tools/portfolio_shots.mjs <출력폴더> [BASE=http://127.0.0.1:8798] [BATCH=20260910-153348-63cb]
// 결과: <출력폴더>/home.png create.png jobs.png review.png library.png lessons.png lessons2.png
//       + samples/before.jpg after-immediate.jpg after-2w.jpg (같은 인물 4:5 세트, 미러 /files/ 에서 복사)
import { spawn } from 'node:child_process'; import { writeFileSync, mkdirSync } from 'node:fs';
const OUT = process.argv[2]; if (!OUT) { console.error('출력 폴더를 주세요'); process.exit(1); }
const BASE = process.argv[3] || 'http://127.0.0.1:8798';
const BATCH = process.argv[4] || '20260910-153348-63cb';           // 팔자 셀카 8장, 채택 6·제외 2, AI 점수 7항목·2w 시리즈 있음
const SAMPLE = { b: '20260911-094915-7933', i: '0004', stem: 'nasolabial_selfie_korea40sf_0004' }; // 전 · 직후 · 2주 한 세트
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
mkdirSync(OUT + '/samples', { recursive: true }); mkdirSync(OUT + '/prof', { recursive: true });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=9352', '--no-first-run', '--hide-scrollbars', '--window-size=1440,900', '--user-data-dir=' + OUT + '/prof', 'about:blank'], { stdio: 'ignore' });
await sleep(3500);
const tabs = await (await fetch('http://127.0.0.1:9352/json/list')).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
let id = 0; const pend = new Map();
ws.addEventListener('message', e => { const j = JSON.parse(e.data); if (pend.has(j.id)) { pend.get(j.id)(j); pend.delete(j.id); } });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
const send = (m, q = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: q })); });
const ev = async e => (await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
await send('Runtime.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 2, mobile: false });
const shot = async n => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${OUT}/${n}.png`, Buffer.from(r.result.data, 'base64')); console.log('shot', n); };
const goto = async h => { await send('Page.navigate', { url: 'about:blank' }); await sleep(400); await send('Page.navigate', { url: BASE + '/' + h }); await sleep(5000); };
const waitImgs = async () => { for (let i = 0; i < 20; i++) { if (await ev("[...document.images].every(i=>i.complete)")) break; await sleep(500); } await sleep(600); };

await goto('#home'); await ev("localStorage.setItem('bna.dev','1')"); await goto('#home');
await ev("document.querySelector('#home-range [data-days=\"14\"], #home-range button:nth-child(2)')?.click()"); await sleep(1500); await shot('home');
await goto('#create'); await sleep(800); await shot('create');
await goto('#jobs'); await ev(`[...document.querySelectorAll('#batches tbody tr')].find(r=>r.dataset.id==='${BATCH}'||r.textContent.includes('${BATCH.slice(4,8)}'))?.click()||document.querySelector('#batches tbody tr')?.click()`); await sleep(2000);
await ev("document.querySelector('#gal-view [data-v=grid]')?.click()"); await sleep(800); await waitImgs(); await shot('jobs');
await ev("document.querySelector('#gal-view [data-v=review]')?.click()"); await sleep(2000); await waitImgs(); await shot('review');
await goto('#library'); await waitImgs(); await shot('library');
await goto('#lessons'); await sleep(800); await shot('lessons');
await ev("window.scrollTo(0,700)"); await sleep(600); await shot('lessons2');
// 전후 샘플 3장 — 미러가 blob 을 그대로 내려주므로 파일로 복사
for (const [name, f] of [['before', `${SAMPLE.stem}_before.jpg`], ['after-immediate', `${SAMPLE.stem}_after_immediate.jpg`], ['after-2w', `${SAMPLE.stem}_after_2w.jpg`]]) {
  const r = await fetch(`${BASE}/files/${SAMPLE.b}/${SAMPLE.i}/${f}`); if (r.ok) { writeFileSync(`${OUT}/samples/${name}.jpg`, Buffer.from(await r.arrayBuffer())); console.log('sample', name); } else console.log('sample 없음', f, r.status);
}
ws.close(); chrome.kill(); process.exit(0);
