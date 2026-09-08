/**
 * 로그인·직급 판정 회귀 — `node cloud/auth-tests.mjs`
 * 네트워크·Blob 없이 순수 판정만 본다(원장 입출력은 라이브 확인 몫).
 */
import {
  SESSION_MS,
  emailAllowed,
  guardChange,
  hashPw,
  isSeedAdmin,
  normEmail,
  pwOk,
  pwProblem,
  publicUser,
  readSession,
  signSession,
} from './lib/auth.mjs';

let pass = 0;
const fails = [];
const ok = (name, cond) => (cond ? pass++ : fails.push(name));

// ── 도메인 판정 ─────────────────────────────────────────────────────────────
ok('회사 메일 허용', emailAllowed('ys.seong@medibuilder.com'));
ok('대문자 흡수', emailAllowed('YS.Seong@MediBuilder.com'));
ok('앞뒤 공백 흡수', emailAllowed('  hy.cha@medibuilder.com  '));
ok('외부 메일 거부', !emailAllowed('someone@gmail.com'));
ok('비슷한 도메인 거부', !emailAllowed('a@medibuilder.co.kr'));
ok('접미 위장 거부', !emailAllowed('a@evil-medibuilder.com'));
ok('서브도메인 위장 거부', !emailAllowed('a@medibuilder.com.evil.com'));
ok('로컬파트 없음 거부', !emailAllowed('@medibuilder.com'));
ok('빈 값 거부', !emailAllowed('') && !emailAllowed(null));
ok('공백 낀 로컬파트 거부', !emailAllowed('a b@medibuilder.com'));
ok('정규화', normEmail('  A@B.COM ') === 'a@b.com');

// ── 시드 관리자 ─────────────────────────────────────────────────────────────
ok('파트장 시드 관리자', isSeedAdmin('hy.cha@medibuilder.com'));
ok('성연서 시드 관리자', isSeedAdmin('YS.SEONG@medibuilder.com'));
ok('그 외는 시드 아님', !isSeedAdmin('someone@medibuilder.com'));

// ── 비밀번호 ────────────────────────────────────────────────────────────────
const u = { ...hashPw('correct-horse') };
ok('맞는 비번 통과', pwOk('correct-horse', u));
ok('틀린 비번 거부', !pwOk('correct-horse ', u));
ok('빈 비번 거부', !pwOk('', u));
ok('해시 없는 계정 거부', !pwOk('x', { salt: 'a' }));
ok('같은 비번도 소금이 달라 해시가 다르다', hashPw('same').hash !== hashPw('same').hash);
ok('짧은 비번 반려', pwProblem('short') !== null);
ok('8자 영숫자 통과', pwProblem('abcd1234') === null);
ok('숫자만 반려', pwProblem('12345678') !== null);
ok('정상 비번 통과', pwProblem('teemo1234') === null);

// ── 세션 ────────────────────────────────────────────────────────────────────
const S = 'secret-for-test';
const now = Date.now();
const tok = signSession('ys.seong@medibuilder.com', S, now);
ok('서명 검증', readSession(tok, S, now)?.email === 'ys.seong@medibuilder.com');
ok('다른 비밀키 거부', readSession(tok, 'other', now) === null);
ok('변조 거부', readSession(tok.slice(0, -2) + 'xx', S, now) === null);
ok('본문 변조 거부', readSession('eyJlIjoiYUBiIn0.' + tok.split('.')[1], S, now) === null);
ok('만료 거부', readSession(tok, S, now + SESSION_MS + 1) === null);
ok('만료 직전 통과', readSession(tok, S, now + SESSION_MS - 1000) !== null);
ok('빈 쿠키 거부', readSession('', S, now) === null);
ok('점 없는 쿠키 거부', readSession('abc', S, now) === null);
ok('비밀키 없으면 거부', readSession(tok, '', now) === null);

// ── 마지막 관리자 보호 ──────────────────────────────────────────────────────
const store1 = {
  users: {
    'a@medibuilder.com': { email: 'a@medibuilder.com', role: 'admin', blocked: false },
    'b@medibuilder.com': { email: 'b@medibuilder.com', role: 'member', blocked: false },
  },
};
ok('마지막 관리자 강등 차단', guardChange(store1, 'a@medibuilder.com', { role: 'member' }) !== null);
ok('마지막 관리자 차단 차단', guardChange(store1, 'a@medibuilder.com', { blocked: true }) !== null);
ok('마지막 관리자 삭제 차단', guardChange(store1, 'a@medibuilder.com', { deleted: true }) !== null);
ok('구성원 차단은 허용', guardChange(store1, 'b@medibuilder.com', { blocked: true }) === null);
ok('구성원 승격은 허용', guardChange(store1, 'b@medibuilder.com', { role: 'admin' }) === null);
ok('없는 계정 반려', guardChange(store1, 'zzz@medibuilder.com', { role: 'admin' }) !== null);
ok('없는 직급 반려', guardChange(store1, 'b@medibuilder.com', { role: 'boss' }) !== null);

const store2 = {
  users: {
    'a@medibuilder.com': { email: 'a@medibuilder.com', role: 'admin', blocked: false },
    'c@medibuilder.com': { email: 'c@medibuilder.com', role: 'admin', blocked: false },
  },
};
ok('관리자 둘이면 강등 허용', guardChange(store2, 'a@medibuilder.com', { role: 'member' }) === null);

const store3 = {
  users: {
    'a@medibuilder.com': { email: 'a@medibuilder.com', role: 'admin', blocked: false },
    'c@medibuilder.com': { email: 'c@medibuilder.com', role: 'admin', blocked: true },
  },
};
ok('차단된 관리자는 머릿수에 안 든다', guardChange(store3, 'a@medibuilder.com', { role: 'member' }) !== null);

// ── 밖으로 내보내는 모양 ────────────────────────────────────────────────────
const pub = publicUser({
  email: 'a@medibuilder.com',
  role: 'admin',
  salt: 'S',
  hash: 'H',
  created_at: 'x',
});
ok('해시·소금은 내보내지 않는다', !('hash' in pub) && !('salt' in pub));
ok('직급 한글 라벨', pub.role_label === '관리자');

console.log(`auth-tests: ${pass}종 통과${fails.length ? ` · ${fails.length}종 실패` : ''}`);
if (fails.length) {
  for (const f of fails) console.error('  실패:', f);
  process.exit(1);
}
