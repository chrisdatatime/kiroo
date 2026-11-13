// Esteira de agentes: estados por estação (derivados do pipeline), transição (salto), cancelada, movimento reduzido,
// créditos por etapa e miniatura. Lógica pura; a renderização está em conveyor-render.test.mjs.
import assert from 'node:assert/strict';
import { buildPipeline, STATIONS, stationAt } from '../src/shell/pipeline.js';
import { hopBetween, shouldHop, hopGeometry, creditsByStation, taskThumb, stationAria, TASK_ICON } from '../src/shell/conveyor.js';

const states = (p) => Object.fromEntries(p.stations.map((s) => [s.id, s.state]));
const ids = STATIONS.map((s) => s.id);
assert.deepEqual(ids, ['produto', 'direcao', 'imagens', 'revisao', 'videos', 'entrega']);
assert.deepEqual(STATIONS.map((s) => s.agent), ['nina', 'theo', 'iris', 'rui', 'lia', 'beto']);

// sem missão: só a Nina espera você; o resto apagado
let p = buildPipeline({ idx: 0, statuses: { nina: 'need' }, hasProd: false });
assert.deepEqual(states(p), { produto: 'need', direcao: 'pending', imagens: 'pending', revisao: 'pending', videos: 'pending', entrega: 'pending' });
assert.equal(p.current, 'produto');

// direção pendente: Nina concluída, Theo esperando seu OK
p = buildPipeline({ idx: 1, statuses: { theo: 'need' }, hasProd: true, detail: { direcao: 'Precisa de aprovação' } });
assert.deepEqual(states(p), { produto: 'done', direcao: 'need', imagens: 'pending', revisao: 'pending', videos: 'pending', entrega: 'pending' });
assert.equal(p.stations[1].label, 'Esperando seu OK');
assert.equal(p.stations[1].detail, 'Precisa de aprovação');
assert.equal(p.current, 'direcao');
assert.equal(p.stations.filter((s) => s.current).length, 1);

// Theo escrevendo: ativa
p = buildPipeline({ idx: 1, statuses: { theo: 'work' }, hasProd: true });
assert.equal(states(p).direcao, 'active');

// imagens em geração: Iris ativa com o que está acontecendo; Rui ainda apagado
p = buildPipeline({ idx: 3, statuses: { iris: 'work' }, hasProd: true, detail: { imagens: 'Criando cena 2' } });
assert.deepEqual(states(p), { produto: 'done', direcao: 'done', imagens: 'active', revisao: 'pending', videos: 'pending', entrega: 'pending' });
assert.equal(p.stations[2].detail, 'Criando cena 2');
assert.equal(p.current, 'imagens');

// revisão das imagens: Rui espera você; a estação de Imagens segue como no fluxo (criativo só conclui ao liberar vídeos)
p = buildPipeline({ idx: 4, statuses: { rui: 'need' }, hasProd: true });
assert.equal(states(p).revisao, 'need');
assert.equal(states(p).imagens, 'pending');
assert.equal(p.current, 'revisao');

// vídeos liberados: Iris concluída, Lia espera sua liberação
p = buildPipeline({ idx: 5, statuses: { lia: 'need' }, hasProd: true });
assert.deepEqual(states(p), { produto: 'done', direcao: 'done', imagens: 'done', revisao: 'pending', videos: 'need', entrega: 'pending' });

// montando: Beto ativo; entrega pronta: Beto espera você; exportado: tudo concluído, sem estação atual
p = buildPipeline({ idx: 8, statuses: {}, hasProd: true });
assert.deepEqual(states(p), { produto: 'done', direcao: 'done', imagens: 'done', revisao: 'done', videos: 'done', entrega: 'active' });
assert.equal(buildPipeline({ idx: 9, statuses: {}, hasProd: true }).stations[5].state, 'need');
p = buildPipeline({ idx: 10, statuses: {}, hasProd: true });
assert.ok(p.stations.every((s) => s.state === 'done'));
assert.equal(p.current, null);

// pausa: a estação onde a missão está vira alerta "Pausada"
p = buildPipeline({ idx: 3, statuses: { iris: 'work' }, hasProd: true, paused: true });
assert.equal(states(p).imagens, 'problem');
assert.equal(p.stations[2].label, 'Pausada');

// cancelada: congelada. Nada ativo nem esperando você; onde parou leva o selo; o resto não concluído fica Interrompida
p = buildPipeline({ idx: 3, statuses: { iris: 'work', rui: 'need' }, hasProd: true, ended: 'cancelled' });
assert.deepEqual(states(p), { produto: 'done', direcao: 'done', imagens: 'cancelled', revisao: 'ended', videos: 'ended', entrega: 'ended' });
assert.equal(p.stations[2].label, 'Cancelada');
assert.equal(p.stations[3].label, 'Interrompida');
assert.ok(p.stations.every((s) => s.state !== 'active' && s.state !== 'need'));
assert.equal(p.current, 'imagens');
// cancelada antes da direção
p = buildPipeline({ idx: 1, statuses: {}, hasProd: true, ended: 'cancelled' });
assert.deepEqual(states(p), { produto: 'done', direcao: 'cancelled', imagens: 'ended', revisao: 'ended', videos: 'ended', entrega: 'ended' });
// falhou: alerta
p = buildPipeline({ idx: 6, statuses: {}, hasProd: true, ended: 'failed' });
assert.equal(states(p).videos, 'problem');
assert.equal(p.stations[4].label, 'Falhou');

// onde a missão está em cada posição do fluxo
assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(stationAt),
  ['produto', 'direcao', 'imagens', 'imagens', 'revisao', 'videos', 'videos', 'revisao', 'entrega', 'entrega', 'entrega']);

// ---- transição (salto) ----
const S = (o) => STATIONS.map((s) => ({ ...s, state: o[s.id] || 'pending' }));
// direção aprovada: Theo concluiu, Iris espera sua liberação → salto Theo → Iris
assert.deepEqual(hopBetween(S({ produto: 'done', direcao: 'need' }), S({ produto: 'done', direcao: 'done', imagens: 'need' })), { from: 'direcao', to: 'imagens' });
// imagem pronta: Iris passa a bola ao Rui (Iris não "concluiu", mas deixou de estar viva)
assert.deepEqual(hopBetween(S({ produto: 'done', direcao: 'done', imagens: 'active' }), S({ produto: 'done', direcao: 'done', revisao: 'need' })), { from: 'imagens', to: 'revisao' });
// Rui aprova e a Iris volta a trabalhar: salto para trás na faixa (Rui → Iris)
assert.deepEqual(hopBetween(S({ produto: 'done', direcao: 'done', revisao: 'need' }), S({ produto: 'done', direcao: 'done', imagens: 'active' })), { from: 'revisao', to: 'imagens' });
// nada mudou, ou mudou sem passar a bola: sem salto
assert.equal(hopBetween(S({ imagens: 'active' }), S({ imagens: 'active' })), null);
assert.equal(hopBetween(S({ imagens: 'active' }), S({ imagens: 'need' })), null);
// sem snapshot anterior (abriu a tela depois): mostra o estado final, sem reproduzir
assert.equal(hopBetween(null, S({ produto: 'done', direcao: 'done', imagens: 'active' })), null);
// cancelada ou pausada: congelada, nunca salta
assert.equal(hopBetween(S({ produto: 'done', direcao: 'need' }), S({ produto: 'done', direcao: 'cancelled', imagens: 'ended' })), null);
assert.equal(hopBetween(S({ imagens: 'active' }), S({ imagens: 'problem' })), null);
// shouldHop: movimento reduzido desliga o salto; missão diferente não compara
const prev = S({ produto: 'done', direcao: 'need' }), next = S({ produto: 'done', direcao: 'done', imagens: 'need' });
assert.deepEqual(shouldHop({ reduced: false, prevKey: 'p1', key: 'p1', prev, next }), { from: 'direcao', to: 'imagens' });
assert.equal(shouldHop({ reduced: true, prevKey: 'p1', key: 'p1', prev, next }), null);
assert.equal(shouldHop({ reduced: false, prevKey: 'p1', key: 'p2', prev, next }), null);
assert.equal(shouldHop({ reduced: false, prevKey: 'p1', key: 'p1', prev: null, next }), null);
// geometria: centro das estações
assert.deepEqual(hopGeometry({ left: 100, width: 140 }, { left: 400, width: 140 }), { x0: 170, x1: 470 });
assert.equal(hopGeometry(null, { left: 0, width: 10 }), null);

// ---- miniatura e ícone ----
const slots = { imgSlots: [{ status: 'aprovada', url: '/media/a.png' }, { status: 'aprovada', url: '/media/b.png' }, { status: 'gerando', url: null }],
  vidSlots: [{ status: 'aprovada', url: '/media/a.mp4' }] };
assert.deepEqual(taskThumb('imagens', slots), { url: '/media/b.png', video: false });
assert.deepEqual(taskThumb('videos', slots), { url: '/media/a.mp4', video: true });
assert.equal(taskThumb('imagens', { imgSlots: [{ status: 'gerando', url: null }] }), null);   // sem miniatura → ícone genérico
assert.equal(taskThumb('direcao', slots), null);
assert.equal(TASK_ICON.direcao, 'edit');

// ---- créditos por etapa: só do extrato real; sem dado, nada ----
const usage = [{ production_id: 'p1', stages: [{ stage: 'Imagens', cc: 1850 }, { stage: 'Conferência das imagens', cc: 200 }, { stage: 'Conferência dos takes', cc: 50 }, { stage: 'Outra coisa', cc: 999 }] }];
assert.deepEqual(creditsByStation(usage, 'p1'), { imagens: '18,50', revisao: '2,50' });
assert.deepEqual(creditsByStation(usage, 'p2'), {});
assert.deepEqual(creditsByStation(null, 'p1'), {});
assert.deepEqual(creditsByStation([{ production_id: 'p1', stages: [{ stage: 'Imagens', cc: 0 }] }], 'p1'), {});

// ---- rótulo para leitor de tela ----
assert.equal(stationAria({ title: 'Imagens', label: 'Em andamento', detail: 'Criando cena 2', state: 'active' }, 'Iris'), 'Iris, Imagens: Em andamento. Criando cena 2.');
assert.equal(stationAria({ title: 'Direção', label: 'Esperando seu OK', detail: '', state: 'need' }, 'Theo'), 'Theo, Direção: Esperando seu OK. Abrir para decidir.');

console.log('conveyor ok');
