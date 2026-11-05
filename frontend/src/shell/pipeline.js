// Fluxo da missão ("o motor nos bastidores"): objetivo → orquestrador → frentes → revisão → entrega.
// Derivação pura do estado real (índice da etapa + status por agente); sem React, testável em Node.
// idx = posição em STAGES (0 produto … 10 exportado). statuses[id] = 'need' | 'work' | 'idle'.

export const STATE_LABEL = { done: 'Concluído', work: 'Em andamento', need: 'Precisa de você', wait: 'Aguardando' };

const pick = (...ss) => (ss.includes('need') ? 'need' : ss.includes('work') ? 'work' : 'wait');

export function buildPipeline({ idx, statuses = {}, hasProd, paused = false, detail = {} }) {
  const front = (done, ...ids) => (done ? 'done' : pick(...ids.map((i) => statuses[i])));
  const fronts = [
    { id: 'roteiro', title: 'Roteiro', agents: ['nina', 'theo'], tab: 'direcao', state: hasProd || idx > 0 ? front(idx >= 2, 'nina', 'theo') : front(false, 'nina') },
    { id: 'criativo', title: 'Criativo', agents: ['iris'], tab: 'imagens', state: front(idx >= 5, 'iris') },
    { id: 'video', title: 'Vídeo', agents: ['lia'], tab: 'videos', state: front(idx >= 8, 'lia') },
  ];
  const review = { id: 'revisao', title: 'Revisão e aprovação', agents: ['rui'], tab: 'revisao', state: idx >= 8 ? 'done' : pick(statuses.rui) };
  const delivery = { id: 'entrega', title: 'Entrega concluída', agents: ['beto'], tab: 'entrega', state: idx >= 10 ? 'done' : idx === 9 ? 'need' : idx === 8 ? 'work' : 'wait' };
  const anyWork = fronts.some((f) => f.state === 'work') || review.state === 'work' || delivery.state === 'work';
  const orchestrator = { id: 'orquestrador', title: 'Orquestrador Kiroo', agents: [], state: !hasProd ? 'wait' : paused ? 'need' : idx >= 10 ? 'done' : 'work', busy: anyWork };
  const goal = { id: 'objetivo', title: 'Objetivo do usuário', agents: [], tab: 'produto', state: hasProd ? 'done' : 'need' };
  const all = [goal, orchestrator, ...fronts, review, delivery];
  all.forEach((n) => { n.detail = detail[n.id] || ''; n.label = STATE_LABEL[n.state]; });
  return { goal, orchestrator, fronts, review, delivery, all, progress: Math.round((all.filter((n) => n.state === 'done').length / all.length) * 100) };
}

// O que precisa de decisão agora, em ordem de urgência (alimenta a Central).
export function attention({ paused, pauseReason, rooms = [] }) {
  const out = [];
  if (paused) out.push({ id: 'pausa', kind: 'pause', title: 'Missão pausada', text: pauseReason || 'A missão pausou e espera sua decisão.' });
  rooms.filter((r) => r.need).forEach((r) => out.push({ id: r.id, kind: 'agent', title: r.name, who: r.who, text: r.status, room: r }));
  return out;
}
