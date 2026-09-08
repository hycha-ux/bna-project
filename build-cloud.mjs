/**
 * 클라우드 배포본 굽기 — web/ 원본을 cloud/ 로 옮겨 담는다.
 *
 * 원본은 `web/` 하나다(원리: 정본 하나). cloud/web·cloud/public 은 산출물이라
 * 손으로 고치지 마라 — 다음 빌드가 조용히 덮는다.
 *
 *   node build-cloud.mjs
 */
import { cpSync, mkdirSync, rmSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(ROOT, 'web');
const CLOUD = path.join(ROOT, 'cloud');

if (!existsSync(path.join(SRC, 'index.html'))) {
  console.error('web/index.html 이 없다. 리포 루트에서 실행해라.');
  process.exit(1);
}

// index.html 은 함수가 게이트 뒤에서 직접 읽는다(정적으로 두면 잠금 밖이 된다).
rmSync(path.join(CLOUD, 'web'), { recursive: true, force: true });
mkdirSync(path.join(CLOUD, 'web'), { recursive: true });
cpSync(path.join(SRC, 'index.html'), path.join(CLOUD, 'web', 'index.html'));

// 벤더 CSS·로고는 개인정보가 없어 정적으로 서빙한다(함수 왕복 낭비를 줄인다).
const pub = path.join(CLOUD, 'public');
rmSync(pub, { recursive: true, force: true });
mkdirSync(pub, { recursive: true });
for (const dir of ['vendor', 'assets']) {
  const from = path.join(SRC, dir);
  if (existsSync(from)) cpSync(from, path.join(pub, dir), { recursive: true });
}

const kb = (p) => (statSync(p).size / 1024).toFixed(0) + 'KB';
console.log('구움:');
console.log('  cloud/web/index.html      ', kb(path.join(CLOUD, 'web', 'index.html')));
for (const dir of ['vendor', 'assets']) {
  if (existsSync(path.join(pub, dir))) console.log('  cloud/public/' + dir);
}
