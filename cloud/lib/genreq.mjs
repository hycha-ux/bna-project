/**
 * 생성 요청 대기열 — 인터넷 화면에서 "만들어 달라"를 적어 두면 생성 PC 가 가져가 돌린다.
 *
 * 왜: 사진을 만드는 코드·키·랜드마크 모듈은 생성 PC(티모)에만 있고, 밖에서 그 PC 로 들어올 길이 없다.
 *     그래서 화면은 요청만 Blob 에 적고, 생성 PC 가 주기적으로 읽어 간다 (2026-09-09 성연서님 "생성하면 티모가 알아서 돌리는 구조").
 *
 * 한 요청 = Blob 하나 `gen-requests/<id>.json`. 상태는 한 방향으로만 간다:
 *   requested → accepted → running → done | error        (cancelled 는 requested 에서만)
 * 화면이 쓰는 건 requested·cancelled 뿐이고, accepted 부터는 생성 PC 가 같은 파일을 덮어쓴다.
 * 정본은 이 파일 하나 — 상태 전이 규칙을 다른 데서 다시 쓰지 마라. 회귀 = `node cloud/genreq-tests.mjs`.
 */
import { put, list, get, del } from '@vercel/blob';

export const PREFIX = 'gen-requests/';
export const STATUS = ['requested', 'accepted', 'running', 'done', 'error', 'cancelled'];
export const STATUS_KO = { requested: '요청됨', accepted: '생성 PC가 받음', running: '생성 중', done: '완료', error: '실패', cancelled: '취소' };

const MODES = ['selfie', 'clinical'];

/** 화면 폼 → 요청 한 건. 잘못된 입력은 여기서 걸러 에러 문장을 돌려준다(400 용). */
export function validate(body, treatments) {
  const b = body || {};
  if (!b.treatment || (treatments && !treatments[b.treatment])) return { error: '시술을 선택하세요' };
  if (!MODES.includes(b.mode)) return { error: '사진 종류(셀카형/임상형)를 선택하세요' };
  const count = Number(b.count);
  if (!Number.isInteger(count) || count < 1 || count > 200) return { error: '생성 장수는 1~200 사이여야 합니다' };
  const target = b.target_pass == null || b.target_pass === '' ? null : Number(b.target_pass);
  if (target != null && (!Number.isInteger(target) || target < 1 || target > count)) return { error: '목표 통과 장수는 1 이상, 생성 장수 이하여야 합니다' };
  const cap = b.cost_cap == null || b.cost_cap === '' ? null : Number(b.cost_cap);
  if (cap != null && !(cap > 0)) return { error: '비용 상한은 0보다 커야 합니다' };
  const seed = b.seed == null || b.seed === '' ? null : Number(b.seed);
  if (seed != null && !Number.isInteger(seed)) return { error: '시드는 정수여야 합니다' };
  const fixed = {};
  for (const [k, v] of Object.entries(b.fixed || {})) if (v) fixed[String(k)] = String(v);
  const TP = ['immediate', '1w', '2w', '4w'];
  const series = Array.isArray(b.series) ? TP.filter((w) => b.series.includes(w)) : null;   // 경과 시리즈 시점(시간순). 없으면 전·후 2장
  return { ok: { treatment: b.treatment, mode: b.mode, count, target_pass: target, cost_cap: cap, seed, fixed, simulate: !!b.simulate, series: series && series.length ? series : null } };
}

export function newId(now = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  const r = Math.random().toString(36).slice(2, 6);
  return `${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}-${r}`;
}

export const blobName = (id) => `${PREFIX}${id}.json`;

/** 전이 규칙: 화면은 requested→cancelled 만, 생성 PC 는 requested→accepted→running→done|error 만. */
export function canTransition(from, to) {
  const next = { requested: ['accepted', 'cancelled'], accepted: ['running', 'error'], running: ['done', 'error'] };
  return (next[from] || []).includes(to);
}

/**
 * 요청 한 건을 같은 경로에 덮어쓴다. 쓰기는 이 함수 하나로만 — put 옵션이 갈리면 파일이 둘 생긴다.
 * ⚠ `allowOverwrite` 를 빼면 **두 번째 쓰기가 통째로 실패한다**(Blob v2, 2026-09-09 실측):
 *   상태 전이가 곧 같은 이름 덮어쓰기라, 이게 없으면 취소도 진행 보고도 한 번도 성공하지 못한다.
 * ⚠ `cacheControlMaxAge: 0` 도 같은 이유로 필수다. 기본값은 캐시를 길게 잡아, 다 끝난 요청을
 *   한참 뒤에 읽어도 **옛 상태가 온다**(09-09 실측: 완료 50초 뒤 목록이 아직 '생성 중'이라
 *   폴러가 같은 요청을 또 닫았다). 이 파일은 사진이 아니라 상태라 캐시하면 안 된다.
 */
export async function save(token, req) {
  await put(blobName(req.id), JSON.stringify(req), {
    access: 'private', token, addRandomSuffix: false, allowOverwrite: true,
    contentType: 'application/json', cacheControlMaxAge: 0,
  });
  return req;
}

export async function create(token, body, user, treatments) {
  const v = validate(body, treatments);
  if (v.error) return { error: v.error };
  const req = {
    id: newId(), status: 'requested', ...v.ok,
    requested_by: user?.email || user?.name || 'unknown', requested_at: new Date().toISOString(),
  };
  await save(token, req);
  return { ok: req };
}

/**
 * ⚠ 읽기는 **캐시를 끈다**(`useCache: false`). 이 파일은 사진이 아니라 *상태*라, 캐시된 옛 값을
 * 받으면 이미 끝난 요청을 다시 돌리거나 화면이 '생성 중'에 얼어붙는다(09-09 실측: 완료 뒤 50초가
 * 지나도 목록이 옛 상태였다). 느려지는 건 작은 JSON 몇 개 읽기뿐이니 그 값이 훨씬 싸다.
 */
export async function load(token, id) {
  try {
    const r = await get(blobName(id), { access: 'private', token, useCache: false });
    if (!r) return null;
    return JSON.parse(await new Response(r.stream).text());
  } catch { return null; }
}

export async function cancel(token, id) {
  const req = await load(token, id);
  if (!req) return { error: '요청을 찾을 수 없습니다' };
  if (!canTransition(req.status, 'cancelled')) return { error: `${STATUS_KO[req.status] || req.status} 상태라 취소할 수 없습니다 — 생성 PC 가 이미 받았습니다` };
  const next = { ...req, status: 'cancelled', cancelled_at: new Date().toISOString() };
  await save(token, next);
  return { ok: next };
}

/**
 * 생성 PC 전용 — 상태 한 칸 전진(accepted→running→done|error).
 *
 * **쓰기 직전에 다시 읽는다**: 폴러가 목록을 만든 사이 화면에서 취소가 눌렸을 수 있다.
 * 전이 규칙에 어긋나면 쓰지 않고 사유를 돌려준다(취소된 요청을 돌리지 않는 장치가 이것 하나다).
 *
 * ⚠ 방금 내가 쓴 값을 곧바로 다시 읽으면 **옛 값이 온다**(Blob 읽기 캐시, 2026-09-09 실측
 *   1초 이내). 그래서 한 회차 안에서 두 칸을 연달아 옮길 때는 앞 칸의 결과를 `known` 으로
 *   넘겨라 — 다시 읽지 않는다. 남이 바꿨을 수 있는 첫 칸에서만 읽는 게 맞다.
 */
export async function advance(token, id, to, patch = {}, known = null) {
  const req = known || await load(token, id);
  if (!req) return { error: '요청을 찾을 수 없습니다' };
  if (!canTransition(req.status, to)) return { error: `${STATUS_KO[req.status] || req.status} → ${STATUS_KO[to] || to} 전이는 허용되지 않습니다` };
  return { ok: await save(token, { ...req, ...patch, status: to }) };
}

/** 상태는 그대로 두고 곁 정보만 갱신(로컬 작업 번호·진행률). 전이가 아니므로 규칙 검사가 없다. */
export async function annotate(token, id, fields) {
  const req = await load(token, id);
  if (!req) return { error: '요청을 찾을 수 없습니다' };
  return { ok: await save(token, { ...req, ...fields, status: req.status }) };
}

/** 최근 것부터. 오래된 done/cancelled 는 keep 개까지만(화면이 무한히 길어지지 않게). */
export async function listAll(token, { keep = 50 } = {}) {
  const out = [];
  let cursor;
  do {
    const page = await list({ token, prefix: PREFIX, cursor, limit: 1000 });
    for (const b of page.blobs) {
      try {
        const r = await get(b.pathname, { access: 'private', token, useCache: false });
        if (r) out.push(JSON.parse(await new Response(r.stream).text()));
      } catch { /* 깨진 한 건이 목록을 죽이지 않는다 */ }
    }
    cursor = page.hasMore ? page.cursor : undefined;
  } while (cursor);
  return sortRequests(out).slice(0, keep);
}

export function sortRequests(arr) {
  const rank = { running: 0, accepted: 1, requested: 2, error: 3, done: 4, cancelled: 5 };
  return [...arr].sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) || String(b.requested_at).localeCompare(String(a.requested_at)));
}

export async function remove(token, id) {
  await del(blobName(id), { token });
}
