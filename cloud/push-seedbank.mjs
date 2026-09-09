/**
 * 씨앗 은행 열람 경로 — 씨앗·파생 사진을 대시보드에서 볼 수 있게 올린다.
 *
 * 왜 필요한가(2026-09-09 성연서님): "베이스가 될 수 있는 이미지를 확인할 경로가 있나?
 * 내가 로컬을 확인할 수 없어서" — 씨앗은 리포 밖 폴더에만 있어 링크가 아예 없었다.
 *
 * ⚠ 씨앗은 **실제 환자 얼굴**이다. 그래서 이 스크립트는 세 가지를 지킨다:
 *   ① Blob 은 private — 주소를 알아도 못 연다. 화면은 `/seedfiles/` 를 거치고,
 *      그 경로는 로그인 + **관리자 직급**에서만 열린다(app.js 정본).
 *   ② prefix 가 `seedbank/` 다. `files/` 로 올리면 push-cloud 의 청소 단계가
 *      "화면이 안 부르는 사진"으로 보고 매 회차 지운다(그쪽 prune 은 prefix 'files/').
 *   ③ 원본(raw)은 올리지 않는다 — 씨앗이 곧 그 원본의 정제본이라 답이 같은데
 *      노출만 두 배가 된다. EXIF·GPS 도 씨앗에서만 제거돼 있다.
 *
 *   node cloud/push-seedbank.mjs [--dry]     # 올린다 / 무엇을 올릴지만 본다
 *   node cloud/push-seedbank.mjs --remove    # 올린 것을 전부 내린다(되돌리기)
 *
 * 원본 대신 **축소본**(긴 변 1024)을 올린다 — `ops/seedbank-view.py`.
 *
 * 토큰은 `bna-project/cloud/.env.local` 의 BLOB_READ_WRITE_TOKEN 을 읽는다(값 미출력).
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { del, list, put } from '@vercel/blob';

const RAW = 'C:/Users/medib/teemo-raw';
const SEEDS = path.join(RAW, 'seeds');
const DERIVED = path.join(RAW, 'derived');
const OUT = 'C:/Users/medib/teemo/out';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const VIEW = path.join(RAW, '_view'); // 열람용 축소본(원본 아님) — 여기 것만 올린다
const ENVFILE = path.join(HERE, '.env.local');
const PREFIX = 'seedbank/';

const DRY = process.argv.includes('--dry');
const REMOVE = process.argv.includes('--remove');

function token() {
  if (!existsSync(ENVFILE)) throw new Error(`${ENVFILE} 이 없다 — cloud 에서 vercel env pull 먼저.`);
  for (const line of readFileSync(ENVFILE, 'utf8').split(/\r?\n/)) {
    const m = /^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/.exec(line);
    if (m) return m[1];
  }
  throw new Error('BLOB_READ_WRITE_TOKEN 이 .env.local 에 없다.');
}

const readJson = (f) => JSON.parse(readFileSync(path.join(OUT, f), 'utf8'));

/** 열람용 축소본을 만든다(PIL). 실패하면 던진다 — 원본을 대신 올리면 안 된다. */
function shrink(dir, names) {
  if (!names.length) return;
  const py = ['.venv/Scripts/python.exe', '.venv/bin/python']
    .map((p) => path.join(ROOT, p))
    .find(existsSync) || 'python';
  const r = spawnSync(py, [path.join(ROOT, 'ops/seedbank-view.py'), dir, VIEW, ...names], {
    encoding: 'utf8',
  });
  if (r.status !== 0) throw new Error(`축소본 생성 실패 — ${(r.stderr || r.stdout || '').trim().split('\n').at(-1)}`);
  process.stdout.write(r.stdout);
}

/** 판정 숫자 → 화면이 그대로 그릴 수 있는 한 덩어리. 여기서 새로 계산하지 않는다. */
export function buildIndex(prep, meas) {
  const ctrl = meas['대조군_씨앗끼리(서로 다른 실제 사람)'];
  const byDeriv = new Map(meas['건별'].map((r) => [r['파생'], r]));

  // 같은 사람 의심 쌍 → 씨앗별 목록으로 뒤집는다(화면은 한 장씩 그린다).
  const dup = new Map();
  for (const { a, b, sim } of prep['씨앗끼리_같은사람_의심(≥0.45)'] || []) {
    for (const [x, y] of [[a, b], [b, a]]) {
      if (!dup.has(x)) dup.set(x, []);
      dup.get(x).push({ with: y.replace(/\.jpg$/, ''), sim });
    }
  }

  const derivedFiles = existsSync(DERIVED) ? readdirSync(DERIVED).filter((f) => /\.jpg$/i.test(f)) : [];

  const seeds = (prep['씨앗목록'] || []).map((s) => {
    const id = s.seed.replace(/\.jpg$/, '');
    const mine = derivedFiles.filter((f) => f.startsWith(id + '_'));
    return {
      id,
      img: s.seed,
      size: s['씨앗해상도'],
      kb: s['씨앗KB'],
      exif_left: (s['EXIF잔존'] || []).length,
      dup: dup.get(s.seed) || [],
      derived: mine.map((f) => {
        const r = byDeriv.get(f) || null;
        return {
          img: f,
          strength: /_kin\./.test(f) ? 'kin' : 'fresh',
          sim_own: r ? r['제씨앗과'] : null,
          sim_other_max: r ? r['남의씨앗과_최대'] : null,
          over_p90: r ? r['대조군_p90_초과'] : null,
          over_max: r ? r['대조군_최대_초과'] : null,
        };
      }),
    };
  });

  return {
    generated_at: new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false }),
    round: '2026-09-09 1차 파일럿',
    counts: {
      raw: prep['받은원본'],
      seeds: prep['씨앗확정'],
      derived: derivedFiles.length,
      no_face: prep['얼굴없음(시술부위 등)'],
    },
    exif: prep.EXIF,
    control: ctrl,
    strength: meas['강도별_제씨앗과의_유사도'],
    face_found: meas['파생_얼굴검출'],
    seeds,
  };
}

async function main() {
  const TOKEN = token();

  if (REMOVE) {
    let cursor, n = 0;
    do {
      const page = await list({ token: TOKEN, prefix: PREFIX, cursor, limit: 1000 });
      for (const b of page.blobs) {
        if (!DRY) await del(b.url, { token: TOKEN });
        n++;
      }
      cursor = page.hasMore ? page.cursor : null;
    } while (cursor);
    console.log(`${DRY ? '[dry] ' : ''}씨앗 은행 열람분 내림 · ${n}건`);
    return;
  }

  const index = buildIndex(readJson('seed-prep.json'), readJson('seed-measure.json'));

  const seedNames = index.seeds.map((s) => s.img);
  const derivNames = index.seeds.flatMap((s) => s.derived.map((d) => d.img));
  for (const [dir, names] of [[SEEDS, seedNames], [DERIVED, derivNames]]) {
    const gone = names.filter((n) => !existsSync(path.join(dir, n)));
    if (gone.length) throw new Error(`사진이 없다: ${gone.join(', ')}`);
  }

  if (DRY) {
    const mb = [...seedNames.map((n) => path.join(SEEDS, n)), ...derivNames.map((n) => path.join(DERIVED, n))]
      .reduce((a, f) => a + statSync(f).size, 0) / 1024 / 1024;
    console.log(
      `[dry] 씨앗 ${index.counts.seeds}장 · 파생 ${index.counts.derived}장 = 사진 ${
        seedNames.length + derivNames.length
      }장(원본 ${mb.toFixed(1)}MB → 축소본 업로드) · 업로드 0건`,
    );
    return;
  }

  // 원본이 아니라 축소본을 올린다 — 격자에서 보기엔 충분하고, 큰 얼굴을 클라우드에 안 둔다.
  shrink(SEEDS, seedNames);
  shrink(DERIVED, derivNames);
  const files = [...seedNames, ...derivNames].map((n) => ({ key: `${PREFIX}img/${n}`, abs: path.join(VIEW, n) }));
  const mb = files.reduce((a, f) => a + statSync(f.abs).size, 0) / 1024 / 1024;

  for (const f of files) {
    await put(f.key, readFileSync(f.abs), {
      access: 'private',
      token: TOKEN,
      addRandomSuffix: false,
      allowOverwrite: true,
    });
  }
  // 사진을 다 올린 **뒤** 목록을 올린다 — 먼저 올리면 화면이 아직 없는 사진을 부른다.
  await put(`${PREFIX}index.json`, JSON.stringify(index), {
    access: 'private',
    token: TOKEN,
    addRandomSuffix: false,
    allowOverwrite: true,
    contentType: 'application/json',
  });
  console.log(`씨앗 은행 열람분 올림 · 사진 ${files.length}장(${mb.toFixed(1)}MB) · 기준 ${index.generated_at}`);
}

if (import.meta.url === `file:///${process.argv[1].replace(/\\/g, '/')}`) {
  main().catch((e) => {
    console.error('실패:', e.message);
    process.exit(1);
  });
}
