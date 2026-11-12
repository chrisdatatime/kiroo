// Missão cancelada (bug: depois de cancelar, a tela seguia em "Criando imagens / Missão em andamento").
// Cobre o que alimenta modal, lateral "Próxima ação", lista de missões, mapa e Central: tudo deriva daqui.
import assert from 'node:assert/strict';
import { deriveStage, sceneView, stoppedAt, endedOf } from '../src/engine/adapter.js';
import { buildPipeline, attention, filterMissions, MISSION_FILTERS } from '../src/shell/pipeline.js';
import { STAGES, STAGE_LABELS } from '../src/game/stages.js';

const scene = (status, extra = {}) => ({ idx: 1, title: 'c', motion: '', target_duration_s: 5, image_attempts: 1, video_attempts: 0,
  image: null, video: null, approved_image: null, status, ...extra });
// como prod_aa78ed1022 / prod_57491e2e40: status cancelado, cenas paradas em "gerando", resposta antiga sem `ended`
const old = { status: 'cancelled', creative: { presentation: 'product_only' }, go_ahead: 'all', running: false,
  scenes: [scene('generating_image'), scene('pending', { idx: 2 }), scene('pending', { idx: 3 })] };
const now = { ...old, ended: 'cancelled' };

for (const P of [old, now]) {
  assert.equal(endedOf(P), 'cancelled');
  assert.equal(deriveStage(P), 'cancelada');                        // nunca 'img_gerando'
  assert.equal(STAGE_LABELS[deriveStage(P)], 'Missão cancelada');
  const sv = P.scenes.map((x) => sceneView(x, P.go_ahead, endedOf(P)));
  assert.deepEqual(sv.map((x) => x.img), ['parada', 'none', 'none']); // sem "Criando…" nem "Na fila"
  assert.ok(STAGES.indexOf(stoppedAt(P)) >= 0);                     // onde parou, para mostrar o que existe
}
assert.equal(deriveStage({ ...old, status: 'failed', ended: 'failed' }), 'falhou');
assert.equal(endedOf({ status: 'producing', scenes: [] }), null);
// sem cancelar, tudo como antes
assert.equal(sceneView(scene('generating_image'), 'all').img, 'gerando');
assert.equal(deriveStage({ ...old, status: 'producing', ended: null }), 'img_gerando');
// Direção pendente (app): etapa Direção mesmo com o status 'validated' e sem creative
assert.equal(deriveStage({ status: 'validated', awaiting_direction: true, creative: null, scenes: [] }), 'direcao');

// fluxo: nada "Em andamento" nem "Precisa de você"; orquestrador mostra Cancelada; progresso não some
const p = buildPipeline({ idx: STAGES.indexOf(stoppedAt(now)), statuses: { iris: 'work', rui: 'need' }, hasProd: true, ended: 'cancelled' });
assert.equal(p.orchestrator.state, 'ended');
assert.equal(p.orchestrator.label, 'Cancelada');
assert.equal(p.orchestrator.busy, false);
assert.ok(p.all.every((n) => n.state !== 'work' && n.state !== 'need'), JSON.stringify(p.all.map((n) => [n.id, n.state])));
assert.equal(p.fronts[1].label, 'Interrompido');
assert.ok(p.progress > 0);
assert.equal(buildPipeline({ idx: 3, statuses: { iris: 'work' }, hasProd: true }).fronts[1].state, 'work');   // sem cancelar: igual
// Central/Atividade: missão encerrada não pede decisão
assert.deepEqual(attention({ paused: false, ended: 'cancelled', rooms: [{ id: 'r', need: true }] }), []);

// filtro de missões
const list = [{ id: 'a', status: 'producing' }, { id: 'b', status: 'cancelled' }, { id: 'c', status: 'completed' }, { id: 'd', status: 'failed' }];
assert.deepEqual(MISSION_FILTERS.map((f) => f.id), ['todas', 'andamento', 'concluidas', 'canceladas']);
assert.deepEqual(filterMissions(list, 'canceladas').map((x) => x.id), ['b']);
assert.deepEqual(filterMissions(list, 'andamento').map((x) => x.id), ['a']);
assert.deepEqual(filterMissions(list, 'concluidas').map((x) => x.id), ['c']);
assert.equal(filterMissions(list, 'todas').length, 4);
console.log('ended ok');
