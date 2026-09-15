// 진행 표시 실시간 반영 순수 함수 회귀 — 네트워크 0. `node cloud/liveprog-tests.mjs`
import { validId, liveName, lastActivity, pickProgress, mergeList, prunable, STALE_S, PREFIX } from './lib/liveprog.mjs';

const fails = [];
const ok = (c, label) => { console.log((c ? 'PASS  ' : 'FAIL  ') + label); if (!c) fails.push(label); };

const ID = '20260915-104807-dbf2';
ok(validId(ID) && validId('20260914-105916-sim'), '실제 배치 ID 형식은 통과');
ok(!validId('../snapshot') && !validId('20260915-104807-dbf2/../x') && !validId(''), '경로 조작·빈 값은 거부');
ok(liveName(ID) === `${PREFIX}${ID}.json`, '파일 이름은 progress/<배치>.json');
let threw = false; try { liveName('../x'); } catch { threw = true; }
ok(threw, '잘못된 ID 로 이름을 만들면 던진다');

const snap = { started_at: 1000, finished_at: null, summary: { running: true, done: 1, planned: 3 }, items: { '0000': { updated_at: 1100 } } };
ok(lastActivity(snap) === 1100, '스냅샷의 마지막 움직임 = 항목 updated_at 최대');
const live = { pushed_at: 1200, summary: { running: true, done: 2, planned: 3 }, items: { '0000': {} } };

const a = pickProgress(snap, live, 1230);
ok(a.live.used && a.summary.done === 2 && a.live.age_s === 30 && a.live.stale === false, '실시간이 더 새면 실시간 · 신호 30초 전 · 멈춤 아님');
const b = pickProgress(snap, { ...live, pushed_at: 1050 }, 1230);
ok(!b.live.used && b.summary.done === 1, '실시간이 스냅샷보다 낡았으면 스냅샷(끝난 뒤 늦게 도착한 옛 신호가 되돌리지 않게)');
const c = pickProgress(snap, live, 1200 + STALE_S + 1);
ok(c.live.stale === true, `진행 중인데 신호가 ${STALE_S}초 넘게 끊기면 멈춤 의심`);
const done = pickProgress(snap, { ...live, summary: { running: false, done: 3, planned: 3 } }, 1200 + 99999);
ok(done.live.stale === false, '끝난 배치는 오래돼도 멈춤이 아니다');
const noLive = pickProgress(snap, null, 99999);
ok(!noLive.live.used && noLive.live.age_s === null && noLive.live.stale === null, '실시간 파일이 없으면 모른다(null) — 멈춤이라고 단정하지 않는다');
ok(pickProgress(null, live, 1200).live.used, '스냅샷에 아직 없는 새 배치도 실시간으로 보인다');
ok(pickProgress(null, null, 1) === null, '둘 다 없으면 null');
ok(!pickProgress(snap, { pushed_at: 'x', summary: {}, items: {} }, 1).live.used, 'pushed_at 이 깨진 파일은 쓰지 않는다');

const list = mergeList([{ batch_id: ID, progress: { running: true, done: 1, planned: 3 } }, { batch_id: 'other', progress: { running: false } }], { [ID]: live }, 1230);
ok(list[0].progress.done === 2 && list[0].progress.live.used && list[1].progress.running === false, '목록의 진행 요약도 실시간으로 갈아 끼운다(없는 배치는 그대로)');

const pr = prunable([`${PREFIX}${ID}.json`, `${PREFIX}20260914-090217-afd6.json`, 'snapshot.json'],
  { [ID]: { summary: { running: true } }, '20260914-090217-afd6': { summary: { running: false } } });
ok(pr.length === 1 && pr[0].includes('afd6'), '지우는 건 스냅샷이 진행 중이라 하지 않는 배치의 실시간 파일뿐(다른 파일은 안 건드림)');

console.log(fails.length ? `실패 ${fails.length}건` : '전부 통과');
process.exit(fails.length ? 1 : 0);
