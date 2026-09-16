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
 *   node cloud/push-seedbank.mjs [--dry]              # 은행 전부 올린다 / 무엇을 올릴지만 본다
 *   node cloud/push-seedbank.mjs --bank nasolabial    # 한 은행만(다른 은행의 사진·목록은 그대로)
 *   node cloud/push-seedbank.mjs --uploads [--raw <폴더>]   # 강남언니 업로드본만(은행 목록은 올라간 것 그대로).
 *                                                     #   --raw = 이 PC 의 받은 폴더(config 의 raw 가 다른 PC 경로일 때)
 *   node cloud/push-seedbank.mjs --remove             # 올린 것을 전부 내린다(되돌리기)
 *
 * 원본 대신 **축소본**(긴 변 1024)을 올린다 — `ops/seedbank-view.py`.
 *
 * 시술별 은행(2026-09-16 연서님 "시술별로 다르게 볼 수 있도록"): 은행 목록은 `config/seedbank.yaml` 의
 * `banks:` 가 정본이다(pilot = 0909 KOS 회차, nasolabial = 원내 팔자 사진). 사진은 `seedbank/img/<은행>/<파일>`,
 * 목록은 `seedbank/index.json` 하나에 `banks[]` 로 전부 들어간다. prep/measure 가 아직 없는 은행은
 * '정제 전'으로만 목록에 남긴다(사진 0장) — 화면이 그 시술을 비어 있는 채로라도 보여 줘야
 * "어디까지 왔나"가 보인다. 정제 전이라도 `raw/manifest.json`(notion_ba_pull.py)이 있으면 받은 장수·명수는 센다.
 *
 * 업로드본(2026-09-16 연서님 "강남언니에 실제로 올라간 사진, 이걸 바탕으로 학습"): `config/seedbank.yaml` 의 `uploads:`.
 * 씨앗이 아니라 **게시된 전후 쌍**이라 은행과 따로 `index.uploads` 에 싣고, 사진은 `seedbank/img/uploads/<파일>`.
 * 상품 → 우리 시술 키는 `product_map` — 화면이 시술 칩 밑에 붙일 때 쓴다.
 *
 * 토큰은 `bna-project/cloud/.env.local` 의 BLOB_READ_WRITE_TOKEN 을 읽는다(값 미출력).
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { del, get, list, put } from '@vercel/blob';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const ENVFILE = path.join(HERE, '.env.local');
const PREFIX = 'seedbank/';

const DRY = process.argv.includes('--dry');
const REMOVE = process.argv.includes('--remove');
const ONLY = (() => { const i = process.argv.indexOf('--bank'); return i > 0 ? process.argv[i + 1] : null; })();
const UPLOADS_ONLY = process.argv.includes('--uploads');
const RAW_OVERRIDE = (() => { const i = process.argv.indexOf('--raw'); return i > 0 ? process.argv[i + 1] : null; })();

/** yaml 의 한 최상위 키 밑을 들여쓰기로 읽는다 — 값은 문자열뿐, 목록 없음(이 파일이 그 모양이다). yaml 의존성 없음. */
export function readSection(text, key) {
  const root = {};
  const stack = [[-1, root]];
  let inside = false;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\s+#.*$/, '').replace(/^\s*#.*$/, '').trimEnd();
    if (!line.trim()) continue;
    const indent = line.match(/^\s*/)[0].length;
    if (!inside) { if (indent === 0 && line.trim() === key + ':') inside = true; continue; }
    if (indent === 0) break;
    const m = /^\s*([^:]+?):\s*(.*)$/.exec(line);
    if (!m) continue;
    while (stack.length > 1 && stack.at(-1)[0] >= indent) stack.pop();
    const parent = stack.at(-1)[1];
    const k = m[1].trim(), v = m[2].trim().replace(/^["']|["']$/g, '');
    if (v === '') { parent[k] = {}; stack.push([indent, parent[k]]); } else parent[k] = v;
  }
  return root;
}

/** config/seedbank.yaml 의 `banks:` — yaml 의존성 없이 들여쓰기 두 단만 읽는다(drive-backup 과 같은 방식). */
export function readBanks(text = readFileSync(path.join(ROOT, 'config', 'seedbank.yaml'), 'utf8')) {
  const banks = {};
  let inBanks = false, cur = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\s+#.*$/, '').replace(/^#.*$/, '').trimEnd();
    if (!line.trim()) continue;
    if (/^banks:\s*$/.test(line)) { inBanks = true; continue; }
    if (!inBanks) continue;
    if (!/^\s/.test(line)) break;                                   // 들여쓰기 없는 다음 키 = banks 끝
    let m = /^  ([A-Za-z0-9_]+):\s*$/.exec(line);
    if (m) { cur = m[1]; banks[cur] = {}; continue; }
    m = /^    ([A-Za-z0-9_]+):\s*(.+)$/.exec(line);
    if (m && cur) banks[cur][m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
  }
  return banks;
}

export function readUploads(text = readFileSync(path.join(ROOT, 'config', 'seedbank.yaml'), 'utf8')) {
  return readSection(text, 'uploads');
}

function token() {
  if (!existsSync(ENVFILE)) throw new Error(`${ENVFILE} 이 없다 — cloud 에서 vercel env pull 먼저.`);
  for (const line of readFileSync(ENVFILE, 'utf8').split(/\r?\n/)) {
    const m = /^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/.exec(line);
    if (m) return m[1];
  }
  throw new Error('BLOB_READ_WRITE_TOKEN 이 .env.local 에 없다.');
}

const readJson = (f) => JSON.parse(readFileSync(f, 'utf8'));

/** 열람용 축소본을 만든다(PIL). 실패하면 던진다 — 원본을 대신 올리면 안 된다. */
function shrink(dir, view, names) {
  if (!names.length) return;
  const py = ['.venv/Scripts/python.exe', '.venv/bin/python']
    .map((p) => path.join(ROOT, p))
    .find(existsSync) || (process.platform === 'win32' ? 'python' : 'python3');
  const r = spawnSync(py, [path.join(ROOT, 'ops/seedbank-view.py'), dir, view, ...names], {
    encoding: 'utf8',
  });
  if (r.status !== 0) throw new Error(`축소본 생성 실패 — ${(r.stderr || r.stdout || '').trim().split('\n').at(-1)}`);
  process.stdout.write(r.stdout);
}

/** 판정 숫자 → 화면이 그대로 그릴 수 있는 한 덩어리. 여기서 새로 계산하지 않는다.
 *  derivedFiles = 파생 폴더의 파일명 목록(테스트에서 폴더 없이 넣으려고 인자로 받는다). */
export function buildIndex(prep, meas, derivedFiles = []) {
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

  const seeds = (prep['씨앗목록'] || []).map((s) => {
    const id = s.seed.replace(/\.jpg$/, '');
    const mine = derivedFiles.filter((f) => f.startsWith(id + '_'));
    return {
      id,
      img: s.seed,
      src: s['원본'] || null,          // 정제 스크립트가 남긴 원본 상대경로(있으면 manifest 와 잇는다)
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

/** notion_ba_pull.py 의 manifest.json → 정제 전에도 보이는 '받은 것' 요약 + 씨앗에 붙일 사람·전후 표. */
export function rawSummary(manifest) {
  if (!manifest) return null;
  const files = manifest.files || [];
  const people = new Map();
  for (const f of files) {
    const k = `${f.used}/${f.batch}/${f.person}`;
    if (!people.has(k)) people.set(k, { used: f.used, batch: f.batch, person: f.person, partial: !!f.partial, before: 0, after: 0, other: 0 });
    const p = people.get(k);
    if (f.side === '전') p.before++; else if (f.side === '후') p.after++; else p.other++;
  }
  // ⚠ 이름(person)은 싣지 않는다 — 얼굴 옆에 실명이 붙는 순간 무게가 달라진다. 묶음·전후·눈 가림만.
  const bySrc = {};
  for (const f of files) bySrc[f.file] = { used: f.used, batch: f.batch, side: f.side, angle: f.angle, shot: f.shot || null, partial: !!f.partial };
  return {
    pulled_at: manifest.pulled_at || null,
    source: manifest.source || null,
    files: files.length,
    people: people.size,
    partial_people: [...people.values()].filter((p) => p.partial).length,
    by_used: [...people.values()].reduce((a, p) => { a[p.used] = (a[p.used] || 0) + 1; return a; }, {}),
    skipped: (manifest.skipped || []).reduce((a, s) => { a[s.why] = (a[s.why] || 0) + 1; return a; }, {}),
    by_src: bySrc,
  };
}

/** 은행 하나 → index.banks[] 한 칸. 사진 폴더·판정 파일이 없으면 status:'raw' 또는 'empty' 로만 남긴다. */
export function bankEntry(key, b, { derivedFiles, prep, meas, manifest } = {}) {
  const base = { key, name_ko: b.name_ko || key, source: b.source || '', round: b.round || '' };
  const raw = rawSummary(manifest);
  if (!prep || !meas) return { ...base, status: raw ? 'raw' : 'empty', raw, counts: { raw: raw ? raw.files : 0, seeds: 0, derived: 0, no_face: 0 }, seeds: [] };
  const idx = buildIndex(prep, meas, derivedFiles || []);
  for (const s of idx.seeds) {
    if (raw && s.src && raw.by_src[s.src]) s.who = raw.by_src[s.src];
    delete s.src;   // 원본 경로엔 사람 폴더(실명)가 들어 있다 — 잇는 데만 쓰고 목록엔 안 싣는다
  }
  const { by_src, ...rawLite } = raw || {};
  return { ...base, status: 'ready', raw: raw ? rawLite : null, ...idx };
}

/** drive_ba_pull.py 의 manifest(index.csv 그대로) → 상품별 케이스 목록. 사진 이름은 번호가 앞에 있어 폴더 없이도 안 겹친다. */
export function uploadsEntry(key, u, manifest) {
  const base = { key, name_ko: u.name_ko || key, drive: u.drive || '' };
  if (!manifest) return { ...base, status: 'empty', counts: { cases: 0, files: 0, live: 0, stopped: 0 }, products: [] };
  const map = u.product_map || {};
  const fileOf = new Map((manifest.files || []).map((f) => [f.file.split('/').pop(), f]));
  const products = new Map();
  let files = 0, live = 0, stopped = 0;
  for (const r of manifest.rows || []) {
    const before = (r['파일(전)'] || '').trim(), after = (r['파일(후)'] || '').trim();
    if (!before && !after) continue;                                    // 사진 없는 줄(중단·기타)
    const product = r['상품'] || '기타';
    if (!products.has(product)) products.set(product, { product, treatment: map[product] || null, cases: [] });
    const c = {
      no: r['번호'], title: r['제목'] || '', status: r['상태'] || '', tags: (r['시술'] || '').split('|').filter(Boolean),
      gender: r['성별'] || '', age: r['연령'] || '', days: r['경과일'] === '' ? null : Number(r['경과일']),
      before: before && fileOf.has(before) ? before : null, after: after && fileOf.has(after) ? after : null,
    };
    products.get(product).cases.push(c);
    files += (c.before ? 1 : 0) + (c.after ? 1 : 0);
    if (c.status === '게시중') live++; else stopped++;
  }
  const list = [...products.values()].sort((a, b) => b.cases.length - a.cases.length || a.product.localeCompare(b.product, 'ko'));
  return {
    ...base, status: 'ready', pulled_at: manifest.pulled_at || null,
    counts: { cases: list.reduce((a, p) => a + p.cases.length, 0), files, live, stopped },
    products: list,
  };
}

function loadBank(key, b) {
  const has = (p) => p && existsSync(p);
  const prep = has(b.prep) ? readJson(b.prep) : null;
  const meas = has(b.measure) ? readJson(b.measure) : null;
  const manifest = has(b.raw) && existsSync(path.join(b.raw, 'manifest.json')) ? readJson(path.join(b.raw, 'manifest.json')) : null;
  const derivedFiles = has(b.derived) ? readdirSync(b.derived).filter((f) => /\.jpg$/i.test(f)) : [];
  return bankEntry(key, b, { derivedFiles, prep, meas, manifest });
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

  const banks = readBanks();
  const uploadsCfg = readUploads();
  if (ONLY && !banks[ONLY]) throw new Error(`config/seedbank.yaml banks 에 '${ONLY}' 가 없다 (있는 것: ${Object.keys(banks).join(', ')})`);

  // 일부만 올릴 때 나머지는 올라가 있는 목록에서 그대로 가져온다 — 남의 사진을 다시 안 올린다.
  let prev = [], prevUploads = {};
  if (ONLY || UPLOADS_ONLY) {
    try {
      const r = await get(`${PREFIX}index.json`, { access: 'private', token: TOKEN });
      if (r && r.statusCode === 200 && r.stream) {
        const chunks = [];
        for await (const c of r.stream) chunks.push(Buffer.from(c));
        const old = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        prev = old.banks || [];
        prevUploads = old.uploads || {};
        // 은행 나누기 전 모양(seeds 가 맨 위) → pilot 하나로 감싼다. 사진은 옛 자리에 있고 서버가 거기서도 찾는다.
        if (!old.banks && Array.isArray(old.seeds))
          prev = [{ key: 'pilot', name_ko: banks.pilot?.name_ko || '1차 파일럿', source: banks.pilot?.source || '', round: old.round || '',
            status: 'ready', counts: old.counts, exif: old.exif, control: old.control, strength: old.strength, face_found: old.face_found, seeds: old.seeds, raw: null }];
      }
    } catch { prev = []; }
    if (!prev.length) console.log('올라가 있는 은행 목록이 없다 — 은행은 이번 목록에서 빠진다(전체로 다시 올리면 돌아온다).');
  }

  const entries = [];
  const uploads = [];   // {key, abs}
  for (const [key, b] of Object.entries(banks)) {
    if ((ONLY && key !== ONLY) || UPLOADS_ONLY) { const p = prev.find((x) => x.key === key); if (p) entries.push(p); continue; }
    const e = loadBank(key, b);
    entries.push(e);
    if (e.status !== 'ready') {
      console.log(`${key}(${e.name_ko}): ${e.status === 'raw' ? `정제 전 — 받은 사진 ${e.raw.files}장·${e.raw.people}명` : '아직 아무것도 없음'} · 사진 업로드 0`);
      continue;
    }
    const seedNames = e.seeds.map((s) => s.img);
    const derivNames = e.seeds.flatMap((s) => s.derived.map((d) => d.img));
    for (const [dir, names] of [[b.seeds, seedNames], [b.derived, derivNames]]) {
      const gone = names.filter((n) => !existsSync(path.join(dir, n)));
      if (gone.length) throw new Error(`${key}: 사진이 없다: ${gone.join(', ')}`);
    }
    const mb = [...seedNames.map((n) => path.join(b.seeds, n)), ...derivNames.map((n) => path.join(b.derived, n))]
      .reduce((a, f) => a + statSync(f).size, 0) / 1024 / 1024;
    console.log(`${key}(${e.name_ko}): 씨앗 ${e.counts.seeds}장 · 파생 ${e.counts.derived}장 = 사진 ${seedNames.length + derivNames.length}장(원본 ${mb.toFixed(1)}MB → 축소본)`);
    if (DRY) continue;
    // 원본이 아니라 축소본을 올린다 — 격자에서 보기엔 충분하고, 큰 얼굴을 클라우드에 안 둔다.
    const view = path.join(path.dirname(b.seeds), '_view');   // 은행 폴더 옆 열람용 축소본(원본 아님)
    shrink(b.seeds, view, seedNames);
    shrink(b.derived, view, derivNames);
    for (const n of [...seedNames, ...derivNames]) uploads.push({ key: `${PREFIX}img/${key}/${n}`, abs: path.join(view, n) });
  }

  // 업로드본 — 은행과 별개. --bank 로 은행 하나만 올릴 땐 올라간 것을 그대로 둔다.
  const ups = {};
  for (let [key, u] of Object.entries(uploadsCfg)) {
    if (ONLY && !UPLOADS_ONLY) { if (prevUploads[key]) ups[key] = prevUploads[key]; continue; }
    if (RAW_OVERRIDE) u = { ...u, raw: RAW_OVERRIDE };
    const mf = u.raw && existsSync(path.join(u.raw, 'manifest.json')) ? readJson(path.join(u.raw, 'manifest.json')) : null;
    const e = uploadsEntry(key, u, mf);
    ups[key] = e;
    if (e.status !== 'ready') { console.log(`${key}(${e.name_ko}): 아직 받은 것 없음(${u.raw || '경로 없음'}/manifest.json) · 업로드 0`); continue; }
    const names = e.products.flatMap((p) => p.cases.flatMap((c) => [c.before, c.after].filter(Boolean)));
    const byName = new Map((mf.files || []).map((f) => [f.file.split('/').pop(), f.file]));
    const gone = names.filter((n) => !existsSync(path.join(u.raw, byName.get(n))));
    if (gone.length) throw new Error(`${key}: 사진이 없다: ${gone.slice(0, 5).join(', ')}${gone.length > 5 ? ' …' : ''}`);
    const mb = names.reduce((a, n) => a + statSync(path.join(u.raw, byName.get(n))).size, 0) / 1024 / 1024;
    console.log(`${key}(${e.name_ko}): 케이스 ${e.counts.cases}건(게시중 ${e.counts.live}) · 사진 ${names.length}장(원본 ${mb.toFixed(1)}MB → 축소본)`);
    if (DRY) continue;
    // 상품 폴더별로 축소본을 만든다(축소 스크립트는 폴더 하나씩 받는다) → 한 폴더로 모아 올린다
    const view = path.join(u.raw, '_view');
    const byDir = new Map();
    for (const n of names) { const d = path.dirname(byName.get(n)); if (!byDir.has(d)) byDir.set(d, []); byDir.get(d).push(n); }
    for (const [d, ns] of byDir) shrink(path.join(u.raw, d), view, ns);
    for (const n of names) uploads.push({ key: `${PREFIX}img/uploads/${n}`, abs: path.join(view, n) });
  }

  const pilot = entries.find((e) => e.key === 'pilot' && e.status === 'ready');
  const index = {
    generated_at: new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false }),
    banks: entries,
    uploads: ups,
    // 은행 나누기 전 화면(배포 전 창)도 깨지지 않게 pilot 을 옛 자리(맨 위)에도 둔다. 새 화면은 banks 만 본다.
    ...(pilot ? { round: pilot.round, counts: pilot.counts, exif: pilot.exif, control: pilot.control, strength: pilot.strength, face_found: pilot.face_found, seeds: pilot.seeds } : {}),
  };
  if (DRY) {
    console.log(`[dry] 은행 ${entries.length}개(${entries.map((e) => `${e.key}:${e.status}`).join(', ')}) · 업로드본 ${Object.keys(ups).length}개 · 업로드 0건`);
    return;
  }

  const mb = uploads.reduce((a, f) => a + statSync(f.abs).size, 0) / 1024 / 1024;
  for (const f of uploads) {
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
  console.log(`씨앗 은행 열람분 올림 · 은행 ${entries.length}개 · 업로드본 ${Object.keys(ups).length}개 · 사진 ${uploads.length}장(${mb.toFixed(1)}MB) · 기준 ${index.generated_at}`);
}

// 윈도우(C:/…)와 맥(/Users/…) 둘 다 — 손으로 file:/// 를 붙이면 맥에서 슬래시가 하나 남아 main 이 조용히 안 돈다(0916 실측)
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => {
    console.error('실패:', e.message);
    process.exit(1);
  });
}
