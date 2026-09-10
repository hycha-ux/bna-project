// 제어문자 거부 규칙이 이스케이프 교체 뒤에도 같은 뜻인지 확인 (2026-09-10 티모)
import { validate } from '../cloud/lib/promote.mjs';

const nl = String.fromCharCode(10), del = String.fromCharCode(127), nul = String.fromCharCode(0);
const cases = [
  ['줄바꿈(0x0a) 거부', validate({ en: 'ok' + nl + 'second', note: 'n' }), true],
  ['DEL(0x7f) 거부', validate({ en: 'has' + del + 'del', note: 'n' }), true],
  ['NUL(0x00) 거부', validate({ en: 'has' + nul + 'nul', note: 'n' }), true],
  ['평범한 ASCII 통과', validate({ en: 'plain ascii sentence', note: 'n' }), false],
];
let bad = 0;
for (const [name, r, wantErr] of cases) {
  const okv = !!r.error === wantErr;
  if (!okv) bad++;
  console.log((okv ? 'PASS  ' : 'FAIL  ') + name);
}
process.exit(bad ? 1 : 0);
