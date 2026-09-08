/**
 * 구글드라이브 백업 — 생성물 원본을 드라이브로 단방향 복사 (2026-09-08 성연서님 지시 "드라이브 백업").
 *
 * 왜: 지금 사진은 이 PC `outputs/` 한 곳에만 있다(git 제외). 클라우드 Blob 에도 사본이 있지만
 * 화면이 안 부르는 사진은 `prune` 이 지우므로 백업이 아니다 — PC가 죽으면 전량 소실이다.
 *
 *   node ops/drive-backup.mjs --dry     # 무엇을 올릴지만(네트워크 0)
 *   node ops/drive-backup.mjs           # 실제 업로드
 *
 * 규칙 셋 — 백업이 원본을 해치지 않게:
 *  1) **단방향이다.** 여기서 지운 건 드라이브에서 안 지운다. 로컬을 실수로 날려도 백업은 남는다.
 *  2) **새것·바뀐 것만 올린다.** 크기+수정시각이 같으면 건너뛴다(원장 `ops/.drive-manifest.json`).
 *  3) **키가 없으면 조용히 멈춘다**(exit 3). 예약작업이 매일 빨간불을 내며 우는 걸 막는다.
 *
 * 자격증명은 `C:\Users\medib\teemo\keys.env` 하나에서만 읽는다(값은 절대 출력하지 않는다).
 * 두 가지 중 하나면 된다:
 *   A) 서비스 계정   GOOGLE_SA_JSON_B64  (서비스 계정 JSON 을 base64 한 줄로)
 *   B) 사용자 위임   GDRIVE_CLIENT_ID · GDRIVE_CLIENT_SECRET · GDRIVE_REFRESH_TOKEN
 * 공통          GDRIVE_BACKUP_FOLDER_ID  (백업이 쌓일 드라이브 폴더)
 *
 * ⚠ A안은 **공유 드라이브(Shared Drive)** 에서만 쓴다. 서비스 계정은 제 저장용량이 0이라,
 *   개인 My Drive 폴더에 올리면 `storageQuotaExceeded` 로 실패한다 — 공유 드라이브는 용량이
 *   조직 것이라 통과한다. 개인 폴더밖에 못 쓰면 B안(파트장 계정 위임)으로 간다.
 */
import { createSign } from 'node:crypto';
import { existsSync, readFileSync, statSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.dirname(HERE);
const KEYS = process.env.TEEMO_KEYS || 'C:\\Users\\medib\\teemo\\keys.env';
const MANIFEST = path.join(HERE, '.drive-manifest.json');
const LOG = path.join(ROOT, 'outputs', 'drive-backup.log');
const DRY = process.argv.includes('--dry');
const FULL = !process.argv.includes('--no-full');     // 전량 안전망 레인(기본 켬)
const argVal = (name) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : null; };

// 백업 대상: 생성물 + 참조 사진. 로그·임시·zip 은 다시 만들 수 있으니 뺀다(용량만 먹는다).
export const TARGETS = ['outputs', 'samples'];
export const SKIP_DIRS = new Set(['exports', '__pycache__', '.venv', 'node_modules']);
export const SKIP_EXT = new Set(['.tmp', '.log', '.zip']);
const MAX_BYTES = 200 * 1024 * 1024; // 한 파일 200MB 초과는 백업 대상이 아니다(있으면 사람이 본다)

// ── 자격증명 (값은 로그·화면 어디에도 찍지 않는다) ──────────────────────────
export function readKeys(file = KEYS) {
  const out = {};
  if (!existsSync(file)) return out;
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = /^\s*([A-Z0-9_]+)\s*=\s*"?([^"\r\n]*)"?\s*$/.exec(line);
    if (m) out[m[1]] = m[2];
  }
  return out;
}

/** 무엇이 있고 무엇이 없는지만 돌려준다 — 값은 담지 않는다. */
export function authMode(k) {
  if (!k.GDRIVE_BACKUP_FOLDER_ID) return { mode: null, missing: ['GDRIVE_BACKUP_FOLDER_ID'] };
  if (k.GOOGLE_SA_JSON_B64) return { mode: 'sa', missing: [] };
  if (k.GDRIVE_CLIENT_ID && k.GDRIVE_CLIENT_SECRET && k.GDRIVE_REFRESH_TOKEN)
    return { mode: 'oauth', missing: [] };
  return {
    mode: null,
    missing: ['GOOGLE_SA_JSON_B64 (또는 GDRIVE_CLIENT_ID·GDRIVE_CLIENT_SECRET·GDRIVE_REFRESH_TOKEN)'],
  };
}

const b64url = (b) => Buffer.from(b).toString('base64url');

/** 서비스 계정 JWT 조립·서명. 네트워크는 부르지 않는다(테스트가 여기까지 검사한다). */
export function signJwt(sa, now = Math.floor(Date.now() / 1000)) {
  const header = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const claim = b64url(
    JSON.stringify({
      iss: sa.client_email,
      scope: 'https://www.googleapis.com/auth/drive',
      aud: 'https://oauth2.googleapis.com/token',
      iat: now,
      exp: now + 3600,
    }),
  );
  const sig = createSign('RSA-SHA256').update(`${header}.${claim}`).end().sign(sa.private_key);
  return `${header}.${claim}.${sig.toString('base64url')}`;
}

async function token(k) {
  const { mode } = authMode(k);
  const body =
    mode === 'sa'
      ? new URLSearchParams({
          grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
          assertion: signJwt(JSON.parse(Buffer.from(k.GOOGLE_SA_JSON_B64, 'base64').toString('utf8'))),
        })
      : new URLSearchParams({
          grant_type: 'refresh_token',
          client_id: k.GDRIVE_CLIENT_ID,
          client_secret: k.GDRIVE_CLIENT_SECRET,
          refresh_token: k.GDRIVE_REFRESH_TOKEN,
        });
  const r = await fetch('https://oauth2.googleapis.com/token', { method: 'POST', body });
  const j = await r.json();
  // 오류 본문에 토큰이 섞일 일은 없지만, 혹시 몰라 코드·설명만 꺼낸다.
  if (!r.ok || !j.access_token) throw new Error(`토큰 발급 실패 (${r.status} ${j.error || ''} ${j.error_description || ''})`);
  return j.access_token;
}

// ── 무엇을 올릴 것인가 (순수 함수 — 회귀가 여기를 본다) ─────────────────────
export function walk(dir, base = dir, acc = []) {
  if (!existsSync(dir)) return acc;
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) {
      if (SKIP_DIRS.has(e.name)) continue;
      walk(path.join(dir, e.name), base, acc);
    } else if (e.isFile()) {
      if (SKIP_EXT.has(path.extname(e.name).toLowerCase())) continue;
      const abs = path.join(dir, e.name);
      const st = statSync(abs);
      if (st.size > MAX_BYTES) continue;
      acc.push({ abs, rel: path.relative(base, abs).split(path.sep).join('/'), sig: `${st.size}:${Math.floor(st.mtimeMs)}` });
    }
  }
  return acc;
}

export function plan(root = ROOT, manifest = {}) {
  const files = [];
  for (const t of TARGETS) for (const f of walk(path.join(root, t), root)) files.push(f);
  const todo = files.filter((f) => manifest[f.rel]?.sig !== f.sig);
  return { files, todo };
}

// ── 검수 결과에 따른 레인 배치 (2026-09-08 성연서님 지시 "선택하면 드라이브에 등록,
//    제외하면 넣지 않게") ────────────────────────────────────────────────────
//
// 드라이브 안에서 두 레인으로 갈린다. 목적이 달라서 합치지 않는다:
//   채택본/       — 사람이 **채택**한 사진만. 이게 실제로 쓰는 창고다.
//                   제외·미검수는 여기 절대 안 들어온다(지시 그대로).
//   _원본안전망/  — 전량 사본. PC 가 죽었을 때를 위한 것이지 창고가 아니다
//                   (2026-09-08 어제 지시로 만든 레인 — `--no-full` 로 끌 수 있다).
//   _제외됨/      — 채택했다가 나중에 제외한 사진이 **여기로 옮겨진다**.
//
// ⚠ 내릴 때 지우지 않고 옮기는 이유: 이 백업은 단방향이고 삭제 권한을 안 쓴다.
//   오판으로 제외를 눌러도 파일은 `_제외됨/` 에 그대로 남아 되돌릴 수 있다.
export const LANE_PICKED = '채택본';
export const LANE_FULL = '_원본안전망';
export const LANE_OUT = '_제외됨';
const IMG_RE = /\.(jpe?g|png|webp)$/i;

/** outputs/<배치>/<아이템>/<파일> → "<배치>/<아이템>". 그 밖이면 null. */
export function itemKeyOf(rel) {
  const m = /^outputs\/([^/]+)\/([^/]+)\//.exec(rel);
  return m && m[2] !== 'exports' ? `${m[1]}/${m[2]}` : null;
}

/** 디스크의 review.json + meta.json 을 읽어 아이템별 판정을 모은다(값 판단은 여기 한 곳). */
export function reviews(root = ROOT) {
  const out = {};
  const base = path.join(root, 'outputs');
  if (!existsSync(base)) return out;
  for (const b of readdirSync(base, { withFileTypes: true })) {
    if (!b.isDirectory() || b.name === 'exports') continue;
    for (const it of readdirSync(path.join(base, b.name), { withFileTypes: true })) {
      if (!it.isDirectory()) continue;
      const d = path.join(base, b.name, it.name);
      const rf = path.join(d, 'review.json');
      if (!existsSync(rf)) continue;
      let rv = {}, meta = {};
      try { rv = JSON.parse(readFileSync(rf, 'utf8')); } catch { continue; }
      try { meta = JSON.parse(readFileSync(path.join(d, 'meta.json'), 'utf8')); } catch { /* 메타 없으면 unknown */ }
      out[`${b.name}/${it.name}`] = { pick: rv.pick || null, treatment: meta.treatment || 'unknown', mode: meta.mode || 'unknown' };
    }
  }
  return out;
}

/** 파일 하나가 드라이브 어느 자리로 갈지. 여러 자리일 수 있다(창고 + 안전망). */
export function targetsFor(rel, rv, { full = true } = {}) {
  const out = [];
  if (full) out.push({ dest: `${LANE_FULL}/${rel}`, key: null });
  const key = itemKeyOf(rel);
  const r = key && rv[key];
  if (r && r.pick === 'pick' && IMG_RE.test(rel))
    out.push({ dest: `${LANE_PICKED}/${r.treatment}_${r.mode}/${key.replace('/', '_')}_${path.posix.basename(rel)}`, key });
  return out;
}

/** 올릴 것 + 내릴 것. 순수 함수 — 회귀가 여기를 본다. */
export function planLanes(root = ROOT, manifest = {}, opts = {}) {
  const rv = opts.reviews || reviews(root);
  const files = [];
  for (const t of TARGETS) for (const f of walk(path.join(root, t), root)) files.push(f);
  const todo = [];
  const wanted = new Set();
  for (const f of files)
    for (const t of targetsFor(f.rel, rv, opts)) {
      wanted.add(t.dest);
      if (manifest[t.dest]?.sig !== f.sig) todo.push({ ...f, dest: t.dest, key: t.key });
    }
  // 채택본 레인에 있는데 더 이상 채택이 아닌 것 → 내린다(지우지 않고 _제외됨/ 으로 옮긴다)
  const evict = Object.entries(manifest)
    .filter(([dest, m]) => dest.startsWith(LANE_PICKED + '/') && m.id && !wanted.has(dest))
    .map(([dest, m]) => ({ dest, id: m.id, key: m.key || null }));
  return { files, todo, evict, reviews: rv };
}

/** 아이템 하나의 현재 드라이브 상태 — 화면 배지가 이걸 쓴다. */
export function driveStateOf(key, manifest = {}) {
  for (const [dest, m] of Object.entries(manifest))
    if (dest.startsWith(LANE_PICKED + '/') && m.key === key && m.id) return 'uploaded';
  return 'pending';
}

// ── 드라이브 (여기서부터 네트워크) ──────────────────────────────────────────
const API = 'https://www.googleapis.com/drive/v3';
const UP = 'https://www.googleapis.com/upload/drive/v3';
const COMMON = 'supportsAllDrives=true&includeItemsFromAllDrives=true';

async function gj(url, tok, init = {}) {
  const r = await fetch(url, { ...init, headers: { Authorization: `Bearer ${tok}`, ...(init.headers || {}) } });
  const t = await r.text();
  let j = {};
  try {
    j = t ? JSON.parse(t) : {};
  } catch {
    /* 드라이브가 HTML 오류를 줄 때가 있다 */
  }
  if (!r.ok) {
    const reason = j.error?.errors?.[0]?.reason || '';
    if (reason === 'storageQuotaExceeded')
      throw new Error(
        'storageQuotaExceeded — 서비스 계정은 제 저장용량이 0이다. 백업 폴더를 **공유 드라이브**로 옮기고 ' +
          '그 드라이브에 서비스 계정을 멤버(콘텐츠 관리자)로 넣어라. 개인 폴더만 가능하면 B안(사용자 위임)으로 간다.',
      );
    throw new Error(`${init.method || 'GET'} ${url.split('?')[0]} → ${r.status} ${j.error?.message || t.slice(0, 200)}`);
  }
  return j;
}

/** 경로(a/b/c)를 드라이브 폴더로 만든다. 이미 있으면 그걸 쓴다(같은 이름 두 번 안 만든다). */
async function folderFor(relDir, tok, rootId, cache) {
  if (!relDir || relDir === '.') return rootId;
  if (cache.has(relDir)) return cache.get(relDir);
  const parentRel = path.posix.dirname(relDir);
  const parent = await folderFor(parentRel === '.' ? '' : parentRel, tok, rootId, cache);
  const name = path.posix.basename(relDir);
  const q = encodeURIComponent(
    `'${parent}' in parents and name='${name.replace(/'/g, "\\'")}' and mimeType='application/vnd.google-apps.folder' and trashed=false`,
  );
  const found = await gj(`${API}/files?q=${q}&fields=files(id)&${COMMON}`, tok);
  let id = found.files?.[0]?.id;
  if (!id) {
    const made = await gj(`${API}/files?fields=id&${COMMON}`, tok, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, mimeType: 'application/vnd.google-apps.folder', parents: [parent] }),
    });
    id = made.id;
  }
  cache.set(relDir, id);
  return id;
}

async function upload(file, tok, rootId, cache, prevId) {
  const dir = path.posix.dirname(file.rel);
  const parent = await folderFor(dir === '.' ? '' : dir, tok, rootId, cache);
  const bytes = readFileSync(file.abs);
  const name = path.posix.basename(file.rel);
  if (prevId) {
    // 같은 파일이 바뀐 것 — 새로 만들지 않고 갱신한다(사본이 둘로 갈리지 않게)
    const r = await gj(`${UP}/files/${prevId}?uploadType=media&fields=id&${COMMON}`, tok, {
      method: 'PATCH',
      body: bytes,
    });
    return r.id;
  }
  const boundary = 'bna' + Math.random().toString(36).slice(2);
  const meta = JSON.stringify({ name, parents: [parent] });
  const body = Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${meta}\r\n--${boundary}\r\nContent-Type: application/octet-stream\r\n\r\n`),
    bytes,
    Buffer.from(`\r\n--${boundary}--\r\n`),
  ]);
  const r = await gj(`${UP}/files?uploadType=multipart&fields=id&${COMMON}`, tok, {
    method: 'POST',
    headers: { 'Content-Type': `multipart/related; boundary=${boundary}` },
    body,
  });
  return r.id;
}

/**
 * 채택본에서 내린다 — **지우지 않고** `_제외됨/` 으로 부모만 바꾼다.
 * 이 백업은 삭제 권한을 쓰지 않는다(단방향 원칙). 오판이면 드라이브에서 도로 끌어오면 된다.
 */
async function moveOut(e, tok, rootId, cache) {
  const dest = `${LANE_OUT}/${e.dest.split('/').slice(1, -1).join('/')}`;
  const to = await folderFor(dest.replace(/\/$/, ''), tok, rootId, cache);
  const cur = await gj(`${API}/files/${e.id}?fields=parents&${COMMON}`, tok);
  const from = (cur.parents || []).join(',');
  await gj(`${API}/files/${e.id}?addParents=${to}${from ? `&removeParents=${from}` : ''}&fields=id&${COMMON}`, tok, { method: 'PATCH' });
}

function log(line) {
  try {
    mkdirSync(path.dirname(LOG), { recursive: true });
    writeFileSync(LOG, `[${new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false })}] ${line}\n`, { flag: 'a' });
  } catch {
    /* 로그 실패로 백업을 멈추지 않는다 */
  }
}

async function main() {
  const man = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : {};
  const only = argVal('--item');                       // "<배치>/<아이템>" — 검수 직후 그 한 장만 (즉시 반영)
  let { files, todo, evict } = planLanes(ROOT, man, { full: FULL });
  if (only) {
    todo = todo.filter((f) => f.key === only);
    evict = evict.filter((e) => e.key === only);
  }
  const mb = (n) => (n / 1024 / 1024).toFixed(1);
  const bytes = todo.reduce((s, f) => s + Number(f.sig.split(':')[0]), 0);
  const lane = (d) => d.split('/')[0];

  if (DRY) {
    console.log(`[dry] 대상 ${files.length}개 · 올릴 것 ${todo.length}개(${mb(bytes)}MB) · 내릴 것 ${evict.length}개 · 업로드 0`);
    for (const f of todo.slice(0, 10)) console.log(`  + [${lane(f.dest)}] ${f.dest}`);
    if (todo.length > 10) console.log(`  … 외 ${todo.length - 10}개`);
    for (const e of evict.slice(0, 10)) console.log(`  - [제외] ${e.dest}`);
    return;
  }

  const keys = readKeys();
  const { mode, missing } = authMode(keys);
  if (!mode) {
    const msg = `백업 대기 — 아직 없는 것: ${missing.join(', ')} (파트장님 발급 대기)`;
    console.log(msg);
    log(msg);
    process.exit(3); // 고장이 아니라 '아직'이다. 감시가 이 코드를 빨간불로 세지 않게 한다.
  }

  if (!todo.length && !evict.length) {
    console.log(`올리거나 내릴 것 없음 (대상 ${files.length}개 전부 최신)`);
    return;
  }

  const tok = await token(keys);
  const cache = new Map();
  let done = 0;
  let failed = 0;
  let moved = 0;
  for (const f of todo) {
    try {
      const id = await upload({ ...f, rel: f.dest }, tok, keys.GDRIVE_BACKUP_FOLDER_ID, cache, man[f.dest]?.id);
      man[f.dest] = { sig: f.sig, id, at: Date.now(), key: f.key || undefined };
      done++;
    } catch (e) {
      failed++;
      log(`실패 ${f.dest} — ${e.message}`);
      if (String(e.message).includes('storageQuotaExceeded')) throw e; // 전부 같은 이유로 실패한다
    }
    if (done % 25 === 0) writeFileSync(MANIFEST, JSON.stringify(man)); // 중간에 죽어도 한 일은 남긴다
  }
  // 제외로 바뀐 것 내리기 — 삭제가 아니라 `_제외됨/` 으로 이동이다(오판을 되돌릴 수 있게)
  for (const e of evict) {
    try {
      await moveOut(e, tok, keys.GDRIVE_BACKUP_FOLDER_ID, cache);
      delete man[e.dest];
      moved++;
    } catch (err) {
      failed++;
      log(`내리기 실패 ${e.dest} — ${err.message}`);
    }
  }
  writeFileSync(MANIFEST, JSON.stringify(man));
  const line = `백업 ${done}개 올림(${mb(bytes)}MB)${moved ? ` · 제외로 ${moved}개 내림` : ''}${failed ? ` · 실패 ${failed}` : ''} · 누적 ${Object.keys(man).length}개 · 방식 ${mode}`;
  console.log(line);
  log(line);
  if (failed) process.exit(1);
}

// argv[1] 은 `node -e` 로 부르면 없다 — 없다고 import 자체가 터지면 회귀가 이 모듈을 못 읽는다
if (process.argv[1] && import.meta.url === `file:///${process.argv[1].split(path.sep).join('/')}`) {
  main().catch((e) => {
    console.error('백업 실패:', e.message);
    log(`중단 — ${e.message}`);
    process.exit(1);
  });
}
