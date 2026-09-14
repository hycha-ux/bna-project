// 생성 요청 대기열 순수 함수 회귀 — 네트워크 0. `node cloud/genreq-tests.mjs`
import { validate, canTransition, sortRequests, newId, blobName, PREFIX } from './lib/genreq.mjs';

const fails = [];
const ok = (c, label) => { console.log((c ? 'PASS  ' : 'FAIL  ') + label); if (!c) fails.push(label); };
const T = { nasolabial: {}, filler_nose: {} };

ok(validate({ treatment: 'nasolabial', mode: 'selfie', count: 8 }, T).ok?.count === 8, '정상 요청은 통과');
ok(validate({ treatment: 'nope', mode: 'selfie', count: 8 }, T).error, '없는 시술은 막는다');
ok(validate({ treatment: 'nasolabial', mode: 'x', count: 8 }, T).error, '모르는 사진 종류는 막는다');
ok(validate({ treatment: 'nasolabial', mode: 'selfie', count: 0 }, T).error, '0장은 막는다');
ok(validate({ treatment: 'nasolabial', mode: 'selfie', count: 8, target_pass: 9 }, T).error, '목표가 장수보다 크면 막는다');
ok(validate({ treatment: 'nasolabial', mode: 'selfie', count: 8, fixed: { gender: 'female', age: '' } }, T).ok.fixed.gender === 'female'
   && !('age' in validate({ treatment: 'nasolabial', mode: 'selfie', count: 8, fixed: { gender: 'female', age: '' } }, T).ok.fixed), '빈 고정값은 버린다');

ok(validate({ treatment: 'nasolabial', mode: 'selfie', count: 8, series: ['2w', 'immediate', 'x'] }, T).ok.series.join(',') === 'immediate,2w', '시리즈 시점은 시간순·아는 값만');
ok(validate({ treatment: 'nasolabial', mode: 'selfie', count: 8 }, T).ok.series === null, '시리즈 없으면 null(전·후 2장)');
ok(canTransition('requested', 'accepted') && canTransition('requested', 'cancelled'), '요청됨 → 받음/취소');
ok(!canTransition('accepted', 'cancelled') && !canTransition('running', 'cancelled'), '받은 뒤엔 화면에서 취소 못 한다');
ok(canTransition('running', 'done') && canTransition('running', 'error') && !canTransition('done', 'running'), '완료 뒤로는 못 돌아간다');
ok(canTransition('error', 'done') && canTransition('error', 'running') && !canTransition('error', 'accepted') && !canTransition('done', 'error'), '실패는 복구(생성 중·완료)로만 되돌아간다 — PC 재시작 뒤 같은 요청을 다시 돌린 경우');

const s = sortRequests([{ status: 'done', requested_at: '2' }, { status: 'requested', requested_at: '1' }, { status: 'running', requested_at: '0' }]);
ok(s.map((x) => x.status).join(',') === 'requested,running,done', '안 끝난 것이 위(그 안에선 최신 먼저) → 끝난 것');
const s2 = sortRequests([{ status: 'error', requested_at: '1' }, { status: 'done', requested_at: '3' }, { status: 'error', requested_at: '2' }, { status: 'done', requested_at: '0' }]);
ok(s2.map((x) => x.requested_at).join(',') === '3,2,1,0', '끝난 것은 실패·완료 구분 없이 시간 역순 한 줄 (2026-09-14 성연서님 "상태순으로 나와서 이상함")');
ok(blobName(newId()).startsWith(PREFIX) && /\d{8}-\d{6}-[a-z0-9]{4}\.json$/.test(blobName(newId())), '파일 이름은 gen-requests/날짜-시각-난수.json');

console.log(fails.length ? `실패 ${fails.length}건` : '전부 통과');
process.exit(fails.length ? 1 : 0);
