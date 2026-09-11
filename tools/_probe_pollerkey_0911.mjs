/**
 * 프로브 — **예약작업이 띄운 폴러**가 로컬 API 에 생성 키를 물려주는지. 돈 0원·생성 0.
 *
 * 2026-09-11 사고의 재현 조건을 그대로 만든다: 부모 환경에서 `OPENAI_API_KEY` 를 **지우고**
 * (작업 스케줄러 환경이 그 모양이다) 폴러와 같은 방식으로 자식 env 를 만들어 파이썬을 띄운 뒤,
 * `NotConfigured` 가 나던 바로 그 줄(`providers.get("openai")`)까지만 간다 — 생성은 안 부른다.
 *
 * 읽는 법: `PASS` 두 줄이면 예약작업 경로로도 키가 닿는다. 값은 찍지 않는다(유무만).
 *   node tools/_probe_pollerkey_0911.mjs
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mergeKeys, PROVIDER_KEYS } from '../ops/gen-poller.mjs';
import { existsSync, readFileSync } from 'node:fs';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const KEYS_FILE = process.env.BNA_KEYS_FILE || path.join('C:', 'Users', 'medib', 'teemo', 'keys.env');

// ① 작업 스케줄러 환경 흉내 — 생성 키를 통째로 뺀 부모 환경
const bare = { ...process.env };
for (const k of PROVIDER_KEYS) delete bare[k];

const text = existsSync(KEYS_FILE) ? readFileSync(KEYS_FILE, 'utf8') : '';
const env = { ...mergeKeys(bare, text), PYTHONPATH: 'src', PYTHONIOENCODING: 'utf-8' };

console.log(`① 부모(예약작업 흉내) 에 OPENAI_API_KEY 있나: ${bare.OPENAI_API_KEY ? '있음' : '없음(재현 성공)'}`);
console.log(`   자식에게 넘길 env 에 있나           : ${env.OPENAI_API_KEY ? '있음' : '없음'}`);
console.log(env.OPENAI_API_KEY ? 'PASS  파일에서 읽어 자식 env 를 채웠다' : 'FAIL  자식 env 가 비었다');

// ② 실제로 그 env 로 파이썬을 띄워, 죽던 그 줄까지 간다(생성 호출 없음 = 돈 0원)
const py = ['.venv/Scripts/python.exe', '.venv/bin/python'].map((p) => path.join(ROOT, p)).find(existsSync) || 'python';
const code = 'from bna import providers\np = providers.get("openai")\nprint("OPENAI_OK", p.name, bool(p.key))\n';
const r = spawnSync(py, ['-c', code], { cwd: ROOT, env, encoding: 'utf8', timeout: 60000 });
const out = `${r.stdout || ''}${r.stderr || ''}`.trim();
const pass = /OPENAI_OK openai True/.test(out);
console.log(`② 자식 파이썬: ${out.split('\n').pop()}`);
console.log(pass ? 'PASS  프로바이더가 키를 잡았다(NotConfigured 없음)' : 'FAIL  자식이 키를 못 잡았다');

process.exit(env.OPENAI_API_KEY && pass ? 0 : 1);
