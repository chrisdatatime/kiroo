import assert from 'node:assert/strict';
import { PHONE_MQ, missionWord, stepFills, normalizeImageName, canShareFile, shareSupported, shareFallback, shareName } from '../src/ui/mobile.js';
import { falStations, EST_WORKFLOW_S, FAL_STEP_BOUNDS, falProgress } from '../src/ui/falFlow.js';

assert.equal(PHONE_MQ, '(max-width: 640px)');

// status em uma palavra (com tom)
assert.deepEqual(missionWord({ status: 'producing' }), { word: 'Criando', tone: 'work' });
assert.deepEqual(missionWord({ status: 'awaiting_final_review' }), { word: 'Pronto', tone: 'done' });
assert.deepEqual(missionWord({ status: 'completed' }), { word: 'Exportado', tone: 'done' });
assert.deepEqual(missionWord({ status: 'paused' }), { word: 'Pausada', tone: 'warn' });
assert.deepEqual(missionWord({ status: 'failed' }), { word: 'Falhou', tone: 'bad' });
assert.deepEqual(missionWord({ status: 'producing', ended: 'cancelled' }), { word: 'Cancelada', tone: 'off' });
assert.deepEqual(missionWord({ status: 'algo_novo' }), { word: 'Aguardando', tone: 'need' });
assert.equal(missionWord(null).word, '—');
assert.deepEqual(missionWord({ status: 'received', engine: 'fal' }), { word: 'Aguardando', tone: 'need' });   // fal antes do /run
assert.deepEqual(missionWord({ status: 'producing', engine: 'fal' }), { word: 'Criando', tone: 'work' });
assert.deepEqual(missionWord({ status: 'received', engine: 'fal' }, 'running'), { word: 'Criando', tone: 'work' });   // status real vence
assert.deepEqual(missionWord({ status: 'awaiting_final_review' }, 'done'), { word: 'Pronto', tone: 'done' });
assert.deepEqual(missionWord({ status: 'completed' }, 'done'), { word: 'Exportado', tone: 'done' });
assert.deepEqual(missionWord({ status: 'paused', engine: 'fal' }, 'limit'), { word: 'Pausada', tone: 'warn' });

// barras da esteira vertical: mesmo progresso geral da esteira do desktop
const st = (states) => states.map((s, k) => ({ id: 's' + k, state: s, current: s !== 'done' && s !== 'pending' }));
assert.deepEqual(stepFills(st(['done', 'done', 'active', 'pending', 'pending', 'pending']), 41), [100, 100, 46, 0, 0, 0]);
assert.deepEqual(stepFills(st(['active', 'pending', 'pending', 'pending', 'pending', 'pending']), 0), [6, 0, 0, 0, 0, 0]);    // nunca vazia
assert.deepEqual(stepFills(st(['done', 'active', 'pending', 'pending', 'pending', 'pending']), 90), [100, 94, 0, 0, 0, 0]);  // nunca cheia antes da hora
assert.deepEqual(stepFills(st(['need', 'pending', 'pending', 'pending', 'pending', 'pending']), 0), [100, 0, 0, 0, 0, 0]);
assert.deepEqual(stepFills(st(['done', 'done', 'done', 'done', 'done', 'done']), 100), [100, 100, 100, 100, 100, 100]);
// com a esteira fal real: estável entre dois polls (mesma entrada → mesma saída) e a atual cresce com o tempo
const t0 = Date.parse('2026-11-14T10:00:00Z');
const P = { engine: 'fal', status: 'producing', running: true, fal: { submitted_at: '2026-11-14T10:00:00Z', remote_status: 'IN_PROGRESS' } };
const a = falStations(P, t0 + 0.5 * EST_WORKFLOW_S * 1000), b = falStations(P, t0 + 0.6 * EST_WORKFLOW_S * 1000);
const fa = stepFills(a.stations, a.progress, FAL_STEP_BOUNDS), fb = stepFills(b.stations, b.progress, FAL_STEP_BOUNDS);
assert.deepEqual(fa, stepFills(a.stations, a.progress, FAL_STEP_BOUNDS));
assert.equal(a.stations[3].state, 'active');
assert.ok(fb[3] > fa[3] && fa[3] >= 6 && fb[3] <= 94);
assert.deepEqual(fa.slice(0, 3), [100, 100, 100]);
// a faixa de cada etapa bate com falProgress: logo depois do envio (Roteiro) a barra já anda, sem ficar presa no mínimo
assert.deepEqual(FAL_STEP_BOUNDS[0], [0, 8]); assert.deepEqual(FAL_STEP_BOUNDS[5], [90, 100]);
for (let k = 1; k < 6; k++) assert.equal(FAL_STEP_BOUNDS[k][0], FAL_STEP_BOUNDS[k - 1][1]);
const early = falStations(P, t0 + 0.08 * EST_WORKFLOW_S * 1000);
assert.equal(early.stations[1].state, 'active');
const fe = stepFills(early.stations, early.progress, FAL_STEP_BOUNDS)[1];
assert.ok(fe > 50 && fe < 94, 'Roteiro a 2/3 do trecho: ' + fe);
// fronteiras: o início de cada etapa (por tempo) cai no começo da faixa dela
const at = (f) => falProgress(P, t0 + f * EST_WORKFLOW_S * 1000);
assert.ok(Math.abs(at(0.12) - FAL_STEP_BOUNDS[2][0]) <= 0.5 && Math.abs(at(0.85) - FAL_STEP_BOUNDS[4][0]) <= 0.5);   // falProgress arredonda

// foto do celular sem extensão
assert.equal(normalizeImageName('IMG_0001.JPG', 'image/jpeg'), 'IMG_0001.JPG');
assert.equal(normalizeImageName('1000012345', 'image/jpeg'), '1000012345.jpg');
assert.equal(normalizeImageName('foto.heic', 'image/heic'), 'foto.heic');          // HEIC continua recusado pela validação
assert.equal(normalizeImageName('', 'image/png'), 'foto.png');
assert.equal(normalizeImageName('x.tmp', 'image/webp'), 'x.webp');

// Web Share com arquivo
const file = { name: 'v.mp4' };
assert.equal(canShareFile(null, file), false);
assert.equal(canShareFile({ share() {} }, file), false);                              // sem canShare: download
assert.equal(canShareFile({ share() {}, canShare: () => true }, file), true);
assert.equal(canShareFile({ share() {}, canShare: () => false }, file), false);
assert.equal(canShareFile({ share() {}, canShare: () => { throw new Error('x'); } }, file), false);
assert.equal(shareSupported({ share() {}, canShare() {} }), true);
assert.equal(shareSupported({}), false);
assert.equal(shareFallback({ name: 'AbortError' }), false);
assert.equal(shareFallback({ name: 'NotAllowedError' }), true);
assert.equal(shareName('Copo Térmico Azul!', 'video', '.mp4'), 'copo-termico-azul-video.mp4');
assert.equal(shareName('', 'foto', '.jpg'), 'kiroo-foto.jpg');

console.log('mobile: ok');
