/**
 * 사무실 PC → 클라우드 스냅샷 푸시 (백엔드 연결의 실체).
 *
 * 왜 이 모양인가: 생성 작업은 몇 분씩 걸리고 유료 API를 부르므로 서버리스에 못 얹는다.
 * 그래서 주방(생성·큐)은 이 PC에 두고, 진열대(보기)만 클라우드에 둔다.
 *
 * 집계를 여기서 다시 짜지 않는다 — 로컬 API(src/bna/api.py)의 응답을 그대로 긁어
 * 올린다. 두 곳에서 따로 계산하면 화면 둘이 조용히 갈린다(정본 하나 규칙).
 *
 *   node cloud/push-cloud.mjs          # 실제 업로드
 *   node cloud/push-cloud.mjs --dry    # 무엇을 올릴지만 출력(업로드 0)
 *
 * ⚠ 이 스크립트가 로컬 API 를 직접 띄울 때, api.py 의 main() 은 큐 러너도 같이 깨운다
 *   = 밀린 작업이 있으면 *돈이 나간다*. 그래서 큐가 비어 있지 않으면 띄우지 않고 멈춘다
 *   (이미 서버가 떠 있으면 그걸 그대로 쓰고 죽이지도 않는다).
 *
 * 토큰은 cloud/.env.local 의 BLOB_READ_WRITE_TOKEN 을 읽는다(gitignore, 값 미출력).
 */
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { del, list, put } from '@vercel/blob';
import * as REV from './lib/reviews.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const OUT = path.join(ROOT, 'outputs');
const DRY = process.argv.includes('--dry');
const RUNNING_PORT = Number(process.env.BNA_LOCAL_API_PORT) || 8765; // api.py 포트 — 이미 떠 있으면 그걸 쓴다(훅이 물려준다)
const SPAWN_PORT = 8799;
const DAYS = [7, 14, 30, 90]; // 화면의 1주·2주·1개월·3개월 버튼과 한 쌍이다
const MANIFEST = path.join(HERE, '.push-manifest.json');

let BASE = `http://127.0.0.1:${SPAWN_PORT}`;

function token() {
  const f = path.join(HERE, '.env.local');
  if (!existsSync(f))
    throw new Error('cloud/.env.local 이 없다. `cd cloud && npx vercel env pull` 을 먼저 돌려라.');
  for (const line of readFileSync(f, 'utf8').split(/\r?\n/)) {
    const m = /^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/.exec(line);
    if (m) return m[1];
  }
  throw new Error('cloud/.env.local 에 BLOB_READ_WRITE_TOKEN 이 없다.');
}

function python() {
  for (const p of ['.venv/Scripts/python.exe', '.venv/bin/python']) {
    const abs = path.join(ROOT, p);
    if (existsSync(abs)) return abs;
  }
  return 'python';
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function alive(base) {
  try {
    const r = await fetch(base + '/api/config', { signal: AbortSignal.timeout(1500) });
    return r.ok;
  } catch {
    return false;
  }
}

async function getJson(p) {
  const r = await fetch(BASE + p);
  if (!r.ok) throw new Error(`${p} → HTTP ${r.status}`);
  return r.json();
}

function queueIsBusy() {
  const f = path.join(OUT, 'queue.json');
  if (!existsSync(f)) return false;
  try {
    const q = JSON.parse(readFileSync(f, 'utf8'));
    // 큐가 실제로 쓰는 상태는 queued · running · done · error · cancelled 다(src/bna/queue.py).
    // ⚠ 종전 목록엔 `error` 가 빠지고 **없는 값 `failed`** 가 들어 있었다 — 그래서 오류로 끝난
    //   작업이 하나라도 있으면 큐가 영원히 '바쁨'으로 잡혀, 로컬 API 가 꺼진 동안 10분 배치가
    //   조용히 아무것도 안 올렸다(2026-09-10 실측: error 1건이 6개월째 남을 수도 있었다).
    //   모르는 상태는 종전대로 '바쁨'으로 본다(fail-closed — 오판 비용이 돈이다).
    const TERMINAL = ['done', 'error', 'cancelled'];
    return (q.jobs || []).some((j) => !TERMINAL.includes(j.status));
  } catch {
    return true; // 못 읽으면 띄우지 않는다(fail-closed — 오판 비용이 돈이다)
  }
}

async function connect() {
  if (await alive(`http://127.0.0.1:${RUNNING_PORT}`)) {
    BASE = `http://127.0.0.1:${RUNNING_PORT}`;
    console.log(`이미 떠 있는 로컬 API 사용 (${RUNNING_PORT}) — 건드리지 않는다`);
    return null;
  }
  if (queueIsBusy())
    throw new Error(
      '큐에 밀린 작업이 있어 로컬 API 를 대신 띄우지 않는다(띄우면 생성이 재개돼 비용이 난다).\n' +
        '  → 사람이 `PYTHONPATH=src python -m bna.api` 로 직접 띄운 뒤 이 명령을 다시 돌려라.',
    );

  const proc = spawn(python(), ['-m', 'bna.api', '--port', String(SPAWN_PORT), '--no-open'], {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: 'src' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let err = '';
  proc.stderr.on('data', (d) => (err += d.toString()));
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    if (await alive(BASE)) return proc;
    if (proc.exitCode != null) throw new Error('로컬 API 가 죽었다:\n' + err.slice(-800));
  }
  proc.kill();
  throw new Error('로컬 API 가 30초 안에 안 떴다:\n' + err.slice(-800));
}

/**
 * 클라우드에서 누른 검수를 이 PC 로 가져온다 (2026-09-08).
 *
 * 순서가 중요하다: **흡수 → 스냅샷 생성 → 업로드 → 흡수분 삭제.**
 * 삭제를 먼저 하면 그 사이 화면이 옛 스냅샷을 읽어 방금 누른 판정이 사라져 보인다.
 *
 * 로컬 API 를 거쳐 저장하는 이유: 그래야 드라이브 등록·프롬프트 학습 훅이 같이 탄다
 * (파일에 직접 쓰면 그 두 가지가 조용히 빠진다). 실패하면 지우지 않고 다음 회차가 잇는다.
 */
async function absorbReviews(TOKEN) {
  if (!TOKEN) return { taken: 0, done: [] };
  let blobs = [];
  try {
    let cursor;
    do {
      const page = await list({ token: TOKEN, prefix: REV.PREFIX, cursor, limit: 1000 });
      blobs.push(...page.blobs);
      cursor = page.hasMore ? page.cursor : null;
    } while (cursor);
  } catch (e) {
    console.log('  검수 흡수 건너뜀 —', e.message);   // 못 읽어도 업로드는 계속한다
    return { taken: 0, done: [] };
  }
  const done = [];
  const failed = [];
  for (const b of blobs) {
    const id = REV.parseBlobName(b.pathname);
    if (!id) continue;
    try {
      // ⚠ `fetch(b.url)` 로 읽지 마라 — 이 저장소는 private 이라 `Forbidden` 이다.
      //   읽기는 REV.readOne 한 곳이다(화면 오버레이와 같은 경로).
      const rv = await REV.readOne(TOKEN, b.pathname);
      if (!rv) { failed.push(b.pathname); continue; }
      const local = readLocalReview(id.batch, id.item);
      // 이 PC 에서 더 나중에 고친 게 있으면 클라우드 값이 이기지 않는다(양쪽 다 사람이 누른다)
      if (local && (local.updated_at || 0) > (rv.updated_at || 0)) { done.push(b); continue; }
      const r = await fetch(BASE + '/api/review', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch: id.batch, item: id.item, pick: rv.pick ?? null, tags: rv.tags || [], note: rv.note || '' }),
      });
      if (r.ok) done.push(b); else failed.push(`${b.pathname} (API ${r.status})`);
    } catch (e) { failed.push(`${b.pathname} (${e.message})`); }   // 한 건 실패가 회차를 죽이지 않는다
  }
  // 조용한 실패가 이 고리의 실패 모드였다 — 남은 게 있으면 반드시 소리를 낸다.
  if (failed.length) {
    console.log(`  ⚠ 검수 흡수 실패 ${failed.length}건 / 전체 ${blobs.length}건 — 사람이 누른 판정이 이 PC 에 안 들어왔다`);
    for (const f of failed.slice(0, 5)) console.log('     ·', f);
  }
  return { taken: done.length, done, failed: failed.length, seen: blobs.length };
}

function readLocalReview(batch, item) {
  const f = path.join(OUT, batch, item, 'review.json');
  try { return JSON.parse(readFileSync(f, 'utf8')); } catch { return null; }
}

async function main() {
  const TOKEN = DRY ? null : token();
  const proc = await connect();
  let uploaded = 0;
  let skipped = 0;
  try {
    // ── 0. 클라우드에서 누른 검수를 먼저 흡수한다 (그래야 아래 스냅샷에 실린다) ──
    const absorbed = await absorbReviews(TOKEN);
    if (absorbed.taken) console.log(`  클라우드 검수 ${absorbed.taken}건 반영`);

    // ── 1. 원장 긁기 (로컬 API 응답 그대로) ──────────────────────────────────
    const [config, allBatches, queue, library] = await Promise.all([
      getJson('/api/config'),
      getJson('/api/batches'),
      getJson('/api/queue'),
      getJson('/api/library'),
    ]);

    // 데모 배치(`--demo` 가 만든 가짜 그림)는 올리지 않는다 — 공유 화면에 섞이면
    // 보는 사람이 실제 성과로 읽는다(2026-09-08 성연서님 "더미 데이터로 있는 거 같아").
    const batches = allBatches.filter((b) => b.kind !== 'demo');
    const dropped = allBatches.length - batches.length;
    const overview = {};
    for (const d of DAYS) overview[String(d)] = await getJson(`/api/overview?days=${d}`);
    // 학습 탭 — 인터넷 화면에서 "없는 경로: /api/lessons" 로 통째로 비어 있었다 (2026-09-10 성연서님).
    // 집계는 PC 원장 기준이라 스냅샷에 실어 보내고, 승격(쓰기)만 PC 에서 한다.
    let lessons = null;
    try { lessons = await getJson('/api/lessons'); } catch (e) { console.log('  학습 집계 건너뜀 —', e.message); }

    const items = {};
    const progress = {};
    for (const b of batches) {
      items[b.batch_id] = await getJson('/api/batches/' + b.batch_id);
      try {
        progress[b.batch_id] = await getJson(`/api/batches/${b.batch_id}/progress`);
      } catch {
        /* 진행 파일이 없는 배치는 정상 — 값 없음으로 둔다 */
      }
    }

    // ── 2. 이미지 목록 (화면이 부르는 경로 그대로) ────────────────────────────
    const files = [];
    for (const [bid, detail] of Object.entries(items)) {
      for (const it of detail.items || []) {
        // 전·후만 올리면 검수 화면의 시술 부위 표시(mask.png)와 시리즈 시점별 후 사진이 인터넷에서 404 다 —
        // 버튼은 켜지는데 아무것도 안 그려졌다 (2026-09-10 성연서님 "온해도 안 보인다").
        const wanted = [it.before_file, it.after_file, it.mask_file, ...Object.values(it.after_files || {})];
        for (const f of [...new Set(wanted)]) {
          if (!f) continue;
          const abs = path.join(OUT, bid, it.item_id, f);
          if (existsSync(abs)) files.push({ key: `files/${bid}/${it.item_id}/${f}`, abs });
        }
      }
    }

    const snap = {
      generated_at: new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false }),
      generated_ts: Date.now() / 1000,             // 화면의 "다음 갱신까지" 카운트다운용 (2026-09-10 성연서님)
      source: 'office-pc',
      config,
      batches,
      queue,
      library,
      overview,
      lessons,
      items,
      progress,
      file_count: files.length,
    };

    if (DRY) {
      console.log(
        `[dry] 배치 ${batches.length}${dropped ? `(데모 ${dropped} 제외)` : ''} · 이미지 ${
          files.length
        }장 · 스냅샷 ${(JSON.stringify(snap).length / 1024).toFixed(0)}KB · 업로드 0건`,
      );
      return;
    }

    // ── 3. 이미지 업로드 (크기·수정시각이 같으면 건너뛴다) ────────────────────
    const man = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : {};
    for (const f of files) {
      const st = statSync(f.abs);
      const sig = `${st.size}:${Math.floor(st.mtimeMs)}`;
      if (man[f.key] === sig) {
        skipped++;
        continue;
      }
      await put(f.key, readFileSync(f.abs), {
        access: 'private',
        token: TOKEN,
        addRandomSuffix: false,
        allowOverwrite: true,
      });
      man[f.key] = sig;
      uploaded++;
    }
    // ── 3-2. 이제 화면이 안 부르는 사진은 클라우드에서 지운다 ─────────────────
    // 안 지우면 데모·삭제한 배치의 사진이 창고에 영영 남는다(사람 얼굴이라 더 그렇다).
    const want = new Set(files.map((f) => f.key));
    let pruned = 0;
    let cursor;
    do {
      const page = await list({ token: TOKEN, prefix: 'files/', cursor, limit: 1000 });
      const gone = page.blobs.filter((b) => !want.has(b.pathname));
      for (const b of gone) {
        await del(b.url, { token: TOKEN });
        delete man[b.pathname];
        pruned++;
      }
      cursor = page.hasMore ? page.cursor : null;
    } while (cursor);

    writeFileSync(MANIFEST, JSON.stringify(man));

    // ── 4. 스냅샷은 마지막에 — 먼저 올리면 화면이 아직 없는 사진을 부른다 ──────
    await put('snapshot.json', JSON.stringify(snap), {
      access: 'private',
      token: TOKEN,
      addRandomSuffix: false,
      allowOverwrite: true,
      contentType: 'application/json',
    });

    // ── 5. 흡수한 검수만 지운다 — 스냅샷을 올린 **뒤**여야 화면이 안 되돌아간다 ──
    for (const b of absorbed.done) {
      try { await del(b.url, { token: TOKEN }); } catch { /* 남으면 다음 회차가 다시 흡수한다(멱등) */ }
    }

    console.log(
      `푸시 완료 · 배치 ${batches.length}${dropped ? `(데모 ${dropped} 제외)` : ''} · 이미지 ${
        files.length
      }장(새로 ${uploaded} · 그대로 ${skipped}${pruned ? ` · 지움 ${pruned}` : ''})${
        absorbed.taken ? ` · 클라우드 검수 ${absorbed.taken}건 반영` : ''
      } · 기준 ${snap.generated_at}`,
    );
  } finally {
    if (proc) proc.kill();
  }
}

main().catch((e) => {
  console.error('푸시 실패:', e.message);
  process.exit(1);
});
