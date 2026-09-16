/**
 * 씨앗 은행 목록 회귀 (2026-09-16, 시술별 은행) — `node cloud/seedbank-tests.mjs`
 *
 * 네트워크·사진 없이 돈다. prep/measure/manifest 를 가짜로 넣고 `index.json` 의 모양만 본다.
 * 왜: 은행이 갈리면서 사진 주소가 `img/<은행>/<파일>` 로 바뀌었다 — 옛 주소로 그리면 전부 404 인데
 *     화면은 빈 격자를 조용히 보여 준다. 그런 조용한 고장은 회귀로만 잡는다.
 */
import { bankEntry, buildIndex, rawSummary, readBanks, readSection, readUploads, uploadsEntry } from './push-seedbank.mjs';

const fails = [];
const ok = (cond, label) => {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + label);
  if (!cond) fails.push(label);
};

// ── config/seedbank.yaml 의 banks ─────────────────────────────────────────
const banks = readBanks();
ok(banks.pilot && banks.nasolabial, 'banks 에 pilot(0909 KOS)·nasolabial(원내 팔자) 둘이 있다');
ok(banks.nasolabial.name_ko === '팔자필러', '팔자 은행 이름이 화면에 그대로 뜬다');
ok(/^C:\//.test(banks.nasolabial.raw) && !/bna/.test(banks.nasolabial.raw), '원본 폴더는 리포 밖(티모 PC)');
ok(banks.pilot.derived === 'C:/Users/medib/teemo-raw/derived', 'pilot 은 옛 pool_dir 과 같은 곳(자[尺]를 잃지 않는다)');
const yaml = 'banks:\n  a:\n    name_ko: 가   # 주석\n    seeds: C:/x/seeds\n  b:\n    name_ko: 나\npool_dir: C:/old\n';
const rb = readBanks(yaml);
ok(rb.a.name_ko === '가' && rb.a.seeds === 'C:/x/seeds' && rb.b.name_ko === '나' && !rb.pool_dir, 'yaml 두 단만 읽고 주석·다음 키는 무시');

// ── 가짜 판정 파일 ──────────────────────────────────────────────────────────
const prep = {
  받은원본: 10, 씨앗확정: 2, '얼굴없음(시술부위 등)': 1, EXIF: { '위치(GPS)': 3, 씨앗잔존: 0 },
  씨앗목록: [
    { seed: 'seed-0001.jpg', 씨앗해상도: '1200x1600', 씨앗KB: 300, EXIF잔존: [], 원본: '사용전/260623/정인좌/전_4.jpg' },
    { seed: 'seed-0002.jpg', 씨앗해상도: '1000x1300', 씨앗KB: 250, EXIF잔존: [] },
  ],
  '씨앗끼리_같은사람_의심(≥0.45)': [{ a: 'seed-0001.jpg', b: 'seed-0002.jpg', sim: 0.5 }],
};
const meas = {
  '대조군_씨앗끼리(서로 다른 실제 사람)': { 평균: 0.1, 최대: 0.3, p90: 0.168 },
  건별: [{ 파생: 'seed-0001_kin.jpg', 제씨앗과: 0.12, 남의씨앗과_최대: 0.2, 대조군_p90_초과: false, 대조군_최대_초과: false }],
  강도별_제씨앗과의_유사도: {}, 파생_얼굴검출: {},
};
const manifest = {
  pulled_at: '2026-09-16T14:00:00+09:00', source: { kind: 'notion' },
  files: [
    { file: '사용전/260623/정인좌/전_4.jpg', used: '사용전', batch: '260623', person: '정인좌', side: '전', angle: 4, partial: true },
    { file: '사용전/260623/정인좌/후_5.jpg', used: '사용전', batch: '260623', person: '정인좌', side: '후', angle: 5, partial: true },
    { file: '사용완료/-/p01/전.jpg', used: '사용완료', batch: '-', person: 'p01', side: '전', angle: null, partial: false },
  ],
  skipped: [{ why: 'AI 생성물' }, { why: 'AI 생성물' }, { why: '셀카 묶음' }],
};

const idx = buildIndex(prep, meas, ['seed-0001_kin.jpg', 'other.jpg']);
ok(idx.counts.seeds === 2 && idx.counts.derived === 2, '씨앗·파생 장수는 판정 파일과 폴더에서 그대로');
ok(idx.seeds[0].derived.length === 1 && idx.seeds[0].derived[0].strength === 'kin', '파생은 제 씨앗 이름으로 시작하는 것만 붙는다');
ok(idx.seeds[0].dup.length === 1 && idx.seeds[1].dup.length === 1, '같은 사람 의심 쌍은 양쪽 씨앗에 다 붙는다');
ok(idx.seeds[0].src === '사용전/260623/정인좌/전_4.jpg' && idx.seeds[1].src === null, '정제가 남긴 원본 경로가 있으면 실린다');

const raw = rawSummary(manifest);
ok(raw.files === 3 && raw.people === 2 && raw.partial_people === 1, '받은 것 요약: 장수·명수·눈 가릴 분');
ok(raw.by_used['사용전'] === 1 && raw.by_used['사용완료'] === 1, '묶음별 명수');
ok(raw.skipped['AI 생성물'] === 2 && raw.skipped['셀카 묶음'] === 1, '제외 사유별 장수(왜 빠졌는지가 남는다)');

const ready = bankEntry('nasolabial', banks.nasolabial, { derivedFiles: ['seed-0001_kin.jpg'], prep, meas, manifest });
ok(ready.status === 'ready' && ready.key === 'nasolabial' && ready.name_ko === '팔자필러', '판정 파일이 있으면 ready');
ok(ready.seeds[0].who && ready.seeds[0].who.batch === '260623' && ready.seeds[0].who.side === '전' && ready.seeds[0].who.partial === true, '씨앗에 묶음·전후·눈 가림이 manifest 에서 붙는다');
ok(!('person' in ready.seeds[0].who) && !JSON.stringify(ready).includes('정인좌'), '실명은 클라우드 목록에 싣지 않는다(얼굴 옆에 이름이 붙으면 안 된다)');
ok(!ready.seeds[1].who, '원본 경로가 없는 씨앗엔 안 붙는다(억지로 안 맞춘다)');
ok(ready.raw && !ready.raw.by_src, '목록엔 사람별 표(by_src)를 안 싣는다 — 크기만 키운다');

const rawOnly = bankEntry('nasolabial', banks.nasolabial, { manifest });
ok(rawOnly.status === 'raw' && rawOnly.counts.raw === 3 && rawOnly.seeds.length === 0, '판정 파일이 없고 manifest 만 있으면 raw(정제 전)');
const empty = bankEntry('lifting', { name_ko: '리프팅' }, {});
ok(empty.status === 'empty' && empty.seeds.length === 0, '아무것도 없으면 empty — 던지지 않는다');

// ── 업로드본(강남언니 실제 게시분) ─────────────────────────────────────────
const ups = readUploads();
ok(ups.gangnamunni && ups.gangnamunni.name_ko === '강남언니 업로드본' && /drive\.google\.com/.test(ups.gangnamunni.drive), 'uploads.gangnamunni 가 드라이브 폴더를 가리킨다');
ok(ups.gangnamunni.product_map['팔자온볼라썸'] === 'nasolabial' && ups.gangnamunni.product_map['턱선 3종 패키지'] === 'lifting', 'product_map: 상품(띄어쓰기 포함) → 시술 키');
const sec = readSection('a:\n  x: 1\nuploads:\n  g:\n    name_ko: 이름  # 주석\n    map:\n      팔자 패키지: nasolabial\n      필러: nasolabial\n    raw: C:/r\nb: 2\n', 'uploads');
ok(sec.g.name_ko === '이름' && sec.g.map['팔자 패키지'] === 'nasolabial' && sec.g.raw === 'C:/r' && !sec.b, '들여쓰기 세 단·주석·다음 최상위 키 처리');

const umf = {
  pulled_at: '2026-09-16T15:00:00+09:00',
  rows: [
    { 번호: '1', 상품: '팔자온볼라썸', 상태: '게시중', 제목: '콜라겐 팔자', 시술: '팔자주름필러|콜라겐주사', 성별: '여', 연령: '30대초', '파일(전)': '001_a_전.jpg', '파일(후)': '001_a_후_D+0.jpg', 경과일: '0' },
    { 번호: '2', 상품: '기타', 상태: '중단', 제목: '', 시술: '', 성별: '', 연령: '', '파일(전)': '', '파일(후)': '', 경과일: '' },
    { 번호: '3', 상품: '반영구(아트메이크)', 상태: '중단', 제목: '눈썹', 시술: '눈썹반영구', 성별: '', 연령: '', '파일(전)': '003_b_전.jpg', '파일(후)': '003_b_후_D+14.jpg', 경과일: '14' },
    { 번호: '4', 상품: '팔자온볼라썸', 상태: '게시중', 제목: '콜라겐 팔자2', 시술: '팔자주름필러', 성별: '', 연령: '', '파일(전)': '004_c_전.jpg', '파일(후)': '004_c_후_D+7.jpg', 경과일: '7' },
  ],
  files: [
    { file: '팔자온볼라썸/001_a_전.jpg' }, { file: '팔자온볼라썸/001_a_후_D+0.jpg' },
    { file: '반영구(아트메이크)/003_b_전.jpg' }, { file: '반영구(아트메이크)/003_b_후_D+14.jpg' },
    { file: '팔자온볼라썸/004_c_전.jpg' },   // 후는 못 받았다
  ],
};
const ue = uploadsEntry('gangnamunni', ups.gangnamunni, umf);
ok(ue.status === 'ready' && ue.counts.cases === 3 && ue.counts.files === 5 && ue.counts.live === 2 && ue.counts.stopped === 1, '사진 없는 줄은 빼고 케이스·장수·게시중/중단을 센다');
ok(ue.products[0].product === '팔자온볼라썸' && ue.products[0].treatment === 'nasolabial' && ue.products[0].cases.length === 2, '상품은 케이스 많은 순, product_map 으로 시술 키가 붙는다');
ok(ue.products[1].treatment === null, '대응 없는 상품은 treatment null(화면의 기타 칩)');
const c4 = ue.products[0].cases.find((c) => c.no === '4');
ok(c4.before === '004_c_전.jpg' && c4.after === null && c4.days === 7, '못 받은 사진은 null — 있는 척 안 한다. 경과일은 숫자');
ok(ue.products[0].cases[0].tags.length === 2 && ue.products[0].cases[0].gender === '여', '시술 태그·성별·연령이 실린다');
ok(uploadsEntry('gangnamunni', ups.gangnamunni, null).status === 'empty', 'manifest 없으면 empty — 던지지 않는다');

console.log(fails.length ? `\n실패 ${fails.length}건` : '\n전부 통과');
process.exit(fails.length ? 1 : 0);
