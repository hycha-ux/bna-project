/**
 * Vercel 빌드 단계 — 배포 직전에 `web/` 원본으로 `cloud/web`·`cloud/public` 을 다시 굽는다.
 *
 * 왜 굽는가: 커밋된 산출물만 믿으면 누가 `web/index.html` 만 고치고 `build-cloud.mjs` 를
 * 안 돌린 채 푸시했을 때 *옛 화면이 조용히 배포된다*. 여기서 다시 구우면 그 틈이 없다.
 * (프로젝트 설정 `sourceFilesOutsideRootDirectory=true` 라서 루트 밖 `web/` 이 보인다.)
 *
 * 원본이 안 보이면 커밋된 산출물로 진행하되 경고를 크게 남긴다 — 배포를 죽이는 것보다
 * 낫지만, 조용히 넘어가지도 않는다.
 */
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const srcIndex = path.join(ROOT, 'web', 'index.html');
const builtIndex = path.join(HERE, 'web', 'index.html');

if (existsSync(srcIndex)) {
  const r = spawnSync(process.execPath, [path.join(ROOT, 'build-cloud.mjs')], {
    cwd: ROOT,
    stdio: 'inherit',
  });
  if (r.status !== 0) process.exit(r.status || 1);
  console.log('vercel-build: web/ 원본으로 다시 구웠다.');
} else if (existsSync(builtIndex)) {
  console.warn('⚠ vercel-build: web/ 원본이 안 보인다 — 커밋된 산출물로 배포한다(낡았을 수 있다).');
} else {
  console.error('vercel-build: web/index.html 도 cloud/web/index.html 도 없다. 배포를 멈춘다.');
  process.exit(1);
}
