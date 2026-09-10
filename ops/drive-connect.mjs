/**
 * 드라이브 연결 — 파트장님이 딱 한 줄만 실행하면 끝나는 안내형 런처 (2026-09-10, 티모).
 *
 *   node C:\Users\medib\bna-project\ops\drive-connect.mjs
 *
 * 왜 사람이 필요한가: 구글은 "이 프로그램이 당신 드라이브에 파일을 써도 됩니까"를
 * **사람에게만** 묻는다. 프로그램이 스스로 자기에게 허락할 수는 없다(그게 보안의 핵심이다).
 * 그래서 이 한 번의 동의만 사람이 하고, 그 뒤 매일 23:00 백업은 무인으로 돈다.
 *
 * 이 런처가 대신 해주는 것 — 종전엔 문서를 보며 손으로 찾아 들어가야 했다:
 *  1) 눌러야 할 콘솔 화면을 순서대로 브라우저에 띄운다(주소 찾기 없음)
 *  2) 클라이언트 ID·비밀을 붙여넣게 받는다
 *  3) 동의 → 토큰 → 금고 이관 → **첫 백업 실행**까지 한 번에 이어 붙인다
 *
 * ⚠ 윈도우 경로는 반드시 String.raw 로 쓴다 — 홑따옴표 + 백슬래시 하나면 `\t` 가 탭으로
 *   먹혀 경로가 조용히 깨진다(2026-09-10 실측 사고). 회귀가 이걸 지킨다.
 */
import { createInterface } from 'node:readline/promises';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const SETUP = path.join(HERE, 'drive-oauth-setup.mjs');
const BACKUP = path.join(HERE, 'drive-backup.mjs');

const open = (url) =>
  spawn('cmd', ['/c', 'start', '', url.replace(/&/g, '^&')], { detached: true, stdio: 'ignore' }).unref();

const 단계 = [
  {
    제목: '1단계 — 구글 클라우드 프로젝트',
    설명: [
      '브라우저에 열린 화면에서 프로젝트가 없으면 [프로젝트 만들기] → 이름 아무거나(예: bna-backup).',
      '이미 프로젝트가 있으면 그대로 두고 넘어가셔도 됩니다.',
    ],
    url: 'https://console.cloud.google.com/projectcreate',
  },
  {
    제목: '2단계 — Drive API 켜기',
    설명: ['파란 [사용] 버튼 한 번만 누르시면 됩니다. 이미 켜져 있으면 그냥 넘어가세요.'],
    url: 'https://console.cloud.google.com/apis/library/drive.googleapis.com',
  },
  {
    제목: '3단계 — 동의 화면을 내부(Internal)로',
    설명: [
      '사용자 유형에서 [내부]를 고르고 앱 이름·이메일만 채우면 됩니다.',
      'medibuilder.com 계정만 쓰므로 구글 심사가 필요 없습니다(외부로 하면 심사가 붙습니다).',
      '이미 만들어져 있으면 그대로 두세요.',
    ],
    url: 'https://console.cloud.google.com/apis/credentials/consent',
  },
  {
    제목: '4단계 — 클라이언트 만들기',
    설명: [
      '[사용자 인증 정보 만들기] → [OAuth 클라이언트 ID] → 유형은 반드시 **데스크톱 앱**.',
      '리디렉션 주소는 입력하지 않으셔도 됩니다(데스크톱 앱은 자동 허용입니다).',
      '만들면 화면에 뜨는 **클라이언트 ID**와 **클라이언트 보안 비밀** 두 값을 복사해 두세요.',
    ],
    url: 'https://console.cloud.google.com/apis/credentials',
  },
];

const rl = createInterface({ input: process.stdin, output: process.stdout });

console.log('');
console.log('=== B&A 드라이브 백업 연결 ===');
console.log('구글 화면을 순서대로 띄워 드립니다. 각 단계를 끝내시고 엔터를 눌러 주세요.');
console.log('(중간에 그만두시려면 Ctrl+C — 아무것도 저장되지 않습니다)');

for (const s of 단계) {
  console.log('');
  console.log(`── ${s.제목}`);
  for (const line of s.설명) console.log('   ' + line);
  console.log('   주소: ' + s.url);
  open(s.url);
  await rl.question('   끝나셨으면 엔터 > ');
}

console.log('');
console.log('── 5단계 — 두 값 붙여넣기 (값은 화면에만 잠깐 보이고 어디에도 기록하지 않습니다)');
const id = (await rl.question('   클라이언트 ID > ')).trim();
const secret = (await rl.question('   클라이언트 보안 비밀 > ')).trim();
rl.close();

if (!id || !secret) {
  console.error('두 값이 모두 필요합니다. 다시 실행해 주세요.');
  process.exit(2);
}
if (!/\.apps\.googleusercontent\.com$/.test(id)) {
  // 잘못 붙여넣으면 동의 화면이 "잘못된 요청"만 띄우고 끝나 원인이 안 보인다 — 여기서 먼저 세운다.
  console.error('클라이언트 ID 모양이 다릅니다 — 끝이 .apps.googleusercontent.com 이어야 합니다.');
  console.error('4단계 화면에서 ID 쪽을 복사하셨는지 확인해 주세요(비밀과 바뀌기 쉽습니다).');
  process.exit(2);
}
if (!existsSync(SETUP)) {
  console.error(`설치가 깨졌습니다 — ${SETUP} 가 없습니다. 티모에게 알려 주세요.`);
  process.exit(2);
}

console.log('');
console.log('브라우저가 한 번 더 열립니다 — 로그인 후 [허용]을 눌러 주세요.');
const r = spawnSync(process.execPath, [SETUP, '--client-id', id, '--client-secret', secret], {
  stdio: 'inherit',
});
if (r.status !== 0) {
  console.error('');
  console.error('연결이 끝나지 않았습니다. 위 메시지를 티모에게 그대로 전해 주시면 이어서 봅니다.');
  process.exit(r.status || 1);
}

// 여기까지 왔으면 금고에 열쇠가 들어갔다 — 첫 백업까지 이 자리에서 끝낸다.
// (사람에게 "이제 티모에게 알려 주세요"를 시키면 그 한 마디가 빠지는 날 백업도 빠진다.)
console.log('');
console.log('연결됐습니다. 이어서 첫 백업을 올립니다 — 20MB 정도라 1~3분 걸립니다.');
const b = spawnSync(process.execPath, [BACKUP], { stdio: 'inherit', cwd: ROOT });
if (b.status === 0) {
  console.log('');
  console.log('첫 백업까지 끝났습니다. 이제 매일 밤 23:00 에 자동으로 돕니다.');
} else {
  console.error('');
  console.error(`백업이 종료코드 ${b.status} 로 멈췄습니다 — 연결 자체는 됐으니 티모가 이어서 봅니다.`);
}
process.exit(0);
