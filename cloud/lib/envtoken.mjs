/**
 * 사무실 PC 스크립트용 Blob 토큰 읽기 — `cloud/.env.local` 의 BLOB_READ_WRITE_TOKEN (값 미출력).
 * push-cloud.mjs·push-progress.mjs 가 같이 쓴다(두 벌이면 한쪽만 고쳐져 갈린다).
 * ⚠ 클라우드 함수(api/app.js)는 이걸 쓰지 않는다 — 거기선 Vercel 환경변수가 정본이다.
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const CLOUD = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

export function blobToken() {
  const f = path.join(CLOUD, '.env.local');
  if (!existsSync(f))
    throw new Error('cloud/.env.local 이 없다. `cd cloud && npx vercel env pull` 을 먼저 돌려라.');
  for (const line of readFileSync(f, 'utf8').split(/\r?\n/)) {
    const m = /^BLOB_READ_WRITE_TOKEN\s*=\s*"?([^"\r\n]+)"?/.exec(line);
    if (m) return m[1];
  }
  throw new Error('cloud/.env.local 에 BLOB_READ_WRITE_TOKEN 이 없다.');
}
