/**
 * 클라우드 검수 저장소 (2026-09-08 성연서님 "나는 지금 PC에서 진행하고 있거든!").
 *
 * 왜 열었나. 종전엔 클라우드가 **모든 쓰기**를 405 로 막았다. 그런데 막아야 할 이유가 있는 건
 * *생성*(유료 API·수 분)과 *내보내기*(디스크에 zip)뿐이다. **검수는 판정 한 줄 저장이라
 * 돈도 시간도 안 든다.** 같이 막아 놓으니, 사진을 만든 PC 앞이 아니면 아무도 검수를 못 했다
 * (실측: 성연서님이 보시던 화면에서 채택/제외가 통째로 잠겨 있었다).
 *
 * 어떻게. 스냅샷은 사무실 PC → 클라우드 **단방향**이라 여기에 쓸 수 없다. 그래서 검수만
 * 따로 Blob 에 둔다:
 *
 *   reviews/<배치>__<아이템>.json   ← 클라우드에서 누른 판정 (여기가 원장)
 *
 * 화면은 `스냅샷 + 이 오버레이`를 겹쳐 본다 → 누른 즉시 반영된다(10분 배치를 안 기다린다).
 * 사무실 PC 의 `push-cloud.mjs` 가 회차마다 이걸 내려받아 `outputs/<배치>/<아이템>/review.json`
 * 에 반영하고, 반영된 것만 지운다. 그때부터 드라이브 등록·프롬프트 학습이 이어진다.
 *
 * ⚠ 충돌은 `updated_at` 이 큰 쪽이 이긴다. PC 에서 방금 고친 걸 클라우드의 옛 판정이
 *   덮으면 안 되기 때문이다(양쪽 다 사람이 누른다).
 * ⚠ 이 파일은 **로그인 게이트 뒤에서만** 불린다. 무인증 공개가 아니다.
 */
import { del, list, put } from '@vercel/blob';
import { get } from '@vercel/blob';

export const PREFIX = 'reviews/';
const TTL_MS = 5_000;                       // 누른 직후 다시 읽으니 짧게 — 길면 방금 누른 게 안 보인다
let CACHE = { at: 0, map: null };

/** "<배치>/<아이템>" ↔ Blob 파일 이름. 배치·아이템 이름엔 `/` 가 없다(폴더명). */
export const keyOf = (batch, item) => `${batch}/${item}`;
export const blobName = (batch, item) => `${PREFIX}${batch}__${item}.json`;
export function parseBlobName(pathname) {
  const m = new RegExp(`^${PREFIX}(.+)__(.+)\\.json$`).exec(pathname);
  return m ? { batch: m[1], item: m[2], key: `${m[1]}/${m[2]}` } : null;
}

/** 아이템 하나의 판정을 Blob 에 쓴다. 값은 화면이 준 것 그대로 + 저장 시각. */
export async function saveReview(token, { batch, item, pick, tags, note }) {
  const rv = {
    pick: pick ?? null,
    tags: Array.isArray(tags) ? tags : [],
    note: typeof note === 'string' ? note : '',
    updated_at: Date.now() / 1000,
    from: 'cloud',                          // 어디서 눌렀는지 — PC 흡수 로그가 이걸 쓴다
  };
  await put(blobName(batch, item), JSON.stringify(rv), {
    access: 'private', token, contentType: 'application/json; charset=utf-8',
    addRandomSuffix: false, allowOverwrite: true, cacheControlMaxAge: 0,
  });
  CACHE = { at: 0, map: null };             // 방금 쓴 걸 바로 보이게 캐시를 버린다
  return rv;
}

/**
 * 판정 한 건 읽기. **이 저장소는 private 이라 `b.url` 을 그냥 fetch 하면 `Forbidden` 이다.**
 * 읽는 자리가 둘(화면 오버레이·사무실 PC 흡수)이라 여기 한 곳에 둔다 —
 * 2026-09-10 실사고: 흡수 쪽이 제 손으로 `fetch(b.url)` 을 짜서 30건이 통째로 안 들어왔고,
 * 그 실패가 한 건짜리 catch 에 삼켜져 **오류 없이 0건**으로 나왔다.
 * 못 읽으면 null 을 준다(던지지 않는다) — 부르는 쪽이 세어서 소리를 낸다.
 */
export async function readOne(token, pathname) {
  try {
    const r = await get(pathname, { access: 'private', token });
    if (!r || r.statusCode !== 200 || !r.stream) return null;
    const chunks = [];
    for await (const c of r.stream) chunks.push(Buffer.from(c));
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return null;
  }
}

/** 클라우드에 쌓인 판정 전부. { "<배치>/<아이템>": review } */
export async function overlay(token) {
  const now = Date.now();
  if (CACHE.map && now - CACHE.at < TTL_MS) return CACHE.map;
  const map = {};
  try {
    let cursor;
    do {
      const page = await list({ token, prefix: PREFIX, cursor, limit: 1000 });
      for (const b of page.blobs) {
        const id = parseBlobName(b.pathname);
        if (!id) continue;
        const rv = await readOne(token, b.pathname);   // 깨진 한 건이 전체를 죽이지 않는다
        if (rv) map[id.key] = rv;
      }
      cursor = page.hasMore ? page.cursor : null;
    } while (cursor);
  } catch {
    return CACHE.map || {};                 // 오버레이를 못 읽으면 스냅샷만 보여 준다(fail-open)
  }
  CACHE = { at: now, map };
  return map;
}

/** 스냅샷의 판정과 오버레이 중 **더 새 것**을 고른다. 양쪽 다 사람이 누른 값이다. */
export function newer(fromSnapshot, fromCloud) {
  if (!fromCloud) return fromSnapshot || {};
  if (!fromSnapshot || !fromSnapshot.updated_at) return fromCloud;
  return (fromCloud.updated_at || 0) >= (fromSnapshot.updated_at || 0) ? fromCloud : fromSnapshot;
}

// ── 화면이 보는 값에 오버레이를 겹친다 (여기 한 곳에서만 겹친다) ─────────────
const isReviewed = (r) => !!(r && (r.pick || (r.tags || []).length || r.note));

/** 배치 상세(items 포함)에 겹치고, 통계도 다시 센다 — 화면 표와 카드가 갈리지 않게. */
export function applyToBatch(batch, map) {
  if (!batch || !Array.isArray(batch.items)) return batch;
  const items = batch.items.map((it) => {
    const rv = newer(it.review, map[keyOf(batch.batch_id, it.item_id)]);
    return { ...it, review: rv };
  });
  return { ...batch, items, stats: recount(batch.stats, items.map((i) => i.review || {})) };
}

/**
 * 목록의 stats(채택·제외 수)에도 겹친다 — 표만 옛 숫자로 남으면 "안 먹었다"로 읽힌다.
 * 스냅샷의 `items[배치].items[].review` 가 아이템별 원본이라 그걸 겹쳐 다시 센다.
 * 원본이 없는 배치는 건드리지 않는다 — 틀린 수를 만드느니 옛 수가 낫다.
 */
export function applyToList(batches, map, snapItems) {
  if (!Array.isArray(batches)) return batches;
  return batches.map((b) => {
    const src = snapItems?.[b.batch_id]?.items;
    if (!Array.isArray(src)) return b;
    const reviews = src.map((it) => newer(it.review, map[keyOf(b.batch_id, it.item_id)]));
    return { ...b, stats: recount(b.stats, reviews) };
  });
}

export function recount(stats, reviews) {
  const s = { ...(stats || {}) };
  s.reviewed = reviews.filter(isReviewed).length;
  s.picked = reviews.filter((r) => r && r.pick === 'pick').length;
  s.rejected = reviews.filter((r) => r && r.pick === 'reject').length;
  s.review_tags = {};
  for (const r of reviews) for (const t of (r && r.tags) || []) s.review_tags[t] = (s.review_tags[t] || 0) + 1;
  return s;
}

/** 라이브러리(채택본)도 겹친다 — 채택했는데 라이브러리에 안 뜨면 저장이 안 된 걸로 읽힌다. */
export function applyToLibrary(lib, map, itemsByBatch) {
  if (!lib || !Array.isArray(lib.items)) return lib;
  const kept = lib.items.filter((i) => {
    const rv = map[keyOf(i.batch_id, i.item_id)];
    return !rv || rv.pick === 'pick';         // 클라우드에서 제외로 바뀐 건 뺀다
  }).map((i) => {
    const rv = map[keyOf(i.batch_id, i.item_id)];
    return rv ? { ...i, review: newer(i.review, rv) } : i;
  });
  const have = new Set(kept.map((i) => keyOf(i.batch_id, i.item_id)));
  // 클라우드에서 새로 채택한 것 추가 (사진 경로는 배치 상세에서 가져온다)
  for (const [key, rv] of Object.entries(map)) {
    if (rv.pick !== 'pick' || have.has(key)) continue;
    const [batch, item] = key.split('/');
    const src = (itemsByBatch?.[batch]?.items || []).find((x) => x.item_id === item);
    if (!src) continue;
    kept.push({
      batch_id: batch, item_id: item, treatment: src.treatment, mode: src.mode,
      variation: src.variation || {}, review: rv, passed: src.passed, demo: !!src.demo,
      before_file: src.before_file, after_file: src.after_file, picked_at: rv.updated_at,
    });
  }
  kept.sort((a, b) => (b.picked_at || 0) - (a.picked_at || 0));
  const summary = {};
  for (const i of kept) {
    summary[i.treatment] = summary[i.treatment] || {};
    summary[i.treatment][i.mode] = (summary[i.treatment][i.mode] || 0) + 1;
  }
  return { items: kept, summary, total: kept.length };
}
