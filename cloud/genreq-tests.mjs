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

ok(canTransition('requested', 'accepted') && canTransition('requested', 'cancelled'), '요청됨 → 받음/취소');
ok(!canTransition('accepted', 'cancelled') && !canTransition('running', 'cancelled'), '받은 뒤엔 화면에서 취소 못 한다');
ok(canTransition('running', 'done') && canTransition('running', 'error') && !canTransition('done', 'running'), '완료 뒤로는 못 돌아간다');

const s = sortRequests([{ status: 'done', requested_at: '2' }, { status: 'requested', requested_at: '1' }, { status: 'running', requested_at: '0' }]);
ok(s.map((x) => x.status).join(',') === 'running,requested,done', '진행 중 → 요청됨 → 끝난 것 순');
ok(blobName(newId()).startsWith(PREFIX) && /\d{8}-\d{6}-[a-z0-9]{4}\.json$/.test(blobName(newId())), '파일 이름은 gen-requests/날짜-시각-난수.json');

console.log(fails.length ? `실패 ${fails.length}건` : '전부 통과');
process.exit(fails.length ? 1 : 0);
