/**
 * 생성 요청 폴러 — 인터넷 화면이 적어 둔 요청을 이 PC(생성 PC)가 가져가 돌린다.
 * 규약 정본 = `docs/gen-request-protocol-0909-buildy.md` §4 (2026-09-09 성연서님
 * "클라우드 화면에서 생성을 누르면 티모가 알아서 돌리는 구조").
 *
 *   node ops/gen-poller.mjs           # 한 회차 (예약작업이 1분마다 이걸 부른다)
 *   node ops/gen-poller.mjs --dry     # 무엇을 할지만 출력 — Blob 쓰기 0, 생성 0, 서버 안 띄움
 *
 * 왜 이 모양인가: 밖에서 이 PC 로 들어올 길이 없다(공인 주소·포트 개방 없음). 그래서 화면은
 * 요청을 Blob `gen-requests/<id>.json` 에 **적어만 두고**, 이 PC 가 주기적으로 열어 가져간다.
 * 사진 결과는 종전대로 `push-cloud` 가 올리므로 여기서 따로 올리지 않는다.
 *
 * 돈이 나가는 스크립트다. 겹치지 않게·두 번 돌지 않게 하는 장치가 넷이다:
 *  1) **락 파일** `outputs/.gen-poller.lock` — 예약작업과 손 실행이 겹쳐 같은 요청을 둘이
 *     집는 걸 막는다(10분 지나면 죽은 락으로 보고 회수).
 *  2) **쓰기 직전 재확인** — `advance()` 가 Blob 을 다시 읽어 전이 규칙을 본다. 목록을 만든
 *     사이 화면에서 취소가 눌렸으면 여기서 걸린다(취소된 요청을 안 돌리는 장치가 이것이다).
 *  3) **라벨 `genreq:<id>`** — 큐에 넣은 뒤 요청 파일에 작업 번호를 적기 전에 죽어도, 다음
 *     회차가 라벨로 그 작업을 찾아 **붙인다**(다시 넣지 않는다). 이게 없으면 재시도가 곧 이중 생성이다.
 *  4) **로컬 API 는 필요할 때만 띄운다** — 큐 러너가 같이 깨어나기 때문이다. 띄우는 건 이번
 *     회차에 실제로 넣을 요청이 있을 때뿐이고, 띄운 서버는 살려 둔다(생성이 몇 분씩 걸린다).
 *
 * 상태를 읽는 곳: 로컬 큐 원장 `outputs/queue.json`(파일이 정본이라 서버가 꺼져 있어도 읽힌다).
 * 상태를 쓰는 곳: `cloud/lib/genreq.mjs`(전이 규칙 정본). 여기서 규칙을 다시 쓰지 마라.
 * 회귀 = `node ops/gen-poller-tests.mjs`(네트워크 0).
 */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, appendFileSync, writeFileSync, unlinkSync, mkdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const OUT = path.join(ROOT, 'outputs');
const LOG = path.join(OUT, 'gen-poller.log');
const LOCK = path.join(OUT, '.gen-poller.lock');
const LOCK_STALE_MS = 10 * 60 * 1000;
const PORT = Number(process.env.BNA_LOCAL_API_PORT) || 8765;
const DRY = process.argv.includes('--dry');
const MAX_ACCEPT = 10;            // 한 회차에 가져가는 요청 수 상한(폭주 시 완충 — 큐는 어차피 한 번에 하나씩 돈다)

export const labelOf = (id) => `genreq:${id}`;

// ── 순수 판단 ────────────────────────────────────────────────────────────────
// 요청 목록 + 로컬 큐 작업 목록 → 이번 회차에 할 일. 여기엔 부작용이 없다(회귀가 이 함수를 본다).
export function plan(reqs, jobs, { maxAccept = MAX_ACCEPT } = {}) {
  const acts = [];
  const byId = new Map(jobs.map((j) => [j.job_id, j]));
  const byLabel = new Map(jobs.map((j) => [j.label, j]));
  const findJob = (r) => (r.local_job_id && byId.get(r.local_job_id)) || byLabel.get(labelOf(r.id)) || null;

  for (const r of reqs) {
    if (r.status !== 'accepted' && r.status !== 'running') continue;
    const j = findJob(r);
    if (!j) {
      // 넣은 적이 없으면 다시 넣는다(받음 직후 죽은 경우). 넣었었는데 사라졌으면 결과를 알 수 없다.
      if (r.local_job_id || r.batch_id) acts.push({ kind: 'error', id: r.id, error: '로컬 큐에서 사라졌습니다 — 중단됐거나 목록이 정리됐습니다' });
      else acts.push({ kind: 'add', id: r.id });
      continue;
    }
    if (!r.local_job_id) acts.push({ kind: 'adopt', id: r.id, job_id: j.job_id });
    if (j.status === 'done') acts.push({ kind: 'done', id: r.id, job_id: j.job_id, batch_id: j.batch_id, stats: j.result || null, from: r.status });
    else if (j.status === 'error') acts.push({ kind: 'error', id: r.id, error: shortErr(j.error) });
    else if (j.status === 'cancelled') acts.push({ kind: 'error', id: r.id, error: '이 PC 대기열에서 취소됐습니다' });
    else if (j.status === 'running' && r.status !== 'running') acts.push({ kind: 'running', id: r.id, job_id: j.job_id, batch_id: j.batch_id });
    else if (j.status === 'running' && r.batch_id !== j.batch_id && j.batch_id) acts.push({ kind: 'note', id: r.id, fields: { batch_id: j.batch_id } });
  }

  const waiting = reqs.filter((r) => r.status === 'requested')
    .sort((a, b) => String(a.requested_at).localeCompare(String(b.requested_at)));
  for (const r of waiting.slice(0, maxAccept)) acts.push({ kind: 'accept', id: r.id });
  return acts;
}

/** 파이썬 repr 예외는 길다 — 화면 한 줄에 들어가게 자른다(전문은 로컬 큐에 남아 있다). */
export function shortErr(e) {
  const s = String(e ?? '알 수 없는 오류').replace(/\s+/g, ' ').trim();
  return s.length > 200 ? s.slice(0, 197) + '…' : s;
}

/**
 * 배치 결과 한 줄 요약 — 장수는 배치가 돌려준 stats, 든 돈은 `progress.json` 에서 온다.
 * ⚠ 파일에는 `summary` 가 없다(파이썬 `progress.read()` 가 읽을 때 만든다) → 항목 비용을 더한다.
 *   더하는 규칙은 `src/bna/progress.py` 의 summary.cost 와 같은 식이다(바뀌면 여기도 같이).
 * 못 읽은 값은 0 이 아니라 null 로 둔다 — 0 원으로 보이면 공짜로 돈 줄 안다.
 */
export function resultOf(stats, progress) {
  const s = stats || {};
  const p = progress || {};
  const items = Object.values(p.items || {});
  const sum = items.reduce((a, i) => a + (Number(i.cost) || 0), 0);
  const passed = items.filter((i) => i.passed).length;
  return {
    total: s.total ?? p.planned ?? (items.length || null),
    passed: s.passed ?? (items.length ? passed : null),
    cost: p.summary?.cost ?? (items.length ? Math.round(sum * 10000) / 10000 : null),
  };
}

// ── 곁일 (파일·네트워크) ─────────────────────────────────────────────────────
function log(...m) {
  const line = `[${new Date().toISOString()}] ${m.join(' ')}`;
  console.log(line);
  try { mkdirSync(OUT, { recursive: true }); appendFileSync(LOG, line + '\n', 'utf8'); } catch { /* 로그 실패가 회차를 죽이지 않는다 */ }
}

/** push-cloud.mjs 와 같은 파일·같은 이름을 읽는다(바꾸면 둘 다 바꿔야 한다). 값은 절대 찍지 않는다. */
function blobToken() {
  const f = path.join(ROOT, 'cloud', '.env.local');
  if (!existsSync(f)) return null;
  for (const line of readFileSync(f, 'utf8').split(/\r?\n/)) {
    const m = /^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/.exec(line);
    if (m) return m[1];
  }
  return null;
}

export function readJson(file) {
  try { return JSON.parse(readFileSync(file, 'utf8')); } catch { return null; }
}

function queueJobs() {
  const q = readJson(path.join(OUT, 'queue.json'));
  return (q && q.jobs) || [];
}

function takeLock() {
  const now = Date.now();
  const cur = readJson(LOCK);
  if (cur && now - (cur.at || 0) < LOCK_STALE_MS) return false;
  writeFileSync(LOCK, JSON.stringify({ pid: process.pid, at: now, host: os.hostname() }), 'utf8');
  return true;
}
function freeLock() { try { unlinkSync(LOCK); } catch { /* 이미 없으면 그만 */ } }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function alive() {
  try { return (await fetch(`http://127.0.0.1:${PORT}/api/config`, { signal: AbortSignal.timeout(1500) })).ok; } catch { return false; }
}

function python() {
  for (const p of ['.venv/Scripts/python.exe', '.venv/bin/python']) {
    const abs = path.join(ROOT, p);
    if (existsSync(abs)) return abs;
  }
  return 'python';
}

/**
 * 로컬 API 를 띄운다 — **띄운 서버는 죽이지 않는다.**
 * 이 회차는 1분이면 끝나지만 생성은 몇 분씩 걸리므로, 부모가 죽어도 사는 자식(detached)이어야
 * 한다. 여기서 kill 하면 돈을 쓰고 시작한 배치가 그 자리에서 날아간다.
 */
async function ensureApi() {
  if (await alive()) return 'already';
  const p = spawn(python(), ['-m', 'bna.api', '--port', String(PORT), '--no-open'], {
    cwd: ROOT, env: { ...process.env, PYTHONPATH: 'src' },
    detached: true, stdio: 'ignore', windowsHide: true,
  });
  p.unref();
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    if (await alive()) return 'spawned';
  }
  throw new Error(`로컬 API 가 30초 안에 안 떴다(포트 ${PORT})`);
}

async function addToQueue(job) {
  const r = await fetch(`http://127.0.0.1:${PORT}/api/queue/add`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jobs: [job] }), signal: AbortSignal.timeout(20000),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok || body.error || !body.added?.length) throw new Error(`큐 등록 실패 — ${body.error || `HTTP ${r.status}`}`);
  return body.added[0];
}

/** 요청 → 로컬 큐 작업. 프로바이더(gen/edit/qa)는 안 보낸다 = providers.yaml 기본값. */
export function jobSpec(req) {
  return {
    treatment: req.treatment, mode: req.mode, count: req.count,
    seed: req.seed ?? null, fixed: req.fixed || {},
    target_pass: req.target_pass ?? null, cost_cap: req.cost_cap ?? null,
    simulate: !!req.simulate, label: labelOf(req.id),
  };
}

// ── 한 회차 ─────────────────────────────────────────────────────────────────
async function main() {
  const token = blobToken();
  if (!token) { log('Blob 토큰이 없다(cloud/.env.local) — 아직 연결 전이라 조용히 멈춘다'); process.exit(3); }
  const GR = await import('../cloud/lib/genreq.mjs');   // @vercel/blob 은 cloud/ 안에서 풀린다

  let reqs = [];
  try { reqs = await GR.listAll(token, { keep: 200 }); } catch (e) { log('요청 목록을 못 읽었다 —', e.message); process.exit(1); }
  const acts = plan(reqs, queueJobs());
  const live = reqs.filter((r) => ['requested', 'accepted', 'running'].includes(r.status)).length;
  // 할 일 없는 회차는 로그 파일에 안 쌓는다 — 1분마다 도는 배치라 하루 1,400줄이 쌓이면
  // 정작 사고가 난 줄을 못 찾는다. 진행 중인 게 있을 때만 파일에도 남긴다.
  if (!acts.length) { const m = `할 일 없음 (진행 중 ${live}건)`; live ? log(m) : console.log(m); return; }

  if (DRY) { log('--dry —', JSON.stringify(acts)); return; }

  const known = new Map(reqs.map((r) => [r.id, r]));
  for (const a of acts) {
    try {
      if (a.kind === 'accept' || a.kind === 'add') {
        // 받음을 먼저 적고 나서 큐에 넣는다. 반대로 하면 화면이 '요청됨'인 채로 생성이 돈다.
        let req = known.get(a.id);
        if (a.kind === 'accept') {
          const r = await GR.advance(token, a.id, 'accepted', { accepted_at: new Date().toISOString(), host: os.hostname() });
          if (r.error) { log(`건너뜀 ${a.id} — ${r.error}`); continue; }   // 그 사이 취소됐다
          req = r.ok;
        }
        if (!req || req.status !== 'accepted') { log(`건너뜀 ${a.id} — 상태가 ${req?.status}`); continue; }
        try {
          await ensureApi();
          const jobId = await addToQueue(jobSpec(req));
          await GR.annotate(token, a.id, { local_job_id: jobId });
          log(`${a.kind === 'accept' ? '받음' : '재등록'} ${a.id} → 큐 ${jobId} (${req.treatment}/${req.mode} ${req.count}장${req.simulate ? ' 시뮬' : ''})`);
        } catch (e) {
          await GR.advance(token, a.id, 'error', { error: shortErr(e.message), finished_at: new Date().toISOString() });
          log(`실패 ${a.id} — ${e.message}`);
        }
      } else if (a.kind === 'adopt') {
        const r = await GR.annotate(token, a.id, { local_job_id: a.job_id });
        if (r.ok) known.set(a.id, r.ok);   // 같은 회차의 뒤 단계(done)가 이 값을 이어 쓴다
        log(`이어붙임 ${a.id} → 큐 ${a.job_id}`);
      } else if (a.kind === 'running') {
        const r = await GR.advance(token, a.id, 'running', { batch_id: a.batch_id || null, started_at: new Date().toISOString(), local_job_id: a.job_id });
        log(r.error ? `전이 실패 ${a.id} — ${r.error}` : `생성 중 ${a.id} (배치 ${a.batch_id || '준비 중'})`);
      } else if (a.kind === 'note') {
        await GR.annotate(token, a.id, a.fields);
      } else if (a.kind === 'done') {
        const prog = a.batch_id ? readJson(path.join(OUT, a.batch_id, 'progress.json')) : null;
        const result = resultOf(a.stats, prog);
        // running 을 건너뛴 채 끝난 경우(회차 사이에 다 돌아버린 짧은 배치)도 한 칸씩 밟아 준다.
        let cur = known.get(a.id);
        if (cur && cur.status === 'accepted') {
          const up = await GR.advance(token, a.id, 'running', { batch_id: a.batch_id || null, started_at: new Date().toISOString() }, cur);
          if (up.ok) cur = up.ok;
        }
        const r = await GR.advance(token, a.id, 'done', { batch_id: a.batch_id || null, finished_at: new Date().toISOString(), result }, cur);
        log(r.error ? `전이 실패 ${a.id} — ${r.error}` : `완료 ${a.id} — ${result.passed ?? '?'}/${result.total ?? '?'}장 통과, $${result.cost ?? '?'}`);
      } else if (a.kind === 'error') {
        const r = await GR.advance(token, a.id, 'error', { error: a.error, finished_at: new Date().toISOString() });
        log(r.error ? `전이 실패 ${a.id} — ${r.error}` : `실패 ${a.id} — ${a.error}`);
      }
    } catch (e) {
      log(`회차 중 오류 (${a.kind} ${a.id}) —`, e.message);   // 한 건이 나머지를 죽이지 않는다
    }
  }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!DRY && !takeLock()) { console.log('앞 회차가 아직 돈다(락) — 이번 회차는 건너뛴다'); process.exit(0); }
  main()
    .catch((e) => { log('회차 실패 —', e.message); process.exitCode = 1; })
    .finally(() => { if (!DRY) freeLock(); });
}
