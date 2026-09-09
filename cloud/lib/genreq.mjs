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
  return { ok: { treatment: b.treatment, mode: b.mode, count, target_pass: target, cost_cap: cap, seed, fixed, simulate: !!b.simulate } };
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

export async function create(token, body, user, treatments) {
  const v = validate(body, treatments);
  if (v.error) return { error: v.error };
  const req = {
    id: newId(), status: 'requested', ...v.ok,
    requested_by: user?.email || user?.name || 'unknown', requested_at: new Date().toISOString(),
  };
  await put(blobName(req.id), JSON.stringify(req), { access: 'private', token, addRandomSuffix: false, contentType: 'application/json' });
  return { ok: req };
}

export async function load(token, id) {
  try {
    const r = await get(blobName(id), { access: 'private', token });
    if (!r) return null;
    return JSON.parse(await new Response(r.stream).text());
  } catch { return null; }
}

export async function cancel(token, id) {
  const req = await load(token, id);
  if (!req) return { error: '요청을 찾을 수 없습니다' };
  if (!canTransition(req.status, 'cancelled')) return { error: `${STATUS_KO[req.status] || req.status} 상태라 취소할 수 없습니다 — 생성 PC 가 이미 받았습니다` };
  const next = { ...req, status: 'cancelled', cancelled_at: new Date().toISOString() };
  await put(blobName(id), JSON.stringify(next), { access: 'private', token, addRandomSuffix: false, contentType: 'application/json' });
  return { ok: next };
}

/** 최근 것부터. 오래된 done/cancelled 는 keep 개까지만(화면이 무한히 길어지지 않게). */
export async function listAll(token, { keep = 50 } = {}) {
  const out = [];
  let cursor;
  do {
    const page = await list({ token, prefix: PREFIX, cursor, limit: 1000 });
    for (const b of page.blobs) {
      try {
        const r = await get(b.pathname, { access: 'private', token });
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
