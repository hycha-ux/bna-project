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
import { put } from '@vercel/blob';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const OUT = path.join(ROOT, 'outputs');
const DRY = process.argv.includes('--dry');
const RUNNING_PORT = 8765; // api.py 기본 포트 — 이미 떠 있으면 그걸 쓴다
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
    return (q.jobs || []).some((j) => !['done', 'failed', 'cancelled'].includes(j.status));
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

async function main() {
  const TOKEN = DRY ? null : token();
  const proc = await connect();
  let uploaded = 0;
  let skipped = 0;
  try {
    // ── 1. 원장 긁기 (로컬 API 응답 그대로) ──────────────────────────────────
    const [config, batches, queue, library] = await Promise.all([
      getJson('/api/config'),
      getJson('/api/batches'),
      getJson('/api/queue'),
      getJson('/api/library'),
    ]);
    const overview = {};
    for (const d of DAYS) overview[String(d)] = await getJson(`/api/overview?days=${d}`);

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
        for (const f of [it.before_file, it.after_file]) {
          if (!f) continue;
          const abs = path.join(OUT, bid, it.item_id, f);
          if (existsSync(abs)) files.push({ key: `files/${bid}/${it.item_id}/${f}`, abs });
        }
      }
    }

    const snap = {
      generated_at: new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false }),
      source: 'office-pc',
      config,
      batches,
      queue,
      library,
      overview,
      items,
      progress,
      file_count: files.length,
    };

    if (DRY) {
      console.log(
        `[dry] 배치 ${batches.length} · 이미지 ${files.length}장 · 스냅샷 ${(
          JSON.stringify(snap).length / 1024
        ).toFixed(0)}KB · 업로드 0건`,
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
    writeFileSync(MANIFEST, JSON.stringify(man));

    // ── 4. 스냅샷은 마지막에 — 먼저 올리면 화면이 아직 없는 사진을 부른다 ──────
    await put('snapshot.json', JSON.stringify(snap), {
      access: 'private',
      token: TOKEN,
      addRandomSuffix: false,
      allowOverwrite: true,
      contentType: 'application/json',
    });

    console.log(
      `푸시 완료 · 배치 ${batches.length} · 이미지 ${files.length}장(새로 ${uploaded} · 그대로 ${skipped}) · 기준 ${snap.generated_at}`,
    );
  } finally {
    if (proc) proc.kill();
  }
}

main().catch((e) => {
  console.error('푸시 실패:', e.message);
  process.exit(1);
});
