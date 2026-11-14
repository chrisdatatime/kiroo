import assert from 'node:assert/strict';
import { EST_WORKFLOW_S, EST_WEIGHTS, EST_CAP, FILL_MS, estimateLevels, falFacts, settledLevels, stepBelt, currentStep, overallProgress } from '../src/ui/falBelt.js';
import { falStations, falStatus } from '../src/ui/falFlow.js';

// Cálculo do progresso da esteira fal (ESTIMADO por tempo + etapas reais do servidor). Sem rede, sem relógio real.
// Não existe teste "por eventos de nó": a fal não os entrega na fila (ver o comentário de falBelt.js).
const T0 = Date.parse('2026-11-14T12:00:00Z');
const P = (o, fal = {}) => ({ id: 'p1', engine: 'fal', status: 'producing', running: true, delivery: {}, fal: { submitted_at: '2026-11-14T12:00:00+00:00', remote_status: 'IN_PROGRESS', ...fal }, ...o });

// pesos somam 1; maior parte em VÍDEOS
assert.ok(Math.abs(EST_WEIGHTS.reduce((a, b) => a + b, 0) - 1) < 1e-9);
assert.ok(EST_WEIGHTS[3] > 0.5);

// estimativa: sobe e é monotônica; janela passada = 100 (Concluída); a etapa em andamento nunca passa de 95;
// VÍDEOS (a última do workflow) nunca é concluída por estimativa
let prevL = [0, 0, 0, 0];
for (let s = 0; s <= EST_WORKFLOW_S * 10; s += 1) {
  const l = estimateLevels(s);
  l.forEach((v, i) => { assert.ok(v >= prevL[i] && (v <= EST_CAP || (v === 100 && i < 3)), `etapa ${i} em ${s}s: ${v}`); });
  assert.ok(l.filter((v) => v > 0 && v < 100).length <= 1, `mais de uma em andamento em ${s}s`);
  prevL = l;
}
assert.deepEqual(estimateLevels(0), [0, 0, 0, 0]);
assert.deepEqual(estimateLevels(EST_WORKFLOW_S * 100), [100, 100, 100, 95]);
const w0 = EST_WEIGHTS[0] * EST_WORKFLOW_S;
assert.ok(estimateLevels(w0 * 0.5)[0] - estimateLevels(w0 * 0.25)[0] > estimateLevels(w0 * 1)[0] - estimateLevels(w0 * 0.75)[0]);   // desacelera
assert.equal(estimateLevels(w0 * 0.1)[1], 0);                                                          // roteiro só começa depois do planejamento
assert.ok(estimateLevels(w0 + 1)[1] > 0);

// fatos do servidor
assert.equal(falFacts(P({ status: 'validated', running: false }, { submitted_at: null }), T0).phase, 'idle');
assert.equal(falFacts(P({}, { remote_status: 'IN_QUEUE' }), T0 + 5000).phase, 'queued');
assert.equal(falFacts(P({}), T0 + 30000).elapsedS, 30);
assert.equal(falFacts(P({}, { stage: 'ingesting' }), T0).phase, 'reviewing');                          // REVISÃO real
assert.equal(falFacts(P({ status: 'editing' }), T0).phase, 'editing');                                  // EDIÇÃO real
assert.equal(falFacts(P({ status: 'awaiting_final_review' }), T0).phase, 'delivered');
assert.equal(falFacts(P({ status: 'paused' }), T0).frozen, true);

// primeiro desenho = estado assentado, sem animação (abrir a tela depois mostra o estado real)
const first = (o, s) => stepBelt(null, falFacts(P(...o), T0 + s * 1000), T0 + s * 1000);
assert.deepEqual(first([{ status: 'awaiting_final_review' }], 0).levels, [100, 100, 100, 100, 100, 100]);
assert.deepEqual(first([{}], 0).levels, [0, 0, 0, 0, 0, 0]);

// roda um relógio simulado; devolve o histórico dos níveis
function run(prev, mk, fromMs, toMs, stepMs = 100) {
  const hist = []; let st = prev;
  for (let t = fromMs; t <= toMs; t += stepMs) { st = stepBelt(st, falFacts(mk(t), T0 + t), T0 + t); hist.push({ t, levels: st.levels.slice() }); }
  return { st, hist };
}

// FAL TERMINOU CEDO (aos 20 s, estimativa em ROTEIRO): não pula; preenche em sequência até 100 e só então fica pronto
const running = () => P({});
const a = run(null, running, 0, 20000, 100);
a.hist.forEach((h) => assert.ok(h.levels.every((v) => v <= EST_CAP || v === 100), 'em andamento acima de 95% por estimativa'));
const before = a.st.levels.slice();
assert.equal(before[0], 100); assert.ok(before.slice(1, 4).every((v) => v < 100) && before[4] === 0 && before[5] === 0);   // planejamento já passou: Concluída
const delivered = () => P({ status: 'awaiting_final_review' });
const b = run(a.st, delivered, 20100, 20100 + 6 * FILL_MS + 1500);
const doneAt = (i) => b.hist.find((h) => h.levels[i] >= 100).t;
for (let i = 1; i < 6; i++) assert.ok(doneAt(i) >= doneAt(i - 1), `etapa ${i} concluiu antes da ${i - 1}`);   // ordem
assert.ok(doneAt(5) - 20100 >= 5 * FILL_MS, 'não pode pular: precisa de ~400 ms por etapa');
assert.ok(doneAt(5) - 20100 <= 6 * FILL_MS + 600);
b.hist.forEach((h, k) => {                                                                              // monotônico; REVISÃO/EDIÇÃO só andam depois da etapa anterior em 100
  if (k) h.levels.forEach((v, i) => assert.ok(v >= b.hist[k - 1].levels[i], 'nível recuou'));
  for (let i = 4; i < 6; i++) if (h.levels[i] > 0) assert.equal(h.levels[i - 1], 100);
});
assert.deepEqual(b.st.levels, [100, 100, 100, 100, 100, 100]);
// "Pronto" só depois da última etapa em 100
const viewEarly = { levels: b.hist[2].levels, anim: [], rank: 5, phase: 'delivered', t: 0 };
assert.equal(falStatus(delivered(), T0, viewEarly).kind, 'running');
assert.equal(falStations(delivered(), T0, viewEarly).allDone, false);
assert.equal(falStatus(delivered(), T0, b.st).kind, 'done');
assert.equal(falStations(delivered(), T0, b.st).allDone, true);

// REVISÃO e EDIÇÃO reais: após a fal terminar, seguem o servidor (ingesting → editing → delivered), sempre em ordem
const rv = run(a.st, () => P({}, { stage: 'ingesting' }), 20100, 20100 + 6000);
assert.deepEqual(rv.st.levels.slice(0, 4), [100, 100, 100, 100]); assert.ok(rv.st.levels[4] > 0 && rv.st.levels[4] < 100); assert.equal(rv.st.levels[5], 0);
assert.equal(currentStep(rv.st.levels, rv.st.phase), 4);
const ed = run(rv.st, () => P({ status: 'editing' }), 26200, 26200 + 3000);
assert.deepEqual(ed.st.levels.slice(0, 5), [100, 100, 100, 100, 100]); assert.ok(ed.st.levels[5] > 0 && ed.st.levels[5] < 100);
assert.equal(currentStep(ed.st.levels, ed.st.phase), 5);

// FAL DEMOROU (muito além da estimativa): vídeos fica perto de 95 com "Finalizando…"; nada concluído por estimativa
const slow = run(a.st, running, 21000, EST_WORKFLOW_S * 3000, 100);
assert.deepEqual(slow.st.levels, [100, 100, 100, 95, 0, 0]);
slow.hist.forEach((h) => assert.ok(h.levels.filter((v) => v > 0 && v < 100).length <= 1, 'mais de uma em andamento'));   // nunca duas ao mesmo tempo
slow.hist.forEach((h) => assert.ok(h.levels.every((v) => v <= EST_CAP || v === 100), 'em andamento acima de 95% por estimativa'));
assert.equal(currentStep(slow.st.levels, slow.st.phase), 3);
const sv = falStations(running(), T0 + EST_WORKFLOW_S * 3000, slow.st);
assert.equal(sv.status.text, 'Finalizando…'); assert.equal(sv.stations[3].label, 'Finalizando…');
assert.deepEqual(sv.stations.map((s) => s.label), ['Concluída', 'Concluída', 'Concluída', 'Finalizando…', 'Pendente', 'Pendente']);
assert.equal(sv.status.kind, 'running');

// fila: nada avança e a etapa 1 mostra "Na fila"
const q = falStations(P({}, { remote_status: 'IN_QUEUE' }), T0 + 60000);
assert.equal(q.stations[0].label, 'Na fila'); assert.deepEqual(q.stations.map((s) => s.level), [0, 0, 0, 0, 0, 0]);

// missão pausada/encerrada congela: o tempo não move a barra
assert.equal(stepBelt(a.st, falFacts(P({ status: 'paused' }), T0 + 90000), T0 + 90000), a.st);
// recomeço (fase anterior à exibida) volta ao assentado, sem animar "para trás"
assert.deepEqual(stepBelt(b.st, falFacts(P({}), T0 + 3000), T0 + 3000).levels, [...estimateLevels(3), 0, 0]);

// sem mudança: o mesmo objeto (a tela não re-renderiza à toa)
const pIdle = () => P({ status: 'validated', running: false }, { submitted_at: null });
const idle = stepBelt(null, falFacts(pIdle(), T0), T0);
assert.equal(stepBelt(idle, falFacts(pIdle(), T0 + 500), T0 + 500), idle);
assert.equal(overallProgress([100, 100, 100, 100, 100, 100]), 100); assert.equal(overallProgress([0, 0, 0, 0, 0, 0]), 0);
assert.deepEqual(settledLevels({ phase: 'idle' }), [0, 0, 0, 0, 0, 0]);
console.log('falbelt.test ok');
