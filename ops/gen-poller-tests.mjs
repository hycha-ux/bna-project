// 생성 요청 폴러 순수 함수 회귀 — 네트워크 0·생성 0. `node ops/gen-poller-tests.mjs`
// 여기서 보는 것은 "이번 회차에 무엇을 할지"(plan) 하나다. 돈이 나가는 판단이라 이중 등록·
// 취소 무시·유령 완료 같은 실패 모양을 시료로 박아 둔다.
import { plan, labelOf, jobSpec, resultOf, shortErr, restartBlockers } from './gen-poller.mjs';

const fails = [];
const ok = (c, label) => { console.log((c ? 'PASS  ' : 'FAIL  ') + label); if (!c) fails.push(label); };
const kinds = (acts) => acts.map((a) => a.kind).join(',');

const REQ = (over = {}) => ({ id: 'r1', status: 'requested', treatment: 'nasolabial', mode: 'selfie', count: 8, requested_at: '2026-09-09T01:00:00.000Z', ...over });
const JOB = (over = {}) => ({ job_id: 'j1', status: 'queued', batch_id: null, label: labelOf('r1'), result: null, error: null, ...over });

// ① 기본 흐름
ok(kinds(plan([REQ()], [])) === 'accept', '요청됨은 가져간다');
ok(kinds(plan([REQ({ status: 'cancelled' }), REQ({ id: 'r2', status: 'done' })], [])) === '', '취소·완료된 요청엔 손대지 않는다');
ok(kinds(plan([REQ({ status: 'accepted', local_job_id: 'j1' })], [JOB()])) === '', '큐에서 차례를 기다리는 동안엔 아무것도 안 한다');
ok(kinds(plan([REQ({ status: 'accepted', local_job_id: 'j1' })], [JOB({ status: 'running', batch_id: 'b1' })])) === 'running', '작업이 돌기 시작하면 생성 중으로 올린다');
ok(kinds(plan([REQ({ status: 'running', local_job_id: 'j1', batch_id: 'b1' })], [JOB({ status: 'done', batch_id: 'b1', result: { total: 8, passed: 4 } })])) === 'done', '끝나면 완료로 닫는다');
ok(kinds(plan([REQ({ status: 'running', local_job_id: 'j1' })], [JOB({ status: 'error', error: 'RuntimeError()' })])) === 'error', '작업이 터지면 실패로 닫는다');
ok(kinds(plan([REQ({ status: 'running', local_job_id: 'j1' })], [JOB({ status: 'cancelled' })])) === 'error', '이 PC에서 취소하면 요청도 닫는다');

// ② 이중 생성 방지 — 여기가 이 파일의 핵심이다(재시도가 곧 돈이다)
ok(kinds(plan([REQ({ status: 'accepted' })], [JOB()])) === 'adopt',
   '작업 번호를 못 적고 죽었어도, 라벨로 찾아 붙이지 새로 넣지 않는다');
ok(kinds(plan([REQ({ status: 'accepted' })], [])) === 'add', '넣은 적이 없으면(라벨도 없다) 다시 넣는다');
ok(kinds(plan([REQ({ status: 'accepted', local_job_id: 'j1' })], [])) === 'error',
   '넣었던 작업이 사라졌으면 다시 넣지 않고 실패로 닫는다');
ok(plan([REQ({ status: 'accepted' })], [JOB({ status: 'done', result: { total: 8, passed: 4 } })]).map((a) => a.kind).join(',') === 'adopt,done',
   '회차 사이에 다 돌아버린 짧은 배치도 붙이고 닫는다');

// ③ 순서·상한
const many = ['3', '1', '2'].map((n) => REQ({ id: 'r' + n, requested_at: `2026-09-09T0${n}:00:00.000Z` }));
ok(plan(many, []).map((a) => a.id).join(',') === 'r1,r2,r3', '먼저 온 요청부터 가져간다');
ok(plan(Array.from({ length: 30 }, (_, i) => REQ({ id: 'r' + i })), []).length === 10, '한 회차 상한은 10건');
ok(plan(Array.from({ length: 30 }, (_, i) => REQ({ id: 'r' + i })), [], { maxAccept: 2 }).length === 2, '상한은 인자로 조절된다');

// ④ 곁가지
ok(kinds(plan([REQ({ status: 'running', local_job_id: 'j1', batch_id: null })], [JOB({ status: 'running', batch_id: 'b9' })])) === 'note',
   '배치 번호가 늦게 오면 상태는 그대로 두고 번호만 적는다');
ok(kinds(plan([REQ({ status: 'running', local_job_id: 'j1', batch_id: 'b9' })], [JOB({ status: 'running', batch_id: 'b9' })])) === '',
   '바뀐 게 없으면 Blob 을 다시 쓰지 않는다');
ok(labelOf('abc') === 'genreq:abc' && jobSpec(REQ()).label === 'genreq:r1', '라벨은 genreq:<요청 id>');
const spec = jobSpec(REQ({ count: 8, target_pass: 4, fixed: { gender: 'female' }, simulate: true }));
ok(spec.count === 8 && spec.target_pass === 4 && spec.fixed.gender === 'female' && spec.simulate === true && !('gen' in spec),
   '큐 작업은 요청 필드 그대로 + 프로바이더는 안 보낸다(기본값)');
// 안 넘긴 칸은 오류 없이 기본값으로 떨어진다 — 조용히 다른 물건이 나오는 자리라 못 박아 둔다.
ok(jobSpec(REQ({ series: ['immediate', '2w'] })).series.join(',') === 'immediate,2w' && jobSpec(REQ()).series === null,
   '경과 시리즈 시점도 큐로 넘긴다(빠뜨리면 전·후 2장이 나온다)');
const PG = { planned: 4, items: { '0000': { passed: true, cost: 0.085 }, '0001': { passed: true, cost: 0.17 }, '0002': { passed: false, cost: 0.255 }, '0003': { passed: true, cost: 0.085 } } };
ok(resultOf({ total: 4, passed: 3 }, PG).cost === 0.595, '든 돈은 progress.json 항목 비용을 더해 낸다');
ok(resultOf(null, PG).total === 4 && resultOf(null, PG).passed === 3, 'stats 가 없어도 progress 로 장수를 낸다');
ok(resultOf({ total: 8, passed: 3 }, { summary: { cost: 1.25 }, items: {} }).cost === 1.25, '계산된 summary 가 있으면 그걸 쓴다');
ok(resultOf(null, null).total === null && resultOf(null, null).cost === null, '못 읽은 값은 0 이 아니라 null 이다');
const long = shortErr('a'.repeat(500));
ok(long.length <= 200 && long.endsWith('…') && shortErr(null) === '알 수 없는 오류', '긴 예외는 잘라 적는다');

// ⑤ 재시작(--restart-api) — 죽이면 그 자리에서 돈이 날아가는 자리라 막는 조건을 못 박는다.
ok(restartBlockers([JOB({ status: 'running' })]).length === 1 && restartBlockers([JOB({ status: 'queued' })]).length === 1,
   '큐에 돌거나 기다리는 작업이 있으면 재시작을 막는다');
ok(restartBlockers([JOB({ status: 'done' }), JOB({ status: 'error' }), JOB({ status: 'cancelled' })]).length === 0,
   '끝난 작업은 재시작을 막지 않는다');
ok(restartBlockers(null).length === 0 && restartBlockers([]).length === 0, '큐를 못 읽어도 터지지 않는다');

console.log(fails.length ? `실패 ${fails.length}건` : '전부 통과');
process.exit(fails.length ? 1 : 0);
