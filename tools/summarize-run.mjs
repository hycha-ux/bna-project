/**
 * 한 회차 결과 요약 — 시술별 생성·통과·비용, 그리고 자동 게이트가 **실제로 잰 비율**.
 *
 *   node tools/summarize-run.mjs <배치ID…>
 *   node tools/summarize-run.mjs --since 2026-09-09T10:00
 *
 * 왜 measured_rate 를 따로 내나 (0909 빌디 요청):
 *   동일인 게이트는 3값이다 — 통과 / 탈락 / **n/a(못 잼)**. 목주름처럼 얼굴이 프레임 밖인 컷은
 *   구조적으로 n/a 가 된다. n/a 를 통과로 세면 "다 통과했다"가 되고, 탈락으로 세면 멀쩡한 컷에
 *   돈을 다시 쓴다. 그래서 **몇 %를 실제로 쟀는지**를 통과율과 나란히 낸다.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const OUT = path.join(ROOT, 'outputs');
const args = process.argv.slice(2);
const sinceArg = args.includes('--since') ? args[args.indexOf('--since') + 1] : null;
const since = sinceArg ? new Date(sinceArg).getTime() : null;
const only = args.filter((a) => !a.startsWith('--') && a !== sinceArg);

const acc = new Map();
for (const b of fs.readdirSync(OUT)) {
  const bd = path.join(OUT, b);
  if (!fs.statSync(bd).isDirectory()) continue;
  if (only.length && !only.includes(b)) continue;
  if (since && fs.statSync(bd).mtimeMs < since) continue;
  for (const it of fs.readdirSync(bd)) {
    const mp = path.join(bd, it, 'meta.json');
    if (!fs.existsSync(mp)) continue;
    let m;
    try { m = JSON.parse(fs.readFileSync(mp, 'utf8')); } catch { continue; }
    if (m.dry_run) continue;
    const t = m.treatment || '?';
    const a = acc.get(t) || {
      treatment: t, batches: new Set(), n: 0, passed: 0, cost: 0,
      idMeasured: 0, idPass: 0, stMeasured: 0, reasons: {}, providers: new Set(), version: m.prompt_version,
    };
    a.batches.add(b); a.n += 1; a.passed += m.passed ? 1 : 0; a.cost += Number(m.cost || 0);
    if ((m.providers || {}).gen) a.providers.add(m.providers.gen);
    // 동일인: measured=false 면 못 잰 것(n/a). passed 는 3값이라 === 로 본다.
    if (m.identity && m.identity.measured) { a.idMeasured += 1; if (m.identity.passed === true) a.idPass += 1; }
    if (m.structure && m.structure.passed !== null && m.structure.passed !== undefined) a.stMeasured += 1;
    for (const r of m.fail_reasons || []) a.reasons[r] = (a.reasons[r] || 0) + 1;
    acc.set(t, a);
  }
}

if (!acc.size) { console.log('집계할 항목이 없다 (meta.json 없음).'); process.exit(1); }
const pct = (a, b) => (b ? `${Math.round((a / b) * 100)}%` : '–');
console.log(`시술            장수  AI통과      비용     동일인 잰비율  잰 것 중 통과  구조 잰비율  모델`);
let tn = 0, tp = 0, tc = 0;
for (const a of acc.values()) {
  tn += a.n; tp += a.passed; tc += a.cost;
  console.log(
    `${a.treatment.padEnd(15)} ${String(a.n).padStart(3)}  ${pct(a.passed, a.n).padStart(5)}  ${('$' + a.cost.toFixed(2)).padStart(8)}` +
    `  ${pct(a.idMeasured, a.n).padStart(11)}  ${pct(a.idPass, a.idMeasured).padStart(12)}  ${pct(a.stMeasured, a.n).padStart(10)}  ${[...a.providers].join(',') || '?'}`);
  const top = Object.entries(a.reasons).sort((x, y) => y[1] - x[1]).slice(0, 3);
  if (top.length) console.log(`${' '.repeat(16)}탈락 사유: ${top.map(([k, v]) => `${k} ${v}`).join(' · ')}`);
}
console.log(`${'합계'.padEnd(15)} ${String(tn).padStart(3)}  ${pct(tp, tn).padStart(5)}  ${('$' + tc.toFixed(2)).padStart(8)}`);
console.log(`\n※ '동일인 잰비율' 이 낮은 건 실패가 아니라 **못 잰 것**(얼굴이 프레임 밖). 통과로도 탈락으로도 세지 않는다.`);
