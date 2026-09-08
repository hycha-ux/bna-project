/**
 * B&A 대시보드 클라우드 배포본 — 보기 전용(read-only) + 계정 로그인.
 *
 * 구조: 사무실 PC의 로컬 API(src/bna/api.py)가 원장이다. `push-cloud.mjs` 가 그 응답을
 *       그대로 긁어 Blob(`snapshot.json` + `files/**`)에 올리고, 이 함수는 그걸 읽어
 *       같은 모양으로 돌려준다. 집계 로직을 여기서 다시 짜지 않는다(정본 하나 규칙).
 *
 * 잠금(2026-09-08 성연서님 지시로 공용 비번 → 개인 계정으로 교체):
 *   - 메디빌더 메일만 회원가입, 직급 2단계(관리자/구성원), 관리자만 `/admin`.
 *   - 판정 정본은 `lib/auth.mjs` 하나다 — 여기서 이메일·직급 규칙을 다시 쓰지 마라.
 *   - AUTH_SECRET 이 없으면 503 으로 닫는다(fail-closed). 생성 이미지가 사람 얼굴이라
 *     열어 두느니 안 뜨는 게 낫다.
 *
 * 쓰기(생성·큐·검수·내보내기)는 전부 405 다 — 돈 쓰는 버튼을 공개 URL에 두지 않는다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { get } from '@vercel/blob';
import {
  COOKIE,
  ROLE_LABEL,
  SESSION_MS,
  emailAllowed,
  guardChange,
  hashPw,
  isSeedAdmin,
  loadUsers,
  normEmail,
  publicUser,
  pwOk,
  pwProblem,
  readSession,
  saveUsers,
  signSession,
} from '../lib/auth.mjs';

const TOKEN = process.env.BLOB_READ_WRITE_TOKEN || '';
const SECRET = process.env.AUTH_SECRET || '';
// 가입코드는 별도 값이 원칙이고, 없으면 옮겨오기 전 공용 비번을 그대로 쓴다.
const SIGNUP_CODE = process.env.SIGNUP_CODE || process.env.DASH_PW || '';

const MIME = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.json': 'application/json; charset=utf-8',
};

const readCookie = (req, name) => {
  const raw = req.headers.cookie || '';
  for (const part of raw.split(';')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    if (part.slice(0, i).trim() === name) return decodeURIComponent(part.slice(i + 1).trim());
  }
  return null;
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

const setSession = (res, email) => {
  res.setHeader(
    'set-cookie',
    `${COOKIE}=${signSession(email, SECRET)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${
      SESSION_MS / 1000
    }`,
  );
};

// ── 스냅샷 캐시 ─────────────────────────────────────────────────────────────
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

/** 쿠키 → 실제 계정. 차단·삭제는 원장에서 즉시 반영된다(쿠키만 믿지 않는다). */
async function currentUser(req) {
  const s = readSession(readCookie(req, COOKIE), SECRET);
  if (!s) return null;
  const store = await loadUsers(TOKEN);
  const u = store.users[s.email];
  if (!u || u.blocked) return null;
  return u;
}

// ── 공용 화면 조각 ──────────────────────────────────────────────────────────
const esc = (s) =>
  String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const SHELL_CSS = `
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:#F4F5F7;color:#191F28;
 font-family:'Pretendard',-apple-system,'Segoe UI',sans-serif;font-size:14px;line-height:1.5}
.wrap{min-height:100vh;display:grid;place-items:center;padding:24px}
.card{background:#fff;padding:32px;border-radius:16px;border:1px solid #EAECEF;width:320px;
 box-shadow:0 1px 3px rgba(0,0,0,.04)}
h1{font-size:17px;margin:0 0 4px}
.sub{font-size:13px;color:#6B7684;margin:0 0 20px}
label{display:block;font-size:12px;color:#6B7684;margin:12px 0 5px}
input,select{width:100%;padding:10px 12px;border:1px solid #EAECEF;border-radius:8px;font-size:14px;
 font-family:inherit;background:#fff}
button.pri{width:100%;margin-top:16px;padding:11px;border:0;border-radius:8px;background:#1F3A5F;
 color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button.pri:disabled{opacity:.5;cursor:default}
.msg{font-size:13px;margin-top:12px;min-height:18px;color:#D64545;white-space:pre-line}
.msg.ok{color:#1F8F55}
.alt{margin-top:16px;font-size:13px;color:#6B7684;text-align:center}
a{color:#1F3A5F}
`;

const authPage = ({ title, sub, fields, button, script, alt }) => `<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>${SHELL_CSS}</style></head><body><div class="wrap"><div class="card">
<h1>${esc(title)}</h1><p class="sub">${esc(sub)}</p>
${fields}
<button class="pri" id="go">${esc(button)}</button>
<div class="msg" id="msg"></div>
${alt ? `<div class="alt">${alt}</div>` : ''}
</div></div><script>${script}</script></body></html>`;

const POST_JS = (url, keys, done) => `
const $=id=>document.getElementById(id);
const send=async()=>{
  const b={};${keys.map((k) => `b['${k}']=$('${k}').value;`).join('')}
  $('go').disabled=true;$('msg').className='msg';$('msg').textContent='';
  try{
    const r=await fetch('${url}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
    const j=await r.json();
    if(!r.ok){$('msg').textContent=j.error||('오류 '+r.status);$('go').disabled=false;return;}
    ${done}
  }catch(e){$('msg').textContent='연결에 실패했습니다.';$('go').disabled=false;}
};
$('go').onclick=send;
document.querySelectorAll('input').forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')send();}));
`;

const LOGIN_PAGE = authPage({
  title: 'B&A 이미지',
  sub: '온리프 · 전후 사진 자동 생성',
  fields: `<label for="email">메디빌더 메일</label>
<input id="email" type="email" placeholder="name@medibuilder.com" autofocus autocomplete="username">
<label for="pw">비밀번호</label>
<input id="pw" type="password" autocomplete="current-password">`,
  button: '로그인',
  script: POST_JS('/api/auth/login', ['email', 'pw'], "location.href='/';"),
  alt: '계정이 없으시면 <a href="/signup">회원가입</a>',
});

const SIGNUP_PAGE = authPage({
  title: '회원가입',
  sub: '메디빌더 메일(@medibuilder.com)만 가입할 수 있습니다',
  fields: `<label for="email">메디빌더 메일</label>
<input id="email" type="email" placeholder="name@medibuilder.com" autofocus autocomplete="username">
<label for="code">가입코드</label>
<input id="code" type="password" placeholder="담당자에게 받은 코드">
<label for="pw">비밀번호 (8자 이상)</label>
<input id="pw" type="password" autocomplete="new-password">
<label for="pw2">비밀번호 확인</label>
<input id="pw2" type="password" autocomplete="new-password">`,
  button: '가입하고 들어가기',
  script: POST_JS('/api/auth/signup', ['email', 'code', 'pw', 'pw2'], "location.href='/';"),
  alt: '이미 계정이 있으시면 <a href="/login">로그인</a>',
});

const closedPage = (why) => `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>준비 중</title><style>${SHELL_CSS}</style></head><body><div class="wrap"><div class="card">
<h1>닫아 두었습니다</h1>
<p class="sub">생성 이미지가 사람 얼굴이라, 잠금이 갖춰지지 않으면 열지 않습니다.</p>
<div class="msg">${esc(why)}</div></div></div></body></html>`;

// ── 관리자 화면 ─────────────────────────────────────────────────────────────
const ADMIN_PAGE = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>관리자 설정</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>${SHELL_CSS}
.wrap{display:block;place-items:unset;max-width:900px;margin:0 auto;padding:32px 24px}
.card{width:auto}
.top{display:flex;align-items:baseline;gap:12px;margin-bottom:20px}
.top h1{margin:0}.top .sub{margin:0}
.top a{margin-left:auto;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:600;color:#6B7684;font-size:12px;padding:8px 10px;border-bottom:1px solid #EAECEF}
td{padding:9px 10px;border-bottom:1px solid #F4F5F7;vertical-align:middle}
tr.me td{background:#F7F8FA}
select{width:auto;padding:5px 8px;font-size:13px}
.btn{padding:5px 10px;border:1px solid #EAECEF;background:#fff;border-radius:7px;font-size:12px;
 cursor:pointer;font-family:inherit}
.btn.danger{color:#D64545;border-color:#FBE5E5}
.tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600}
.tag.admin{background:rgba(31,58,95,.08);color:#1F3A5F}
.tag.member{background:#F4F5F7;color:#6B7684}
.tag.blocked{background:#FBE5E5;color:#D64545}
.note{font-size:12px;color:#8B95A1;margin-top:16px;line-height:1.7}
</style></head><body><div class="wrap">
<div class="top"><h1>관리자 설정</h1><p class="sub">구성원 · 관리자</p><a href="/">← 대시보드</a></div>
<div class="card">
<table><thead><tr><th>메일</th><th>직급</th><th>상태</th><th>가입</th><th>최근 접속</th><th></th></tr></thead>
<tbody id="rows"><tr><td colspan="6" style="color:#8B95A1">불러오는 중…</td></tr></tbody></table>
<div class="msg" id="msg"></div>
<div class="note">
· 직급을 바꾸면 바로 반영됩니다(그 사람이 다음 요청을 보낼 때부터).<br>
· <b>차단</b>은 로그인만 막습니다. <b>삭제</b>는 계정을 지웁니다 — 같은 메일로 다시 가입할 수 있습니다.<br>
· 마지막 관리자는 강등·차단·삭제할 수 없습니다. 먼저 다른 관리자를 세우세요.<br>
· 메일 인증 수단이 없어 <b>주소의 본인 확인은 못 합니다</b> — 가입코드가 그 자리를 대신합니다. 모르는 계정이 보이면 차단하세요.
</div></div></div>
<script>
const $=id=>document.getElementById(id);
let ME='';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=s=>s?new Date(s).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
async function load(){
  const r=await fetch('/api/admin/users');const j=await r.json();
  if(!r.ok){$('msg').textContent=j.error||'불러오지 못했습니다';return;}
  ME=j.me;
  $('rows').innerHTML=j.users.map(u=>{
    const me=u.email===ME;
    return '<tr class="'+(me?'me':'')+'"><td>'+esc(u.email)+(me?' <span class="tag member">나</span>':'')+'</td>'
     +'<td><select data-e="'+esc(u.email)+'" class="role">'
     +'<option value="admin"'+(u.role==='admin'?' selected':'')+'>관리자</option>'
     +'<option value="member"'+(u.role==='member'?' selected':'')+'>구성원</option></select></td>'
     +'<td>'+(u.blocked?'<span class="tag blocked">차단됨</span>':'<span class="tag '+u.role+'">정상</span>')+'</td>'
     +'<td>'+fmt(u.created_at)+'</td><td>'+fmt(u.last_login)+'</td>'
     +'<td style="text-align:right;white-space:nowrap">'
     +'<button class="btn blk" data-e="'+esc(u.email)+'" data-v="'+(u.blocked?'0':'1')+'">'+(u.blocked?'차단 해제':'차단')+'</button> '
     +'<button class="btn danger del" data-e="'+esc(u.email)+'">삭제</button></td></tr>';
  }).join('')||'<tr><td colspan="6" style="color:#8B95A1">아직 가입한 사람이 없습니다</td></tr>';
  document.querySelectorAll('.role').forEach(s=>s.onchange=()=>save({email:s.dataset.e,role:s.value}));
  document.querySelectorAll('.blk').forEach(b=>b.onclick=()=>save({email:b.dataset.e,blocked:b.dataset.v==='1'}));
  document.querySelectorAll('.del').forEach(b=>b.onclick=()=>{
    if(confirm(b.dataset.e+' 계정을 삭제할까요? 되돌릴 수 없습니다.')) save({email:b.dataset.e,delete:true});
  });
}
async function save(body){
  $('msg').className='msg';$('msg').textContent='';
  const r=await fetch('/api/admin/user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(!r.ok){$('msg').textContent=j.error||'바꾸지 못했습니다';}
  else{$('msg').className='msg ok';$('msg').textContent='반영했습니다.';}
  load();
}
load();
</script></body></html>`;

const FORBIDDEN_PAGE = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>권한 없음</title><style>${SHELL_CSS}</style></head><body><div class="wrap"><div class="card">
<h1>관리자만 볼 수 있습니다</h1>
<p class="sub">이 페이지는 직급이 <b>관리자</b>인 계정만 열 수 있습니다.</p>
<div class="alt"><a href="/">← 대시보드로</a></div></div></div></body></html>`;

// ── 대시보드 HTML ───────────────────────────────────────────────────────────
let INDEX_HTML = null;
function indexHtml(snap, user) {
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
  const at = snap?.generated_at || null;

  // ① 스냅샷 시각은 화면에 남긴다 — 낡은 값을 실시간으로 오해하면 그게 사고다.
  //    (계정·관리자·로그아웃은 2026-09-08 성연서님 지시로 프로필 메뉴로 옮겼다.)
  const banner = `<div id="snapnote" style="position:fixed;left:50%;bottom:14px;transform:translateX(-50%);
z-index:9999;background:rgba(25,31,40,.82);color:#fff;font-size:12px;padding:6px 13px;border-radius:999px;
box-shadow:0 2px 8px rgba(0,0,0,.16)">${
    at ? `보기 전용 · 사무실 PC 기준 ${esc(at)} 스냅샷` : '보기 전용 · 아직 데이터가 올라오지 않았습니다'
  }</div>`;

  // ② 계정·관리자·로그아웃은 우측 상단 프로필(▾) 메뉴 안으로.
  //    빌디의 index.html 을 고치지 않고 여기서 얹는다(그쪽이 다시 구워도 안 지워진다).
  //    ⚠ 메뉴 마크업(#tb-profile·#menu)이 사라지면 조용히 아무 데도 안 뜬다 →
  //    못 찾으면 우측 상단에 대체 알약을 띄운다(fail-open, 로그아웃 길을 잃지 않게).
  const me = JSON.stringify({
    email: user.email,
    role: user.role,
    label: ROLE_LABEL[user.role] || user.role,
  });
  const profileJs = `<script>(function(){
var U=${me};
var local=U.email.split('@')[0];
var esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
 return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});};
var prof=document.getElementById('tb-profile'), menu=document.getElementById('menu');
if(prof&&menu){
  menu.style.width='250px'; // 기본 200px 에선 회사 메일이 두 줄로 깨진다
  var av=prof.querySelector('.avatar'); if(av) av.textContent=local.slice(0,2).toUpperCase();
  var sp=prof.querySelectorAll('span'); if(sp[1]) sp[1].textContent=local;
  prof.title=U.email;
  var head=document.createElement('div');
  head.style.cssText='padding:10px 12px 9px;margin:-2px 0 4px;border-bottom:1px solid var(--ui-border)';
  head.innerHTML='<div style="font-size:13px;font-weight:600;line-height:1.3">'+esc(local)+'</div>'
    +'<div style="font-size:12px;color:var(--ui-md);word-break:break-all">'+esc(U.email)+'</div>'
    +'<div style="margin-top:6px"><span style="display:inline-block;padding:2px 8px;border-radius:999px;'
    +'font-size:11px;font-weight:600;background:'+(U.role==='admin'?'var(--pri-alpha);color:var(--primary)':'var(--ui-surface);color:var(--ui-md)')
    +'">'+esc(U.label)+'</span></div>';
  menu.insertBefore(head,menu.firstChild);
  var sep=document.createElement('div'); sep.className='mi-sep'; menu.appendChild(sep);
  if(U.role==='admin'){
    var a=document.createElement('button');
    a.innerHTML='<svg width="18" height="18"><use href="#i-gear"/></svg>관리자 설정';
    a.onclick=function(){location.href='/admin';};
    menu.appendChild(a);
  }
  var out=document.createElement('button');
  out.innerHTML='<svg width="18" height="18"><use href="#i-user"/></svg>로그아웃';
  out.onclick=function(){location.href='/api/auth/logout';};
  menu.appendChild(out);
}else{
  var f=document.createElement('div');
  f.style.cssText='position:fixed;right:16px;top:14px;z-index:9999;background:#fff;border:1px solid #EAECEF;'
    +'border-radius:999px;padding:6px 12px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.08)';
  f.innerHTML=esc(U.email)+' · '+(U.role==='admin'?'<a href="/admin">관리자 설정</a> · ':'')
    +'<a href="/api/auth/logout">로그아웃</a>';
  document.body.appendChild(f);
}
})();</script>`;

  return INDEX_HTML.replace('</body>', `${banner}${profileJs}</body>`);
}

// ── 라우팅 ──────────────────────────────────────────────────────────────────
const WRITE_MSG = '이 화면은 보기 전용입니다. 생성·검수·내보내기는 사무실 PC에서 진행합니다.';

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks).toString('utf8');
  try {
    return JSON.parse(raw || '{}');
  } catch {
    return Object.fromEntries(new URLSearchParams(raw));
  }
}

export default async function handler(req, res) {
  const url = new URL(req.url, 'http://x');
  const p = url.pathname;

  if (!SECRET) return html(res, 503, closedPage('관리자: 환경변수 AUTH_SECRET 이 없습니다.'));
  if (!TOKEN) return html(res, 503, closedPage('관리자: 환경변수 BLOB_READ_WRITE_TOKEN 이 없습니다.'));

  // ── 가입·로그인 (로그인 전에도 열려 있는 유일한 경로) ─────────────────────
  if (p === '/api/auth/signup' && req.method === 'POST') {
    const b = await readBody(req);
    const email = normEmail(b.email);
    if (!emailAllowed(email))
      return json(res, 400, { error: '메디빌더 메일(@medibuilder.com)만 가입할 수 있습니다.' });
    if (!SIGNUP_CODE || String(b.code || '') !== SIGNUP_CODE)
      return json(res, 400, { error: '가입코드가 다릅니다.' });
    const bad = pwProblem(b.pw);
    if (bad) return json(res, 400, { error: bad });
    if (String(b.pw) !== String(b.pw2)) return json(res, 400, { error: '비밀번호 확인이 다릅니다.' });

    const store = await loadUsers(TOKEN);
    if (store.users[email]) return json(res, 409, { error: '이미 가입된 메일입니다. 로그인해 주세요.' });
    const { salt, hash } = hashPw(b.pw);
    store.users[email] = {
      email,
      role: isSeedAdmin(email) ? 'admin' : 'member',
      salt,
      hash,
      blocked: false,
      created_at: new Date().toISOString(),
      last_login: new Date().toISOString(),
    };
    await saveUsers(store, TOKEN);
    setSession(res, email);
    return json(res, 200, { ok: true, role: store.users[email].role });
  }

  if (p === '/api/auth/login' && req.method === 'POST') {
    const b = await readBody(req);
    const email = normEmail(b.email);
    const store = await loadUsers(TOKEN);
    const u = store.users[email];
    // 없는 계정과 틀린 비번을 같은 문구로 답한다(누가 가입했는지 흘리지 않는다).
    if (!u || !pwOk(b.pw, u)) return json(res, 401, { error: '메일 또는 비밀번호가 다릅니다.' });
    if (u.blocked) return json(res, 403, { error: '차단된 계정입니다. 관리자에게 문의해 주세요.' });
    u.last_login = new Date().toISOString();
    await saveUsers(store, TOKEN);
    setSession(res, email);
    return json(res, 200, { ok: true, role: u.role });
  }

  if (p === '/api/auth/logout') {
    res.setHeader('set-cookie', `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`);
    res.statusCode = 302;
    res.setHeader('location', '/login');
    return res.end();
  }

  const user = await currentUser(req);

  if (p === '/signup' && !user) return html(res, 401, SIGNUP_PAGE);
  if (p === '/login' && !user) return html(res, 401, LOGIN_PAGE);

  if (!user) {
    if (p.startsWith('/api/') || p.startsWith('/files/'))
      return json(res, 401, { error: '로그인이 필요합니다. 새로고침해 주세요.' });
    return html(res, 401, LOGIN_PAGE);
  }

  if (p === '/login') {
    res.statusCode = 302;
    res.setHeader('location', '/');
    return res.end();
  }

  // ── 관리자 ────────────────────────────────────────────────────────────────
  if (p === '/admin') {
    if (user.role !== 'admin') return html(res, 403, FORBIDDEN_PAGE);
    return html(res, 200, ADMIN_PAGE);
  }

  if (p === '/api/admin/users') {
    if (user.role !== 'admin') return json(res, 403, { error: '관리자만 볼 수 있습니다.' });
    const store = await loadUsers(TOKEN);
    const users = Object.values(store.users)
      .map(publicUser)
      .sort((a, b) => (a.role === b.role ? a.email.localeCompare(b.email) : a.role === 'admin' ? -1 : 1));
    return json(res, 200, { me: user.email, users });
  }

  if (p === '/api/admin/user' && req.method === 'POST') {
    if (user.role !== 'admin') return json(res, 403, { error: '관리자만 바꿀 수 있습니다.' });
    const b = await readBody(req);
    const target = normEmail(b.email);
    const store = await loadUsers(TOKEN);
    const next = {};
    if (b.role !== undefined) next.role = String(b.role);
    if (b.blocked !== undefined) next.blocked = b.blocked === true || b.blocked === 'true';
    if (b.delete === true || b.delete === 'true') next.deleted = true;
    const problem = guardChange(store, target, next);
    if (problem) return json(res, 400, { error: problem });

    if (next.deleted) delete store.users[target];
    else {
      if (next.role) store.users[target].role = next.role;
      if (next.blocked !== undefined) store.users[target].blocked = next.blocked;
    }
    await saveUsers(store, TOKEN);
    return json(res, 200, { ok: true });
  }

  if (p === '/api/me') return json(res, 200, publicUser(user));

  // ── 쓰기 계열 — 공개 URL에 돈 쓰는 버튼을 두지 않는다 ─────────────────────
  if (req.method !== 'GET') return json(res, 405, { error: WRITE_MSG });

  const snap = await snapshot();

  if (p === '/' || p === '/index.html') return html(res, 200, indexHtml(snap, user));

  if (p.startsWith('/files/')) {
    const got = await blobBytes('files/' + p.slice('/files/'.length));
    if (!got) {
      res.statusCode = 404;
      return res.end('not found');
    }
    res.statusCode = 200;
    // Blob 이 octet-stream 으로 돌려주면 브라우저가 사진을 내려받기로 취급할 수 있다.
    res.setHeader(
      'content-type',
      MIME[path.extname(p).toLowerCase()] || got.contentType || 'application/octet-stream',
    );
    res.setHeader('cache-control', 'private, max-age=300');
    return res.end(got.buf);
  }

  if (!p.startsWith('/api/')) {
    res.statusCode = 404;
    return res.end('not found');
  }

  if (!snap)
    return json(res, 503, {
      error: '아직 사무실 PC에서 데이터가 올라오지 않았습니다 (push-cloud 미실행).',
    });

  // readonly 를 화면에 알려 준다 — 이걸 안 주면 버튼이 멀쩡해 보이고, 눌러도 405 라
  // 아무 일도 안 일어난다(2026-09-08 "클릭했을 때 반영이 안 된다"의 뿌리).
  if (p === '/api/config')
    return json(res, 200, { ...snap.config, readonly: true, readonly_msg: WRITE_MSG });
  if (p === '/api/batches') return json(res, 200, snap.batches);
  if (p === '/api/queue') return json(res, 200, snap.queue);
  if (p === '/api/library') return json(res, 200, snap.library);

  if (p === '/api/overview') {
    const want = String(url.searchParams.get('days') || '14');
    const ov = snap.overview || {};
    if (ov[want]) return json(res, 200, ov[want]);
    const keys = Object.keys(ov);
    if (!keys.length) return json(res, 503, { error: '집계가 아직 없습니다.' });
    const near = keys.reduce((a, b) => (Math.abs(+b - +want) < Math.abs(+a - +want) ? b : a));
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
