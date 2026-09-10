/**
 * B안 전용 — 파트장님 계정으로 드라이브 접근 권한을 한 번만 받아 오는 도우미 (2026-09-08).
 *
 * 언제 쓰나: 공유 드라이브를 못 만들어 **개인 드라이브 폴더**에 백업해야 할 때.
 * 서비스 계정은 제 저장용량이 0이라 개인 폴더에 못 올린다 → 사람 계정의 권한을 빌린다.
 * 브라우저 동의 1회면 끝이고, 그 뒤로는 무인으로 갱신된다(리프레시 토큰).
 *
 *   node ops/drive-oauth-setup.mjs --client-id <ID> --client-secret <비밀> --folder <폴더ID>
 *
 * 끝나면 `C:\Users\medib\_teemo_keys.txt` 에 필요한 줄을 적어 둔다 —
 * 이어서 `node C:\Users\medib\teemo\install-keys.mjs` 를 돌리면 티모 금고로 들어가고 원본은 지워진다.
 *
 * ⚠ 이 스크립트는 **값을 화면에 찍지 않는다**(토큰이 터미널 기록·스크린샷에 남지 않게).
 */
import { createServer } from 'node:http';
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import { spawn, spawnSync } from 'node:child_process';

const PORT = 53682; // 데스크톱 앱 유형은 loopback(127.0.0.1:임의포트)을 자동 허용한다 — 콘솔에 URI 등록 불필요
const OUT = 'C:\\Users\\medib\\_teemo_keys.txt';
// ⚠ 윈도우 경로는 반드시 String.raw 로 쓴다 — 홑따옴표에 백슬래시 하나면 `\t` 가 탭으로,
//   `\U`·`\m` 은 글자로 먹혀 경로가 조용히 깨진다(2026-09-10 실측: 이 줄이 깨져 있어
//   동의는 끝나고 금고 이관만 실패 → 리프레시 토큰이 평문 txt 로 남을 뻔했다).
export const INSTALL_KEYS = String.raw`C:\Users\medib\teemo\install-keys.mjs`;
const SCOPE = 'https://www.googleapis.com/auth/drive';

function arg(name) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 ? process.argv[i + 1] : null;
}

const id = arg('client-id');
const secret = arg('client-secret');
const folder = arg('folder');
if (!id || !secret) {
  console.error('사용법: node ops/drive-oauth-setup.mjs --client-id <ID> --client-secret <비밀> [--folder <폴더ID>]');
  console.error('  구글 클라우드 콘솔 → 사용자 인증 정보 → OAuth 클라이언트 ID(데스크톱 앱)에서 받는다.');
  process.exit(2);
}

const url =
  'https://accounts.google.com/o/oauth2/v2/auth?' +
  new URLSearchParams({
    client_id: id,
    redirect_uri: `http://127.0.0.1:${PORT}`,
    response_type: 'code',
    scope: SCOPE,
    access_type: 'offline',
    prompt: 'consent', // 리프레시 토큰은 첫 동의 때만 나온다 — 매번 받도록 강제한다
  });

console.log('브라우저가 열리면 파트장님 계정으로 로그인하고 [허용]을 눌러 주세요.');
console.log('안 열리면 이 주소를 직접 여세요:\n' + url);
spawn('cmd', ['/c', 'start', '', url.replace(/&/g, '^&')], { detached: true, stdio: 'ignore' }).unref();

const srv = createServer(async (req, res) => {
  const code = new URL(req.url, `http://127.0.0.1:${PORT}`).searchParams.get('code');
  if (!code) {
    res.writeHead(400).end('코드가 없습니다. 다시 시도해 주세요.');
    return;
  }
  try {
    const r = await fetch('https://oauth2.googleapis.com/token', {
      method: 'POST',
      body: new URLSearchParams({
        code,
        client_id: id,
        client_secret: secret,
        redirect_uri: `http://127.0.0.1:${PORT}`,
        grant_type: 'authorization_code',
      }),
    });
    const j = await r.json();
    if (!j.refresh_token) throw new Error(`리프레시 토큰이 안 왔다 (${j.error || r.status}) — 동의 화면에서 [허용]을 눌렀는지 확인`);

    const lines =
      [`GDRIVE_CLIENT_ID=${id}`, `GDRIVE_CLIENT_SECRET=${secret}`, `GDRIVE_REFRESH_TOKEN=${j.refresh_token}`]
        .concat(folder ? [`GDRIVE_BACKUP_FOLDER_ID=${folder}`] : [])
        .join('\n') + '\n';
    appendFileSync(OUT, (existsSync(OUT) && readFileSync(OUT, 'utf8').trim() ? '\n' : '') + lines, 'utf8');

    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(
      '<h2>완료했습니다. 이 창을 닫으셔도 됩니다.</h2><p>티모가 이어서 처리합니다.</p>',
    );
    console.log(`받았습니다 — ${OUT} 에 ${folder ? 4 : 3}줄을 적었습니다(값은 화면에 찍지 않습니다).`);
    // 금고 이관까지 여기서 끝낸다 (2026-09-10). 종전엔 "이어서 install-keys 를 돌리세요"라고 안내만 했는데,
    // 그 한 줄이 안 돌면 토큰이 평문 txt 로 남는다 — 사람에게 시키는 단계는 적을수록 안전하다.
    try {
      const r = spawnSync(process.execPath, [INSTALL_KEYS], { stdio: 'inherit' });
      if (r.status !== 0) throw new Error(`install-keys 종료코드 ${r.status}`);
      console.log('금고(keys.env)까지 옮겼습니다. 티모에게 알려 주시면 첫 백업을 돌립니다.');
    } catch (e) {
      console.error('금고 이관 실패:', e.message);
      console.error(`⚠ ${OUT} 에 값이 평문으로 남아 있습니다 — node ${INSTALL_KEYS} 를 직접 돌려 주세요.`);
    }
    setTimeout(() => process.exit(0), 300);
  } catch (e) {
    res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' }).end('<h2>실패했습니다.</h2>');
    console.error('실패:', e.message);
    setTimeout(() => process.exit(1), 300);
  }
});
srv.listen(PORT, '127.0.0.1');
setTimeout(() => {
  console.error('10분 안에 동의가 끝나지 않아 종료합니다.');
  process.exit(1);
}, 600_000).unref?.();
