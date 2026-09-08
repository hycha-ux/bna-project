/**
 * 로그인·직급 판정 정본 — 이 파일 하나다.
 *
 * 화면(app.js)·관리자 API·회귀(auth-tests.mjs)가 전부 여기를 부른다.
 * 판정을 호출부에 복붙하면 화면과 서버가 조용히 갈린다.
 *
 * 원장: private Blob `auth/users.json`. git 에 두지 않는다(계정·해시가 들어간다).
 *
 * ⚠ 메일 소유 확인(인증메일)은 하지 않는다 — 보낼 수단이 없다.
 *   대신 ①메디빌더 도메인 ②가입코드 두 겹으로 막는다. 구글 로그인으로 올리면
 *   이 두 겹을 걷어내도 된다(그때는 도메인 판정만 남는다).
 */
import crypto from 'node:crypto';
import { get, put } from '@vercel/blob';

export const DOMAIN = '@medibuilder.com';
export const USERS_KEY = 'auth/users.json';
export const ROLES = ['admin', 'member'];
export const ROLE_LABEL = { admin: '관리자', member: '구성원' };

/** 이 메일로 가입하면 관리자로 시작한다(2026-09-08 성연서님 지시). */
export const SEED_ADMINS = ['hy.cha@medibuilder.com', 'ys.seong@medibuilder.com'];

export const normEmail = (s) => String(s || '').trim().toLowerCase();

/** 도메인 판정 — 대소문자·앞뒤 공백만 흡수하고 넓히지 마라. */
export function emailAllowed(email) {
  const e = normEmail(email);
  if (!e.endsWith(DOMAIN)) return false;
  const local = e.slice(0, -DOMAIN.length);
  return /^[a-z0-9._%+-]+$/.test(local);
}

export const isSeedAdmin = (email) => SEED_ADMINS.includes(normEmail(email));

// ── 비밀번호 ────────────────────────────────────────────────────────────────
export function hashPw(pw, salt = crypto.randomBytes(16).toString('hex')) {
  const hash = crypto.scryptSync(String(pw), salt, 32).toString('hex');
  return { salt, hash };
}

export function pwOk(pw, user) {
  if (!user || !user.salt || !user.hash) return false;
  const got = crypto.scryptSync(String(pw), user.salt, 32).toString('hex');
  const a = Buffer.from(got);
  const b = Buffer.from(user.hash);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

/** 너무 짧은 비밀번호는 받지 않는다. 메일 인증이 없어 이 줄이 마지막 방어다. */
export function pwProblem(pw) {
  const s = String(pw || '');
  if (s.length < 8) return '비밀번호는 8자 이상이어야 합니다.';
  if (/^\d+$/.test(s)) return '숫자만으로는 안 됩니다.';
  return null;
}

// ── 세션 쿠키 ───────────────────────────────────────────────────────────────
export const COOKIE = 'bna_s';
export const SESSION_MS = 14 * 24 * 60 * 60 * 1000;

const b64u = (buf) => Buffer.from(buf).toString('base64url');

export function signSession(email, secret, now = Date.now()) {
  const body = b64u(JSON.stringify({ e: normEmail(email), t: now }));
  const sig = crypto.createHmac('sha256', secret).update(body).digest('base64url');
  return `${body}.${sig}`;
}

/** 서명·만료만 본다. 차단·삭제 여부는 원장을 읽는 쪽(currentUser)이 판정한다. */
export function readSession(value, secret, now = Date.now()) {
  if (!value || !secret) return null;
  const i = value.lastIndexOf('.');
  if (i < 0) return null;
  const body = value.slice(0, i);
  const sig = value.slice(i + 1);
  const want = crypto.createHmac('sha256', secret).update(body).digest('base64url');
  const a = Buffer.from(sig);
  const b = Buffer.from(want);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  let payload;
  try {
    payload = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
  } catch {
    return null;
  }
  if (!payload || !payload.e || !payload.t) return null;
  if (now - payload.t > SESSION_MS) return null;
  return { email: payload.e, issued: payload.t };
}

// ── 원장 ────────────────────────────────────────────────────────────────────
export const emptyStore = () => ({ version: 1, users: {} });

export async function loadUsers(token) {
  const r = await get(USERS_KEY, { access: 'private', token, useCache: false });
  if (!r || r.statusCode !== 200 || !r.stream) return emptyStore();
  const chunks = [];
  for await (const c of r.stream) chunks.push(Buffer.from(c));
  try {
    const j = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    return j && j.users ? j : emptyStore();
  } catch {
    // 깨진 원장을 빈 것으로 덮으면 전원이 로그아웃되고 관리자도 사라진다.
    throw new Error('회원 원장을 읽지 못했습니다. 덮어쓰지 않고 멈춥니다.');
  }
}

export async function saveUsers(store, token) {
  await put(USERS_KEY, JSON.stringify(store), {
    access: 'private',
    token,
    addRandomSuffix: false,
    allowOverwrite: true,
    contentType: 'application/json',
  });
}

export const adminCount = (store) =>
  Object.values(store.users || {}).filter((u) => u.role === 'admin' && !u.blocked).length;

/**
 * 직급·차단을 바꿀 수 있는지. 마지막 관리자를 잃으면 아무도 이 화면을 못 고친다
 * → 마지막 한 명은 강등·차단·삭제 전부 막는다(fail-closed).
 */
export function guardChange(store, email, next) {
  const e = normEmail(email);
  const u = (store.users || {})[e];
  if (!u) return '없는 계정입니다.';
  const losesAdmin =
    u.role === 'admin' &&
    !u.blocked &&
    (next.role === 'member' || next.blocked === true || next.deleted === true);
  if (losesAdmin && adminCount(store) <= 1)
    return '마지막 관리자는 바꿀 수 없습니다. 다른 관리자를 먼저 세우세요.';
  if (next.role && !ROLES.includes(next.role)) return '없는 직급입니다.';
  return null;
}

export function publicUser(u) {
  return {
    email: u.email,
    role: u.role,
    role_label: ROLE_LABEL[u.role] || u.role,
    blocked: !!u.blocked,
    created_at: u.created_at,
    last_login: u.last_login || null,
  };
}
