/**
 * 회귀 — 드라이브 백업. 네트워크 호출 0, 키 불필요.
 *   node ops/drive-backup-tests.mjs
 *
 * 여기서 지키는 것: ①올릴 목록 판정(새것·바뀐 것만) ②제외 규칙 ③키 없을 때의 처신
 * ④JWT 서명이 진짜 검증되는가 ⑤값이 로그로 새지 않는가.
 */
import { generateKeyPairSync, createVerify } from 'node:crypto';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { plan, walk, authMode, readKeys, signJwt, SKIP_DIRS, SKIP_EXT, planLanes, pickedDest, LANE_PICKED, LANE_OUT } from './drive-backup.mjs';

let fails = 0;
const ok = (cond, msg) => {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + msg);
  if (!cond) fails++;
};

// ── 시료: outputs/ 몇 개 + 제외돼야 할 것들 ────────────────────────────────
const root = mkdtempSync(path.join(tmpdir(), 'bna-backup-'));
mkdirSync(path.join(root, 'outputs', 'b1', '0001'), { recursive: true });
mkdirSync(path.join(root, 'outputs', 'exports', 'x'), { recursive: true });
mkdirSync(path.join(root, 'samples', 'reference'), { recursive: true });
const img = path.join(root, 'outputs', 'b1', '0001', 'after.png');
writeFileSync(img, 'PNGDATA');
writeFileSync(path.join(root, 'outputs', 'b1', 'progress.json'), '{}');
writeFileSync(path.join(root, 'outputs', 'drive-backup.log'), 'log');       // 제외(.log)
writeFileSync(path.join(root, 'outputs', 'b1', '0001', 'x.tmp'), 'tmp');    // 제외(.tmp)
writeFileSync(path.join(root, 'outputs', 'exports', 'x', 'a.zip'), 'zip');  // 제외(exports + .zip)
writeFileSync(path.join(root, 'samples', 'reference', 'ref.jpg'), 'JPG');

// ① 대상 판정 — 생성물·참조는 담고, 로그·임시·exports 는 뺀다
const { files, todo } = plan(root, {});
const rels = files.map((f) => f.rel).sort();
ok(rels.includes('outputs/b1/0001/after.png') && rels.includes('samples/reference/ref.jpg'),
   '생성물·참조 사진은 백업 대상이다');
ok(!rels.some((r) => r.endsWith('.log') || r.endsWith('.tmp') || r.includes('exports/')),
   `로그·임시·exports 는 빠져야 한다 — 실제 ${rels.join(', ')}`);
ok(todo.length === files.length, '원장이 비면 전부 올릴 대상이다');

// ② 이미 올린 것은 건너뛴다 — 크기+수정시각이 같으면 그대로
const man = Object.fromEntries(files.map((f) => [f.rel, { sig: f.sig, id: 'x' }]));
ok(plan(root, man).todo.length === 0, '바뀐 게 없으면 올릴 것도 없어야 한다');

// ③ 내용이 바뀌면 다시 올린다 (사진을 덮어 그린 경우)
writeFileSync(img, 'PNGDATA-CHANGED');
utimesSync(img, new Date(), new Date(Date.now() + 5000));
const again = plan(root, man).todo.map((f) => f.rel);
ok(again.length === 1 && again[0] === 'outputs/b1/0001/after.png',
   `바뀐 파일 1개만 다시 올려야 한다 — 실제 ${again.join(', ')}`);

// ④ 키가 없으면 '고장'이 아니라 '대기'다 — 무엇이 없는지 이름만 말한다
ok(authMode({}).mode === null && authMode({}).missing.length > 0, '키가 없으면 mode=null 이고 빠진 이름을 말한다');
ok(authMode({ GDRIVE_BACKUP_FOLDER_ID: 'f', GOOGLE_SA_JSON_B64: 'x' }).mode === 'sa', '서비스 계정 키가 있으면 sa');
ok(authMode({ GDRIVE_BACKUP_FOLDER_ID: 'f', GDRIVE_CLIENT_ID: 'a', GDRIVE_CLIENT_SECRET: 'b', GDRIVE_REFRESH_TOKEN: 'c' }).mode === 'oauth',
   '리프레시 토큰 3종이면 oauth');
ok(authMode({ GOOGLE_SA_JSON_B64: 'x' }).missing[0] === 'GDRIVE_BACKUP_FOLDER_ID',
   '폴더 ID 가 없으면 그것부터 말한다(어디에 올릴지 모르면 시작도 못 한다)');

// ⑤ JWT — 진짜 서명인가(형식만 맞추고 지나가면 발급 단계에서야 안다)
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const pem = privateKey.export({ type: 'pkcs8', format: 'pem' });
const jwt = signJwt({ client_email: 'bna@test.iam.gserviceaccount.com', private_key: pem }, 1000);
const [h, c, s] = jwt.split('.');
ok(jwt.split('.').length === 3, 'JWT 는 3토막이다');
ok(createVerify('RSA-SHA256').update(`${h}.${c}`).end().verify(publicKey, Buffer.from(s, 'base64url')),
   '서명이 공개키로 검증돼야 한다');
const claim = JSON.parse(Buffer.from(c, 'base64url').toString('utf8'));
ok(claim.exp - claim.iat === 3600 && claim.scope.includes('/auth/drive'), '유효기간 1시간 · drive 스코프');

// ⑥ keys.env 파서 — 따옴표·주석·빈 줄에 안 넘어가야 한다(값은 화면에 안 찍는다)
const kf = path.join(root, 'keys.env');
writeFileSync(kf, '# 주석\nGDRIVE_BACKUP_FOLDER_ID="abc123"\n\nOTHER=zzz\n');
const k = readKeys(kf);
ok(k.GDRIVE_BACKUP_FOLDER_ID === 'abc123', '따옴표는 벗기고 주석·빈 줄은 건너뛴다');
ok(readKeys(path.join(root, 'nope.env')).GDRIVE_BACKUP_FOLDER_ID === undefined, '파일이 없어도 안 터진다');

// ⑦ 제외 규칙은 한 곳에서만 정의된다(두 벌이 되면 조용히 갈린다)
ok(SKIP_DIRS.has('exports') && SKIP_EXT.has('.zip'), '제외 목록은 export 된 상수 하나다');

// ⑧ 삭제는 코드에 아예 없어야 한다 — 백업이 원본을 따라 지워지면 백업이 아니다
const src = (await import('node:fs')).readFileSync(new URL('./drive-backup.mjs', import.meta.url), 'utf8');
ok(!/DELETE/.test(src) && !/\btrash\b/.test(src.replace(/trashed=false/g, '')),
   '드라이브 삭제·휴지통 호출이 없어야 한다(단방향 백업)');

// ⑨ 윈도우 경로 리터럴은 조용히 깨진다 — 백슬래시 하나면 `\t` 가 탭이 된다.
//    (2026-09-10 실측 사고: 동의는 끝나고 금고 이관만 실패해 리프레시 토큰이 평문 txt 로 남을 뻔했다.
//     화면엔 "금고 이관 실패" 한 줄뿐이라, 사람이 안 읽으면 백업은 영영 안 도는 채로 조용하다.)
// 사람이 실행하는 두 진입점을 같은 자로 잰다 — 한쪽만 검사하면 나머지가 사각이 된다.
const fsm = await import('node:fs');
const oauthSrc = ['drive-oauth-setup.mjs', 'drive-connect.mjs']
  .map((f) => fsm.readFileSync(new URL('./' + f, import.meta.url), 'utf8'))
  .join('\n');
// import 로 확인하지 않는다 — 이 모듈은 인자가 없으면 top-level 에서 process.exit(2) 라 테스트가 통째로 죽는다.
// 검사 대상은 '코드'다 — 주석 안의 예시 경로까지 잡으면 설명을 못 쓴다.
const codeOnly = oauthSrc
  .split(/\r?\n/)
  .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
  .join('\n')
  .replace(/String\.raw`[^`]*`/g, 'RAW');
ok(!/(?<!\\)\\Users\\/.test(codeOnly),
   '경로 리터럴에 이스케이프 안 된 백슬래시가 없어야 한다(String.raw 밖)');
// 그리고 그 경로가 실제로 존재해야 한다 — 오타면 "금고 이관 실패" 한 줄로 조용히 끝난다.
const rawPath = /String\.raw`([^`]*install-keys[^`]*)`/.exec(oauthSrc)?.[1];
ok(!!rawPath && !/\t/.test(rawPath) && existsSync(rawPath),
   '금고 이관 대상(install-keys.mjs) 경로가 실제로 존재해야 한다');

// ⑥ 채택본 이름 — 한 사람 = 한 폴더, 전·후만, 마스크 제외 (2026-09-14 성연서님 "알아보기가 너무 힘들고 중복 사진들")
{
  const r2 = mkdtempSync(path.join(tmpdir(), 'bna-lanes-'));
  const it = path.join(r2, 'outputs', '20260911-094915-ab12', '0003');
  mkdirSync(it, { recursive: true });
  const stem = 'nasolabial_selfie_korea30sm_0003';
  writeFileSync(path.join(it, `${stem}_before.jpg`), 'B');
  writeFileSync(path.join(it, `${stem}_after.jpg`), 'A');
  writeFileSync(path.join(it, `${stem}_after_1w.jpg`), 'A1');
  writeFileSync(path.join(it, 'mask.png'), 'M');
  writeFileSync(path.join(it, 'meta.json'), JSON.stringify({ treatment: 'nasolabial', mode: 'selfie',
    variation: { country: { key: 'korea' }, age: { key: '30s' }, gender: { key: 'male' } } }));
  writeFileSync(path.join(it, 'review.json'), JSON.stringify({ pick: 'pick' }));
  const names = { nasolabial: '팔자주름' };
  const L = planLanes(r2, {}, { full: false, names });
  const dests = L.todo.map((f) => f.dest).sort();
  ok(dests.join(' | ') === [
    `${LANE_PICKED}/팔자주름_셀카/0003_한국_30대_남/전.jpg`,
    `${LANE_PICKED}/팔자주름_셀카/0003_한국_30대_남/후.jpg`,
    `${LANE_PICKED}/팔자주름_셀카/0003_한국_30대_남/후_1주.jpg`].sort().join(' | '),
    `채택본은 사람 폴더 안에 전·후(시점)만 — 실제 ${dests.join(', ')}`);
  ok(!dests.some((d) => /mask/i.test(d)), '마스크는 채택본에 올리지 않는다');
  ok(pickedDest('outputs/b/0001/meta.json', { treatment: 'x', mode: 'selfie' }, 'b/0001', names) === null, '그림이 아니면 채택본 자리가 없다');

  // 옛 이름으로 이미 올라간 것은 다시 올리지 않고 드라이브 안에서 옮긴다. 옛 마스크는 _제외됨/ 으로 내린다.
  const key = '20260911-094915-ab12/0003';
  const sigOf = (n) => L.files.find((f) => f.rel.endsWith(n)).sig;
  const oldMan = {
    [`${LANE_PICKED}/nasolabial_selfie/${key.replace('/', '_')}_${stem}_before.jpg`]: { sig: sigOf('_before.jpg'), id: 'idB', key },
    [`${LANE_PICKED}/nasolabial_selfie/${key.replace('/', '_')}_mask.png`]: { sig: sigOf('mask.png'), id: 'idM', key },
  };
  const M = planLanes(r2, oldMan, { full: false, names });
  ok(M.moves.length === 1 && M.moves[0].id === 'idB' && M.moves[0].dest.endsWith('/0003_한국_30대_남/전.jpg'),
    `옛 자리의 같은 파일은 이름만 바꾼다(재업로드 0) — 실제 ${JSON.stringify(M.moves)}`);
  ok(!M.todo.some((f) => f.dest.endsWith('/전.jpg')) && M.todo.length === 2, `옮기는 파일은 올릴 목록에서 빠진다 — 올릴 것 ${M.todo.length}`);
  ok(M.evict.length === 1 && M.evict[0].id === 'idM', '옛 마스크는 내리기 대상이다(지우지 않는다)');
  ok(!M.evict.some((e) => e.id === 'idB'), '옮기는 파일을 내리기로 잡지 않는다');

  // 같은 아이템을 다른 인물로 다시 뽑아 남은 옛 그림은 채택본에 안 들어간다 (2026-09-14 티모 --dry 11자리 충돌)
  writeFileSync(path.join(it, 'nasolabial_selfie_korealate_20sf_0003_before.jpg'), 'OLD-B');
  writeFileSync(path.join(it, 'nasolabial_selfie_korealate_20sf_0003_after.jpg'), 'OLD-A');
  const L2 = planLanes(r2, {}, { full: false, names });
  ok(L2.todo.length === 3 && !L2.todo.some((f) => /korealate_20sf/.test(f.rel)), `옛 인물의 그림은 채택본 자리가 없다 — 올릴 것 ${L2.todo.length}`);
  ok(L2.conflicts.length === 0, '옛 그림을 걸러내면 자리 다툼이 없다');

  // 배치가 달라도 번호·인적사항이 같으면 그때만 폴더 끝에 배치 꼬리(월일-시분)가 붙는다 (1자리 충돌)
  const it2 = path.join(r2, 'outputs', '20260912-101500-zz99', '0003');
  mkdirSync(it2, { recursive: true });
  writeFileSync(path.join(it2, `${stem}_before.jpg`), 'B2');
  writeFileSync(path.join(it2, `${stem}_after.jpg`), 'A2');
  writeFileSync(path.join(it2, 'meta.json'), JSON.stringify({ treatment: 'nasolabial', mode: 'selfie',
    variation: { country: { key: 'korea' }, age: { key: '30s' }, gender: { key: 'male' } } }));
  writeFileSync(path.join(it2, 'review.json'), JSON.stringify({ pick: 'pick' }));
  const L3 = planLanes(r2, {}, { full: false, names });
  const dirs = [...new Set(L3.todo.map((f) => path.posix.dirname(f.dest)))].sort();
  ok(dirs.length === 2 && dirs.every((d) => /0003_한국_30대_남_(0911-0949|0912-1015)$/.test(d)),
    `겹칠 때만 배치 꼬리가 붙어 두 사람이 갈린다 — 실제 ${dirs.join(', ')}`);
  ok(L3.conflicts.length === 0 && L3.todo.length === 5, `꼬리를 붙이면 자리 다툼이 없다 — 올릴 것 ${L3.todo.length}`);
  rmSync(r2, { recursive: true, force: true });
}

// ⑦ 한 자리를 둘 이상이 노리면 아무것도 안 한다 (2026-09-14 티모 — --dry 에서 63자리가 51자리로 접혔다)
{
  const r3 = mkdtempSync(path.join(tmpdir(), 'bna-clash-'));
  const it = path.join(r3, 'outputs', '20260910-153348-63cb', '0001');
  mkdirSync(it, { recursive: true });
  // 한 아이템을 다른 변주로 다시 뽑아 옛 그림이 남았다 — meta 는 최신 변주 하나뿐이라 둘 다 같은 자리를 노린다
  for (const stem of ['nasolabial_selfie_korea30sf_0001', 'nasolabial_selfie_korea30sm_0001']) {
    writeFileSync(path.join(it, `${stem}_before.jpg`), `B-${stem}`);
    writeFileSync(path.join(it, `${stem}_after.jpg`), `A-${stem}`);
  }
  writeFileSync(path.join(it, 'meta.json'), JSON.stringify({ treatment: 'nasolabial', mode: 'selfie',
    variation: { country: { key: 'korea' }, age: { key: '30s' }, gender: { key: 'male' } } }));
  writeFileSync(path.join(it, 'review.json'), JSON.stringify({ pick: 'pick' }));
  const names = { nasolabial: '팔자주름' };
  // (2026-09-14 빌디) 원인을 위에서 막았다 — 옛 인물(korea30sf)의 그림은 채택본 자리를 안 받는다.
  //   그래서 다툼 자체가 없고, 아래 fail-closed 가드는 안전망으로만 남는다.
  const C = planLanes(r3, {}, { full: false, names });
  ok(C.todo.length === 2 && C.todo.every((f) => /korea30sm/.test(f.rel)), `최신 인물의 전·후만 올린다 — 올릴 것 ${C.todo.length}`);
  ok(C.conflicts.length === 0, `옛 인물을 걸러내면 다툼이 없다 — ${C.conflicts.length}`);

  // 이미 올라간 옛 이름: 최신 인물 것은 옮기고, 옛 인물 것은 채택본에서 내린다(검수한 그림이 아니다). 덮어쓰기는 없다.
  const key = '20260910-153348-63cb/0001';
  const sigOf = (n) => C.files.find((f) => f.rel.endsWith(n)).sig;
  const pre = `${LANE_PICKED}/nasolabial_selfie/${key.replace('/', '_')}`;
  const oldMan = {
    [`${pre}_nasolabial_selfie_korea30sf_0001_before.jpg`]: { sig: sigOf('korea30sf_0001_before.jpg'), id: 'idF', key },
    [`${pre}_nasolabial_selfie_korea30sm_0001_before.jpg`]: { sig: sigOf('korea30sm_0001_before.jpg'), id: 'idM', key },
  };
  const D = planLanes(r3, oldMan, { full: false, names });
  ok(D.moves.length === 1 && D.moves[0].id === 'idM' && D.moves[0].dest.endsWith('/0001_한국_30대_남/전.jpg'), `최신 인물의 옛 이름은 옮긴다 — ${JSON.stringify(D.moves)}`);
  ok(D.evict.length === 1 && D.evict[0].id === 'idF', '옛 인물의 그림은 채택본에서 내린다(지우지 않는다)');
  ok(D.conflicts.length === 0, '가드는 안전망으로만 남는다(잡힌 것 0)');
  rmSync(r3, { recursive: true, force: true });
}

rmSync(root, { recursive: true, force: true });
console.log();
console.log(fails ? `실패 ${fails}건` : '전부 통과');
process.exit(fails ? 1 : 0);
