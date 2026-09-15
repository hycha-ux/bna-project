/**
 * 진행 기록 한 파일만 클라우드에 올린다 (2026-09-15 티모, 빌디 제안 5번).
 *
 *   node cloud/push-progress.mjs <요약 JSON 경로> <배치ID>        # 올린다
 *   node cloud/push-progress.mjs <요약 JSON 경로> <배치ID> --dry  # 무엇을 올릴지만
 *
 * 부르는 쪽은 src/bna/cloudpush.py 의 nudge_progress 다(30초 간격·60초 심장박동). 요약은 파이썬
 * `progress.read()` 가 만들어 파일로 넘긴다 — 여기서 산식을 다시 짜지 않는다(정본 하나).
 * 사진·스냅샷은 건드리지 않는다(그건 push-cloud.mjs). 한 번에 PUT 1건이라 1~2초로 끝난다.
 * 다 끝난 배치의 파일은 push-cloud.mjs 가 스냅샷을 올린 뒤 지운다(lib/liveprog.mjs 의 prunable).
 */
import { readFileSync } from 'node:fs';
import { put } from '@vercel/blob';
import { liveName } from './lib/liveprog.mjs';
import { blobToken } from './lib/envtoken.mjs';

const [file, id] = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const DRY = process.argv.includes('--dry');

async function main() {
  if (!file || !id) throw new Error('사용법: node cloud/push-progress.mjs <요약 JSON> <배치ID> [--dry]');
  const name = liveName(id);                         // 형식이 틀린 ID 는 여기서 던진다
  const body = readFileSync(file, 'utf8');
  const j = JSON.parse(body);
  if (!j.summary || !Number.isFinite(Number(j.pushed_at))) throw new Error('요약(summary)·pushed_at 이 없는 파일이다');
  if (DRY) return console.log(`[dry] ${name} · ${j.summary.done}/${j.summary.planned} · ${(body.length / 1024).toFixed(1)}KB`);
  await put(name, body, { access: 'private', token: blobToken(), addRandomSuffix: false, allowOverwrite: true, contentType: 'application/json' });
  console.log(`진행 올림 · ${name} · ${j.summary.done}/${j.summary.planned}${j.summary.running ? '' : ' · 끝'}`);
}

main().catch((e) => {
  console.error('진행 올리기 실패:', e.message);
  process.exit(1);
});
