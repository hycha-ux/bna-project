/**
 * 클라우드 검수 오버레이 회귀 (2026-09-08).
 *   node cloud/review-tests.mjs
 *
 * 네트워크는 안 부른다 — 겹치기·충돌 판정은 순수 함수라 여기서 전부 잡힌다.
 */
import {
  PREFIX, applyToBatch, applyToLibrary, applyToList, blobName, keyOf, newer, parseBlobName, recount,
} from './lib/reviews.mjs';

const fails = [];
const ok = (cond, label) => {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + label);
  if (!cond) fails.push(label);
};

// ── 이름 왕복 ──────────────────────────────────────────────────────────────
const n = blobName('20260908-101134-640d', '0000');
ok(n === `${PREFIX}20260908-101134-640d__0000.json`, '판정 파일 이름은 배치__아이템 이다');
const back = parseBlobName(n);
ok(back && back.batch === '20260908-101134-640d' && back.item === '0000', '이름에서 배치·아이템을 되찾는다');
ok(parseBlobName('files/a/b.jpg') === null, '사진 파일은 판정으로 오인하지 않는다');

// ── 충돌: 더 새 것이 이긴다 (양쪽 다 사람이 누른 값이다) ────────────────────
ok(newer({pick: 'pick', updated_at: 100}, {pick: 'reject', updated_at: 200}).pick === 'reject',
   '클라우드가 더 나중이면 클라우드가 이긴다');
ok(newer({pick: 'pick', updated_at: 300}, {pick: 'reject', updated_at: 200}).pick === 'pick',
   'PC 에서 더 나중에 고쳤으면 클라우드 옛 값이 못 덮는다');
ok(newer({pick: 'pick', updated_at: 100}, null).pick === 'pick', '클라우드에 없으면 스냅샷 그대로');
ok(newer(undefined, {pick: 'reject', updated_at: 5}).pick === 'reject', '스냅샷에 판정이 없으면 클라우드 값');
ok(newer({}, {pick: 'reject', updated_at: 5}).pick === 'reject', '빈 판정({})은 시각이 없으니 클라우드가 이긴다');

// ── 배치 상세: 카드와 통계가 같이 움직여야 한다 ─────────────────────────────
const batch = {
  batch_id: 'b1',
  stats: {total: 3, reviewed: 0, picked: 0, rejected: 0},
  items: [
    {item_id: '0000', review: {}},
    {item_id: '0001', review: {pick: 'pick', updated_at: 10}},
    {item_id: '0002', review: {}},
  ],
};
const ov = {
  'b1/0000': {pick: 'reject', tags: ['손가락'], note: '', updated_at: 99},
  'b1/0001': {pick: 'reject', tags: [], note: '', updated_at: 5},   // 스냅샷(10)이 더 새것
};
const merged = applyToBatch(batch, ov);
ok(merged.items[0].review.pick === 'reject', '클라우드 판정이 카드에 겹쳐진다');
ok(merged.items[1].review.pick === 'pick', '더 오래된 클라우드 판정은 카드를 못 바꾼다');
ok(merged.stats.picked === 1 && merged.stats.rejected === 1 && merged.stats.reviewed === 2,
   `통계도 같이 다시 센다 — 실제 채택 ${merged.stats.picked}·제외 ${merged.stats.rejected}·검수 ${merged.stats.reviewed}`);
ok(merged.stats.review_tags['손가락'] === 1, '제외 사유 집계도 겹쳐진다');
ok(batch.items[0].review.pick === undefined, '원본 스냅샷을 제자리에서 고치지 않는다(캐시 오염 방지)');

// ── 목록 표: 아이템별 원본이 있을 때만 다시 센다 ────────────────────────────
const list1 = applyToList([{batch_id: 'b1', stats: {total: 3, picked: 9, rejected: 9}}], ov, {b1: batch});
ok(list1[0].stats.picked === 1 && list1[0].stats.rejected === 1, '목록 표의 채택·제외 수도 겹쳐진다');
const list2 = applyToList([{batch_id: 'zz', stats: {picked: 7}}], ov, {b1: batch});
ok(list2[0].stats.picked === 7, '아이템별 원본이 없는 배치는 옛 수를 그대로 둔다(틀린 수를 만들지 않는다)');

// ── 라이브러리: 채택하면 들어오고 제외하면 빠진다 ───────────────────────────
const lib = {items: [{batch_id: 'b1', item_id: '0001', treatment: 'nasolabial', mode: 'selfie',
                      review: {pick: 'pick', updated_at: 10}, picked_at: 10}], summary: {}, total: 1};
const snapItems = {b1: {items: [
  {item_id: '0000', treatment: 'nasolabial', mode: 'selfie', before_file: 'a.jpg', after_file: 'b.jpg'},
  {item_id: '0001', treatment: 'nasolabial', mode: 'selfie', before_file: 'c.jpg', after_file: 'd.jpg'},
]}};
const lib2 = applyToLibrary(lib, {'b1/0000': {pick: 'pick', updated_at: 50}}, snapItems);
ok(lib2.total === 2 && lib2.items.some((i) => i.item_id === '0000'),
   `클라우드에서 채택한 사진이 라이브러리에 들어온다 — 실제 ${lib2.total}장`);
ok(lib2.items[0].item_id === '0000', '최근에 채택한 것이 위로 온다');
const lib3 = applyToLibrary(lib, {'b1/0001': {pick: 'reject', updated_at: 50}}, snapItems);
ok(lib3.total === 0, '클라우드에서 제외로 바꾸면 라이브러리에서 빠진다');
const lib4 = applyToLibrary(lib, {'b1/0002': {pick: 'pick', updated_at: 50}}, snapItems);
ok(lib4.total === 1, '스냅샷에 없는 사진은 라이브러리에 만들어 넣지 않는다');

// ── 세는 규칙: 사유·메모만 있어도 '검수함'이다 ──────────────────────────────
const c = recount({}, [{pick: null, tags: ['각도'], note: ''}, {pick: null, tags: [], note: '메모'}, {}]);
ok(c.reviewed === 2 && c.picked === 0 && c.rejected === 0,
   `판정 없이 사유·메모만 있어도 검수한 것으로 센다 — 실제 ${c.reviewed}`);

console.log();
console.log(fails.length ? `실패 ${fails.length}건` : '전부 통과');
process.exit(fails.length ? 1 : 0);
