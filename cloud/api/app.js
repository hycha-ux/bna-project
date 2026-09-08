/**
 * B&A 대시보드 클라우드 배포본 — 보기 전용(read-only).
 *
 * 구조: 사무실 PC의 로컬 API(src/bna/api.py)가 원장이다. `push-cloud.mjs` 가 그 응답을
 *       그대로 긁어 Blob(`snapshot.json` + `files/**`)에 올리고, 이 함수는 그걸 읽어
 *       같은 모양으로 돌려준다. 집계 로직을 여기서 다시 짜지 않는다(정본 하나 규칙).
 *
 * 잠금: 생성 이미지가 사람 얼굴이라 게이트가 유일한 방어다.
 *       DASH_PW 가 없으면 503 으로 닫는다(fail-closed). 열어 두느니 안 뜨는 게 낫다.
 *
 * 쓰기(생성·큐·검수·내보내기)는 전부 405 다 — 돈 쓰는 버튼을 공개 URL에 두지 않는다.
 */
import crypto from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { get } from '@vercel/blob';

const PW = process.env.DASH_PW || '';
const TOKEN = process.env.BLOB_READ_WRITE_TOKEN || '';
const COOKIE = 'bna_auth';
const MAX_AGE = 60 * 60 * 24 * 14;
const MIME = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.json': 'application/json; charset=utf-8',
};

const authValue = () =>
  crypto.createHmac('sha256', PW).update('bna-dashboard-v1').digest('hex').slice(0, 32);

const readCookie = (req, name) => {
  const raw = req.headers.cookie || '';
  for (const part of raw.split(';')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    if (part.slice(0, i).trim() === name) return decodeURIComponent(part.slice(i + 1).trim());
  }
  return null;
};

const authed = (req) => {
  if (!PW) return false;
  const v = readCookie(req, COOKIE);
  if (!v) return false;
  const want = authValue();
  const a = Buffer.from(v);
  const b = Buffer.from(want);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
};

const json = (res, code, body) => {
  res.statusCode = code;
  res.setHeader('content-type', 'application/json; charset=utf-8');
  res.setHeader('cache-control', 'no-store');
  res.end(JSON.stringify(body));
};

const html = (res, code, body) => {
  res.statusCode = code;
  res.setHeader('content-type', 'text/html; charset=utf-8');
  res.setHeader('cache-control', 'no-store');
  res.end(body);
};

// ── 스냅샷 캐시 (같은 인스턴스가 연속 요청을 받을 때 Blob 왕복을 줄인다) ───────────
let CACHE = { at: 0, snap: null };
const TTL_MS = 15_000;

async function blobBytes(pathname) {
  const r = await get(pathname, { access: 'private', token: TOKEN });
  if (!r || r.statusCode !== 200 || !r.stream) return null;
  const chunks = [];
  for await (const c of r.stream) chunks.push(Buffer.from(c));
  return { buf: Buffer.concat(chunks), contentType: r.contentType };
}

async function snapshot() {
  const now = Date.now();
  if (CACHE.snap && now - CACHE.at < TTL_MS) return CACHE.snap;
  const got = await blobBytes('snapshot.json');
  if (!got) return null;
  const snap = JSON.parse(got.buf.toString('utf8'));
  CACHE = { at: now, snap };
  return snap;
}

// ── 화면 ────────────────────────────────────────────────────────────────────────
const LOGIN_PAGE = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>B&amp;A 이미지</title>
<style>
body{margin:0;height:100vh;display:grid;place-items:center;background:#F4F5F7;
 font-family:-apple-system,'Segoe UI',sans-serif;color:#191F28}
form{background:#fff;padding:32px;border-radius:16px;border:1px solid #EAECEF;width:300px;
 box-shadow:0 1px 3px rgba(0,0,0,.04)}
h1{font-size:17px;margin:0 0 4px} p{font-size:13px;color:#6B7684;margin:0 0 20px}
input{width:100%;padding:11px 12px;border:1px solid #EAECEF;border-radius:8px;font-size:14px;
 box-sizing:border-box}
button{width:100%;margin-top:10px;padding:11px;border:0;border-radius:8px;background:#1F3A5F;
 color:#fff;font-size:14px;font-weight:600;cursor:pointer}
.err{color:#D64545;font-size:13px;margin-top:10px;min-height:18px}
</style></head><body>
<form method="POST" action="/api/login">
<h1>B&amp;A 이미지</h1><p>온리프 · 전후 사진 자동 생성</p>
<input type="password" name="pw" placeholder="비밀번호" autofocus required>
<button type="submit">들어가기</button>
<div class="err">__ERR__</div>
</form></body></html>`;

const CLOSED_PAGE = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>준비 중</title><style>body{margin:0;height:100vh;display:grid;place-items:center;
font-family:-apple-system,'Segoe UI',sans-serif;background:#F4F5F7;color:#6B7684;font-size:14px;
text-align:center;line-height:1.7}</style></head><body><div>
<b style="color:#191F28">잠금이 설정되지 않아 닫아 두었습니다.</b><br>
생성 이미지가 사람 얼굴이라 비밀번호 없이는 열지 않습니다.<br>
관리자: 환경변수 <code>DASH_PW</code> 를 설정한 뒤 다시 배포하세요.
</div></body></html>`;

let INDEX_HTML = null;
function indexHtml(snap) {
  if (INDEX_HTML == null) {
    const tries = [
      path.join(process.cwd(), 'web', 'index.html'),
      new URL('../web/index.html', import.meta.url).pathname,
    ];
    for (const p of tries) {
      try {
        INDEX_HTML = readFileSync(p, 'utf8');
        break;
      } catch {
        /* 다음 후보 */
      }
    }
    if (INDEX_HTML == null) INDEX_HTML = '';
  }
  if (!INDEX_HTML) return '<h1>index.html 을 찾지 못했습니다</h1>';
  // 스냅샷이 언제 것인지 화면에 남긴다 — 낡은 값을 실시간으로 오해하면 그게 사고다.
  const at = snap?.generated_at || null;
  const banner = `<div id="snapnote" style="position:fixed;left:50%;bottom:14px;transform:translateX(-50%);
z-index:9999;background:rgba(25,31,40,.88);color:#fff;font-size:12px;padding:7px 14px;border-radius:999px;
box-shadow:0 2px 8px rgba(0,0,0,.18)">${
    at ? `보기 전용 · 사무실 PC 기준 ${at} 스냅샷` : '보기 전용 · 아직 데이터가 올라오지 않았습니다'
  }</div>`;
  return INDEX_HTML.replace('</body>', `${banner}</body>`);
}

// ── 라우팅 ──────────────────────────────────────────────────────────────────────
const WRITE_MSG =
  '이 화면은 보기 전용입니다. 생성·검수·내보내기는 사무실 PC에서 진행합니다.';

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}

export default async function handler(req, res) {
  const url = new URL(req.url, 'http://x');
  const p = url.pathname;

  if (!PW || !TOKEN) return html(res, 503, CLOSED_PAGE);

  // 로그인
  if (p === '/api/login' && req.method === 'POST') {
    const body = await readBody(req);
    let pw = '';
    try {
      pw = JSON.parse(body).pw || '';
    } catch {
      pw = new URLSearchParams(body).get('pw') || '';
    }
    if (pw !== PW) {
      return html(res, 401, LOGIN_PAGE.replace('__ERR__', '비밀번호가 다릅니다'));
    }
    res.setHeader(
      'set-cookie',
      `${COOKIE}=${authValue()}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${MAX_AGE}`,
    );
    res.statusCode = 302;
    res.setHeader('location', '/');
    return res.end();
  }

  if (!authed(req)) {
    if (p.startsWith('/api/') || p.startsWith('/files/')) {
      return json(res, 401, { error: '로그인이 필요합니다. 새로고침해 주세요.' });
    }
    return html(res, 401, LOGIN_PAGE.replace('__ERR__', ''));
  }

  // 쓰기 계열 — 공개 URL에 돈 쓰는 버튼을 두지 않는다
  if (req.method !== 'GET') return json(res, 405, { error: WRITE_MSG });

  const snap = await snapshot();

  if (p === '/' || p === '/index.html') return html(res, 200, indexHtml(snap));

  if (p.startsWith('/files/')) {
    const got = await blobBytes('files/' + p.slice('/files/'.length));
    if (!got) {
      res.statusCode = 404;
      return res.end('not found');
    }
    res.statusCode = 200;
    // Blob 이 octet-stream 으로 돌려주면 브라우저가 사진을 내려받기로 취급할 수 있다.
    // 확장자로 바로잡는다(업로드 쪽만 고치면 이미 올라간 파일은 그대로 남는다).
    res.setHeader('content-type', MIME[path.extname(p).toLowerCase()] || got.contentType || 'application/octet-stream');
    res.setHeader('cache-control', 'private, max-age=300');
    return res.end(got.buf);
  }

  if (!p.startsWith('/api/')) {
    res.statusCode = 404;
    return res.end('not found');
  }

  if (!snap) {
    return json(res, 503, {
      error: '아직 사무실 PC에서 데이터가 올라오지 않았습니다 (push-cloud 미실행).',
    });
  }

  if (p === '/api/config') return json(res, 200, snap.config);
  if (p === '/api/batches') return json(res, 200, snap.batches);
  if (p === '/api/queue') return json(res, 200, snap.queue);
  if (p === '/api/library') return json(res, 200, snap.library);

  if (p === '/api/overview') {
    const want = String(url.searchParams.get('days') || '14');
    const ov = snap.overview || {};
    if (ov[want]) return json(res, 200, ov[want]);
    // 창 길이가 스냅샷에 없으면 가장 가까운 것으로 — 빈 화면보다 낫고, 배너가 축을 밝힌다
    const keys = Object.keys(ov);
    if (!keys.length) return json(res, 503, { error: '집계가 아직 없습니다.' });
    const near = keys.reduce((a, b) =>
      Math.abs(+b - +want) < Math.abs(+a - +want) ? b : a,
    );
    return json(res, 200, ov[near]);
  }

  const mProg = /^\/api\/batches\/([^/]+)\/progress$/.exec(p);
  if (mProg) {
    const v = (snap.progress || {})[mProg[1]];
    return v ? json(res, 200, v) : json(res, 404, { error: '없는 배치입니다.' });
  }

  const mItem = /^\/api\/batches\/([^/]+)$/.exec(p);
  if (mItem) {
    const v = (snap.items || {})[mItem[1]];
    return v ? json(res, 200, v) : json(res, 404, { error: '없는 배치입니다.' });
  }

  return json(res, 404, { error: '없는 경로입니다: ' + p });
}
