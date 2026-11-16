import assert from 'node:assert/strict';
import { PHONE_MQ, missionWord, normalizeImageName, canShareFile, shareSupported, shareFallback, shareName } from '../src/ui/mobile.js';
import { falStations, EST_WORKFLOW_S } from '../src/ui/falFlow.js';
import * as falFlow from '../src/ui/falFlow.js';
import * as mobile from '../src/ui/mobile.js';

assert.equal(PHONE_MQ, '(max-width: 767px)');

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

// esteira vertical do celular: lê o `level` de cada estação (falBelt, a mesma fonte do desktop); sem cálculo próprio
assert.equal(mobile.stepFills, undefined); assert.equal(falFlow.FAL_STEP_BOUNDS, undefined);
const t0 = Date.parse('2026-11-14T10:00:00Z');
const P = { engine: 'fal', status: 'producing', running: true, fal: { submitted_at: '2026-11-14T10:00:00Z', remote_status: 'IN_PROGRESS' } };
const a = falStations(P, t0 + 0.5 * EST_WORKFLOW_S * 1000), b = falStations(P, t0 + 0.6 * EST_WORKFLOW_S * 1000);
assert.deepEqual(a.stations.map((s) => s.level), falStations(P, t0 + 0.5 * EST_WORKFLOW_S * 1000).stations.map((s) => s.level));   // estável entre polls
assert.deepEqual(a.stations.map((s) => [s.state, s.label]).slice(0, 4), [['done', 'Concluída'], ['done', 'Concluída'], ['done', 'Concluída'], ['active', 'Em andamento']]);
assert.deepEqual(a.stations.slice(0, 3).map((s) => s.level), [100, 100, 100]);
assert.ok(b.stations[3].level > a.stations[3].level && a.stations[3].level > 0 && b.stations[3].level <= 95);

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
