/**
 * 진행 표시 실시간 반영 — 순수 함수 (2026-09-15 티모, 빌디 제안 5번 · 성연서님 "진행해볼까?").
 *
 * 왜 따로 있나: 클라우드 화면의 진행 막대는 `snapshot.json` 에 실린 progress 를 읽는데, 스냅샷은
 * 사진 1장이 *판정될 때만* 올라간다(한 번에 8~20초짜리 전체 올리기). 그래서 한 장이 그려지는 동안
 * (1콜 ≈105초 × 비포·후) 화면이 몇 분씩 멈춰 있어 "멈춤 vs 그리는 중"을 못 가렸다 — 09-15 09:48
 * 재부팅 무응답이 1시간 동안 화면에서 안 보인 이유다.
 *
 * 그래서 PC 가 `progress/<배치>.json` 한 파일만 따로 올린다(단계가 바뀔 때 30초 간격 + 60초 심장박동,
 * src/bna/cloudpush.py 의 nudge_progress). 이 모듈은 그 파일과 스냅샷 중 **더 새 것**을 고르고,
 * 마지막 신호가 몇 초 전인지(`live.age_s`)를 붙인다. 화면은 `live.stale` 로 멈춤을 표시하면 된다.
 *
 * ⚠ 요약(summary) 산식은 여기서 다시 짜지 않는다 — PC 의 `progress.read()` 가 만든 값을 그대로 싣는다(정본 하나).
 */
export const PREFIX = 'progress/';
export const HEARTBEAT_S = 60;      // PC 가 변화 없어도 이 간격으로 신호를 보낸다(cloudpush.HEARTBEAT_S 와 한 쌍)
export const STALE_S = 5 * 60;      // 진행 중인데 마지막 신호가 이보다 오래면 '멈춤 의심' — 심장박동 5번 놓침

const ID_RE = /^\d{8}-\d{6}-[a-z0-9]{2,12}$/;
/** 배치 ID 형식 검사 — Blob 경로에 들어가므로 `..`·슬래시가 섞인 값은 거부한다. */
export const validId = (id) => ID_RE.test(String(id ?? ''));

export function liveName(id) {
  if (!validId(id)) throw new Error('잘못된 배치 ID: ' + id);
  return `${PREFIX}${id}.json`;
}

/** 진행 기록의 마지막 움직임(초). 스냅샷 쪽 비교 기준. */
export function lastActivity(p) {
  if (!p) return 0;
  const ts = [p.started_at, p.finished_at, ...Object.values(p.items || {}).map((it) => it?.updated_at)];
  return Math.max(0, ...ts.map(Number).filter(Number.isFinite));
}

/**
 * 스냅샷 진행(snapProg)과 PC 가 따로 올린 실시간 진행(live) 중 더 새 것을 고른다.
 * 반환값은 로컬 API 와 같은 모양(summary·items …) + `live` 필드.
 *   live.used    실시간 파일을 썼나
 *   live.age_s   마지막 신호가 몇 초 전인가(실시간 파일이 없으면 null)
 *   live.stale   진행 중인데 신호가 STALE_S 넘게 끊겼나(끝난 배치는 false, 모르면 null)
 */
export function pickProgress(snapProg, live, nowS) {
  const liveAt = live ? Number(live.pushed_at) : NaN;
  const liveOk = !!(live && live.summary && live.items && Number.isFinite(liveAt));
  const useLive = liveOk && (!snapProg || liveAt >= lastActivity(snapProg));
  const v = useLive ? live : snapProg;
  if (!v) return null;
  const age = liveOk ? Math.max(0, Math.round(nowS - liveAt)) : null;
  const running = !!v.summary?.running;
  return {
    ...v,
    live: { used: useLive, pushed_at: liveOk ? liveAt : null, age_s: age, stale: running ? (age == null ? null : age > STALE_S) : false },
  };
}

/** 배치 목록의 진행 요약을 실시간 값으로 갈아 끼운다. lives = {배치ID: 실시간 진행}. */
export function mergeList(batches, lives, nowS) {
  return (batches || []).map((b) => {
    const lv = lives?.[b.batch_id];
    if (!lv) return b;
    const picked = pickProgress(b.progress ? { summary: b.progress, items: {}, started_at: 0 } : null, lv, nowS);
    return picked && picked.live.used ? { ...b, progress: { ...picked.summary, live: picked.live } } : b;
  });
}

/** 올려 둔 실시간 파일 중 지워도 되는 것 — 스냅샷이 '진행 중'이라고 하지 않는 배치 전부. */
export function prunable(pathnames, snapProgress) {
  return (pathnames || []).filter((pn) => {
    if (!pn.startsWith(PREFIX)) return false;
    const id = pn.slice(PREFIX.length).replace(/\.json$/, '');
    return !snapProgress?.[id]?.summary?.running;
  });
}
