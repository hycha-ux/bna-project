/**
 * 생성 요청 폴러 — 인터넷 화면이 적어 둔 요청을 이 PC(생성 PC)가 가져가 돌린다.
 * 규약 정본 = `docs/gen-request-protocol-0909-buildy.md` §4 (2026-09-09 성연서님
 * "클라우드 화면에서 생성을 누르면 티모가 알아서 돌리는 구조").
 *
 *   node ops/gen-poller.mjs           # 한 회차 (예약작업이 1분마다 이걸 부른다)
 *   node ops/gen-poller.mjs --dry     # 무엇을 할지만 출력 — Blob 쓰기 0, 생성 0, 서버 안 띄움
 *   node ops/gen-poller.mjs --restart-api  # 로컬 API 만 껐다 켠다(큐가 비었을 때만, 요청은 안 본다)
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
 *     단 **파이썬 코드가 바뀌었고 큐가 비었을 때만** 갈아 끼운다(`ensureApi` 머리말).
 *
 * 상태를 읽는 곳: 로컬 큐 원장 `outputs/queue.json`(파일이 정본이라 서버가 꺼져 있어도 읽힌다).
 * 상태를 쓰는 곳: `cloud/lib/genreq.mjs`(전이 규칙 정본). 여기서 규칙을 다시 쓰지 마라.
 * 회귀 = `node ops/gen-poller-tests.mjs`(네트워크 0).
 */
import { spawn, execFileSync } from 'node:child_process';
import { existsSync, readFileSync, appendFileSync, writeFileSync, unlinkSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const OUT = path.join(ROOT, 'outputs');
const LOG = path.join(OUT, 'gen-poller.log');
const LOCK = path.join(OUT, '.gen-poller.lock');
const API_STATE = path.join(OUT, '.gen-poller-api.json');   // 우리가 띄운 로컬 API 의 pid·소스 시각
const LOCK_STALE_MS = 10 * 60 * 1000;
const PORT = Number(process.env.BNA_LOCAL_API_PORT) || 8765;
const DRY = process.argv.includes('--dry');
const RESTART = process.argv.includes('--restart-api');
const MAX_ACCEPT = 10;            // 한 회차에 가져가는 요청 수 상한(폭주 시 완충 — 큐는 어차피 한 번에 하나씩 돈다)

export const labelOf = (id) => `genreq:${id}`;

/** 재시작이 죽여선 안 되는 작업들. 순수 함수라 회귀가 이걸 본다(돈이 걸린 판단이라 눈으로만 보지 않는다). */
export const restartBlockers = (jobs) => (jobs || []).filter((j) => j.status === 'queued' || j.status === 'running');

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

/**
 * 생성 키를 자식(로컬 API)에게 물려준다 — **파일이 유일한 원천이다**(`C:\Users\medib\teemo\keys.env`).
 *
 * 왜 있는가(2026-09-11 사고): 폴러는 예약작업(`TeemoBnaGenPoller`)이 띄운다. 예약작업 환경엔
 * `OPENAI_API_KEY` 가 없고(사용자·시스템 환경변수 어디에도 없다 — 실측), `spawnApi` 는
 * `{...process.env}` 를 그대로 물려주므로 **키 없는 서버**가 조용히 떴다. 종전엔 사람이
 * `run-selfie-batches.ps1`(이 파일을 읽어 주입한다)로 띄워 둔 서버가 살아 있어 안 드러났고,
 * 09-09 의 폴러 성공 8건은 전부 *시뮬*(프로바이더를 안 만든다)이라 키를 안 탔다. 그래서 이 경로로
 * 들어온 **첫 실모드 요청**이 `NotConfigured('openai: OPENAI_API_KEY not set in .env')` 로 죽었다.
 *
 * ⚠ 이름 목록은 `tools/run-selfie-batches.ps1` 의 화이트리스트와 **같은 한 벌이다** — 한쪽만 늘리면
 *   손으로 돌릴 때와 폴러가 돌릴 때 서버의 능력이 갈린다(오류 없이 갈린다).
 * ⚠ 값은 절대 찍지 않는다. 로그·예외 문안에도 이름만 남긴다.
 */
export const PROVIDER_KEYS = ['OPENAI_API_KEY', 'GEMINI_API_KEY', 'HIGGSFIELD_API_KEY', 'HIGGSFIELD_SECRET'];
const KEYS_FILE = process.env.BNA_KEYS_FILE || path.join('C:', 'Users', 'medib', 'teemo', 'keys.env');

/** 순수 함수 — 이미 환경에 있는 값이 이긴다(손으로 띄운 셸이 일부러 넣은 값을 파일이 덮지 않는다). */
export function mergeKeys(base, fileText) {
  const out = { ...base };
  for (const line of String(fileText || '').split(/\r?\n/)) {
    const m = /^\s*([A-Z0-9_]+)\s*=\s*"?([^"\r\n]*)"?\s*$/.exec(line);
    if (!m || !PROVIDER_KEYS.includes(m[1])) continue;
    if (!out[m[1]] && m[2]) out[m[1]] = m[2];
  }
  return out;
}

function providerEnv() {
  let text = '';
  try { if (existsSync(KEYS_FILE)) text = readFileSync(KEYS_FILE, 'utf8'); } catch { /* 못 읽으면 아래 가드가 세운다 */ }
  return mergeKeys(process.env, text);
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

/** 파이썬 소스의 가장 최근 수정 시각 — 떠 있는 서버가 옛 코드인지 판단하는 값. */
function srcMtime(dir = path.join(ROOT, 'src', 'bna')) {
  let newest = 0;
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === '__pycache__') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) newest = Math.max(newest, srcMtime(p));
    else if (e.name.endsWith('.py')) newest = Math.max(newest, statSync(p).mtimeMs);
  }
  return newest;
}

/** 그 포트를 실제로 물고 있는 프로세스 번호. pid 재사용으로 엉뚱한 프로세스를 죽이지 않으려는 확인이다. */
function listeningPid(port = PORT) {
  try {
    const out = execFileSync('netstat', ['-ano', '-p', 'tcp'], { encoding: 'latin1', timeout: 8000 });
    for (const line of out.split(/\r?\n/)) {
      if (!line.includes(`:${port}`) || !/LISTENING/i.test(line)) continue;
      const pid = Number(line.trim().split(/\s+/).pop());
      if (Number.isInteger(pid)) return pid;
    }
  } catch { /* 못 재면 아무것도 죽이지 않는다 */ }
  return null;
}

/**
 * 로컬 API 를 띄운다 — **띄운 서버는 (한 가지 경우만 빼고) 죽이지 않는다.**
 * 이 회차는 1분이면 끝나지만 생성은 몇 분씩 걸리므로, 부모가 죽어도 사는 자식(detached)이어야
 * 한다. 여기서 kill 하면 돈을 쓰고 시작한 배치가 그 자리에서 날아간다.
 *
 * 예외 하나 — **파이썬 코드가 바뀌었는데 옛 서버가 떠 있는 경우**. 이 서버는 한 번 뜨면 몇 날이고
 * 살아 있어서, `git pull` 로 파이프라인이 바뀌어도 조용히 옛 코드로 계속 돈다(09-09 실측: 새로
 * 생긴 `series` 칸이 오류 없이 통째로 무시돼 전·후 2장이 나왔다). 그래서 **①큐가 비었고
 * ②소스가 서버보다 새롭고 ③그 포트를 물고 있는 게 우리가 띄운 그 프로세스일 때만** 갈아 끼운다.
 */
async function ensureApi({ idle }) {
  if (await alive()) {
    const rec = readJson(API_STATE);
    const stale = idle && rec && srcMtime() > (rec.src || 0) && listeningPid() === rec.pid;
    if (!stale) return 'already';
    try { process.kill(rec.pid); } catch { return 'already'; }
    for (let i = 0; i < 20 && await alive(); i++) await sleep(500);
    log('코드가 바뀌어 로컬 API 를 다시 띄운다(큐가 비어 있을 때만)');
  }
  return spawnApi();
}

/** 서버를 새로 띄우고 pid·소스 시각을 적는다. **죽이는 판단은 부르는 쪽 몫이다**(돈이 걸린 판단이라 여기 두지 않는다). */
async function spawnApi() {
  // 키 없는 서버는 띄우지 않는다 — 마지막 방어선이다(앞단 `needsKey` 가 먼저 막는다).
  const env = { ...providerEnv(), PYTHONPATH: 'src' };
  if (!env.OPENAI_API_KEY) throw new Error(`생성 키가 없다 — ${KEYS_FILE} 의 OPENAI_API_KEY 를 확인해라(node C:/Users/medib/teemo/tools/verify-keys.mjs)`);
  const p = spawn(python(), ['-m', 'bna.api', '--port', String(PORT), '--no-open'], {
    cwd: ROOT, env,
    detached: true, stdio: 'ignore', windowsHide: true,
  });
  p.unref();
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    if (await alive()) {
      // ⚠ 적어 둘 pid 는 `spawn` 이 준 것이 아니라 **그 포트를 실제로 물고 있는** 프로세스다.
      // venv 의 python.exe 는 진짜 인터프리터를 자식으로 띄우는 껍데기라 둘이 다르다(09-09 실측
      // 31096 vs 26344) — 껍데기 번호를 적어 두면 갈아 끼우기가 영영 안 걸린다.
      const owner = listeningPid() ?? p.pid;
      try { writeFileSync(API_STATE, JSON.stringify({ pid: owner, spawned: p.pid, at: Date.now(), src: srcMtime() }), 'utf8'); } catch { /* 기록 실패는 다음 회차가 덮는다 */ }
      return 'spawned';
    }
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

/**
 * 요청 → 로컬 큐 작업. 프로바이더(gen/edit/qa)는 안 보낸다 = providers.yaml 기본값.
 * ⚠ **요청 필드가 늘면 여기도 늘려라.** 안 넘긴 칸은 오류 없이 기본값으로 떨어진다 — `series`
 *   (경과 시리즈 시점)를 빠뜨리면 시점별 사진을 시켰는데 전·후 2장이 조용히 나온다.
 *   `genreq.mjs` 의 `validate` 가 통과시키는 칸과 `queue.py` 의 `add` 가 받는 칸이 짝이다.
 */
/**
 * 이 요청이 생성 키를 타는가 — 시뮬(`simulate`)은 프로바이더를 안 만들어 키 없이도 돈다.
 * 그래서 키가 없는 회차라도 시뮬 요청까지 세우지는 않는다(09-09 의 성공 8건이 그 모양이었다).
 */
export const needsKey = (req) => !req?.simulate;

export function jobSpec(req) {
  return {
    treatment: req.treatment, mode: req.mode, count: req.count,
    seed: req.seed ?? null, fixed: req.fixed || {},
    target_pass: req.target_pass ?? null, cost_cap: req.cost_cap ?? null,
    series: req.series ?? null,
    simulate: !!req.simulate, label: labelOf(req.id),
  };
}

/**
 * 손으로 부르는 재시작 — `node ops/gen-poller.mjs --restart-api`.
 * 자동 갈아 끼우기(`ensureApi`)는 **코드가 바뀌었을 때만** 걸리므로, 서버가 이상하게 굴 때
 * 사람이 부를 문이 따로 필요했다(종전엔 pid 를 손으로 찾아 죽였다 — 그 자리가 사고 자리다).
 * ⚠ 죽이는 건 돈이 걸린 일이다: 큐에 도는 작업이 있으면 **아무것도 하지 않고** 멈춘다(exit 2).
 * ⚠ 죽일 번호는 상태 파일이 아니라 **그 포트를 실제로 물고 있는** 번호다(껍데기 pid 함정, `ensureApi` 머리말).
 */
async function restartApi() {
  const busy = restartBlockers(queueJobs());
  if (busy.length) { log(`재시작 안 한다 — 큐에 도는 작업 ${busy.length}건(죽이면 그 생성이 그 자리에서 날아간다)`); process.exitCode = 2; return; }
  const owner = listeningPid();
  if (DRY) { log(`--dry — 재시작했을 것: 포트 ${PORT} ${owner ? `pid ${owner} 종료 후 ` : '(떠 있는 서버 없음) '}새로 띄움`); return; }
  if (owner) {
    try { process.kill(owner); } catch (e) { log('종료 실패 —', e.message); }
    for (let i = 0; i < 20 && await alive(); i++) await sleep(500);
    if (await alive()) { log(`포트 ${PORT} 가 아직 응답한다 — 재시작 중단(무엇이 물고 있는지 확인해라)`); process.exitCode = 1; return; }
  }
  await spawnApi();
  log(`로컬 API 재시작 완료 — 포트 ${PORT}, pid ${readJson(API_STATE)?.pid ?? '?'}${owner ? ` (옛 pid ${owner})` : ' (꺼져 있던 걸 새로 띄웠다)'}`);
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
        // 키가 없으면 **받기 전에** 세운다. 받아 버리면 생성에서 죽어 요청이 '실패'로 소모되고
        // 사람이 다시 보내야 한다(2026-09-11 실사고). 여기서 멈추면 '요청됨'인 채 남아,
        // 키를 채운 다음 회차가 재전송 없이 그대로 집어 간다.
        if (needsKey(req) && !providerEnv().OPENAI_API_KEY) {
          log(`대기 ${a.id} — 생성 키가 없어 받지 않는다(${KEYS_FILE} 의 OPENAI_API_KEY). 요청은 그대로 둔다`);
          continue;
        }
        if (a.kind === 'accept') {
          const r = await GR.advance(token, a.id, 'accepted', { accepted_at: new Date().toISOString(), host: os.hostname() });
          if (r.error) { log(`건너뜀 ${a.id} — ${r.error}`); continue; }   // 그 사이 취소됐다
          req = r.ok;
        }
        if (!req || req.status !== 'accepted') { log(`건너뜀 ${a.id} — 상태가 ${req?.status}`); continue; }
        try {
          await ensureApi({ idle: !queueJobs().some((j) => j.status === 'queued' || j.status === 'running') });
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
  (RESTART ? restartApi() : main())
    .catch((e) => { log('회차 실패 —', e.message); process.exitCode = 1; })
    .finally(() => { if (!DRY) freeLock(); });
}
