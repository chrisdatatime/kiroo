import assert from 'node:assert/strict';
import { buildPipeline, attention } from '../src/shell/pipeline.js';

const st = (o) => o;
const states = (p) => Object.fromEntries(p.all.map((n) => [n.id, n.state]));

// sem produção: só o objetivo pede você, o resto espera
let p = buildPipeline({ idx: 0, statuses: st({ nina: 'need' }), hasProd: false });
assert.equal(p.goal.state, 'need');
assert.equal(p.orchestrator.state, 'wait');
assert.equal(p.delivery.state, 'wait');

// direção pendente: orquestrador trabalhando, roteiro pede você
p = buildPipeline({ idx: 1, statuses: st({ theo: 'need' }), hasProd: true });
assert.deepEqual(states(p), { objetivo: 'done', orquestrador: 'work', roteiro: 'need', criativo: 'wait', video: 'wait', revisao: 'wait', entrega: 'wait' });

// imagens em geração
p = buildPipeline({ idx: 3, statuses: st({ iris: 'work' }), hasProd: true });
assert.equal(p.fronts[0].state, 'done');
assert.equal(p.fronts[1].state, 'work');
assert.equal(p.orchestrator.busy, true);

// revisão do Rui
p = buildPipeline({ idx: 4, statuses: st({ rui: 'need' }), hasProd: true });
assert.equal(p.review.state, 'need');
assert.equal(p.fronts[1].state, 'wait');

// entrega pronta para revisar e exportada
p = buildPipeline({ idx: 9, statuses: {}, hasProd: true });
assert.equal(p.delivery.state, 'need');
assert.equal(p.fronts.every((f) => f.state === 'done'), true);
p = buildPipeline({ idx: 10, statuses: {}, hasProd: true });
assert.equal(p.all.every((n) => n.state === 'done'), true);
assert.equal(p.progress, 100);

// pausa vira decisão do usuário
p = buildPipeline({ idx: 3, statuses: {}, hasProd: true, paused: true });
assert.equal(p.orchestrator.state, 'need');
const a = attention({ paused: true, pauseReason: 'saldo', rooms: [{ id: 'imagens', name: 'Imagens', who: 'Iris', status: 'Aguardando', need: true }, { id: 'x', need: false }] });
assert.deepEqual(a.map((x) => x.id), ['pausa', 'imagens']);

console.log('pipeline.test ok');
