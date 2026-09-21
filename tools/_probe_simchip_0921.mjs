// 검수 화면 '닮음' 칩 눈 확인 (2026-09-21). 로컬 API(8799)가 떠 있어야 한다.
//   node tools/_probe_simchip_0921.mjs [배치ID]   → tmp/simchip-0921.png
// 캔버스·칩은 겹쳐도 오류를 안 낸다 — 확인은 스크린샷이 유일하다.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const BATCH = process.argv[2] || '';
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=9351', '--no-first-run',
  '--window-size=1440,900', '--user-data-dir=' + path.join(ROOT, '.ui-smoke-profile-probe'), 'about:blank'], { stdio: 'ignore' });
await sleep(3500);
const tabs = await (await fetch('http://127.0.0.1:9351/json/list')).json();
const ws = new WebSocket(tabs.find((t) => t.type === 'page').webSocketDebuggerUrl);
let id = 0; const pend = new Map();
ws.addEventListener('message', (e) => { const j = JSON.parse(e.data); if (pend.has(j.id)) { pend.get(j.id)(j); pend.delete(j.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, q = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: q })); });
const ev = async (e) => (await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: 'http://localhost:8799/#jobs' }); await sleep(3500);
await ev("(function(){localStorage.removeItem('bna.jobsfilter');return 1})()");
const sel = BATCH ? `#batches tbody tr[data-id="${BATCH}"]` : '#batches tbody tr';
await ev(`document.querySelector('${sel}')?.click()`); await sleep(2000);
await ev("document.querySelector('#gal-view [data-v=review]')?.click()"); await sleep(2500);
const chips = await ev("[...document.querySelectorAll('#rev .gates .gate')].map(g=>g.textContent.trim())");
console.log('칩:', JSON.stringify(chips));
const shot = await send('Page.captureScreenshot', { format: 'png' });
mkdirSync(path.join(ROOT, 'tmp'), { recursive: true });
const out = path.join(ROOT, 'tmp', 'simchip-0921.png');
writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
console.log(out);
ws.close(); chrome.kill();
