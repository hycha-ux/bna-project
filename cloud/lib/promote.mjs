/**
 * 규칙 승격 요청 저장소 (2026-09-10 성연서님 "규칙으로 승격을 하고 싶은데 막혀 있어서").
 *
 * 승격은 `config/prompts/avoid.yaml` 을 고치는 일이라 사무실 PC 에서만 실제로 된다.
 * 검수 판정과 같은 길을 쓴다 — 여기(Blob)에 요청을 적어 두면 PC 의 push-cloud 가 회차마다
 * 가져가 로컬 API(/api/lessons/promote)로 넣고, 넣은 것만 지운다.
 *
 *   promotions/<시각>-<난수>.json   ← { note, en, where, by, at }
 *
 * 화면은 대기 중인 요청을 "승격 대기" 로 보여 주고, 같은 메모는 목록에서 뺀다(두 번 올리지 않게).
 */
import { del, get, list, put } from '@vercel/blob';

export const PREFIX = 'promotions/';
const TTL_MS = 5_000;
let CACHE = { at: 0, arr: null };

export function newId(now = new Date()) {
  return now.toISOString().replace(/[-:TZ.]/g, '').slice(0, 14) + '-' + Math.random().toString(36).slice(2, 6);
}

export async function save(token, { note, en, where }, by) {
  const req = { id: newId(), note: String(note || '').slice(0, 300), en: String(en || '').trim().slice(0, 400),
    where: Array.isArray(where) && where.length ? where : ['before', 'after'], by: by || null, at: Date.now() / 1000, from: 'cloud' };
  if (!req.en) throw new Error('영어 문장이 비어 있습니다');
  await put(`${PREFIX}${req.id}.json`, JSON.stringify(req), {
    access: 'private', token, contentType: 'application/json; charset=utf-8', addRandomSuffix: false, allowOverwrite: true, cacheControlMaxAge: 0,
  });
  CACHE = { at: 0, arr: null };
  return req;
}

export async function readOne(token, pathname) {
  try {
    const r = await get(pathname, { access: 'private', token });
    if (!r || r.statusCode !== 200 || !r.stream) return null;
    const chunks = []; for await (const c of r.stream) chunks.push(Buffer.from(c));
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch { return null; }
}

/** 대기 중인 요청 전부 (오래된 순). 각 항목에 blob url·pathname 을 붙여 지울 수 있게. */
export async function pending(token) {
  const now = Date.now();
  if (CACHE.arr && now - CACHE.at < TTL_MS) return CACHE.arr;
  const arr = [];
  try {
    let cursor;
    do {
      const page = await list({ token, prefix: PREFIX, cursor, limit: 1000 });
      for (const b of page.blobs) { const r = await readOne(token, b.pathname); if (r) arr.push({ ...r, _url: b.url, _path: b.pathname }); }
      cursor = page.hasMore ? page.cursor : null;
    } while (cursor);
  } catch { /* 못 읽으면 빈 목록 — 화면은 그냥 승격 버튼을 보인다 */ }
  arr.sort((a, b) => (a.at || 0) - (b.at || 0));
  CACHE = { at: now, arr };
  return arr;
}

export async function remove(token, url) { try { await del(url, { token }); } catch { /* 다음 회차가 다시 본다 */ } CACHE = { at: 0, arr: null }; }
