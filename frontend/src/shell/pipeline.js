// Fluxo da missão ("o motor nos bastidores"): objetivo → orquestrador → frentes → revisão → entrega.
// Derivação pura do estado real (índice da etapa + status por agente); sem React, testável em Node.
// idx = posição em STAGES (0 produto … 10 exportado). statuses[id] = 'need' | 'work' | 'idle'.

export const STATE_LABEL = { done: 'Concluído', work: 'Em andamento', need: 'Precisa de você', wait: 'Aguardando',
  ended: 'Interrompido' };
export const ENDED_LABEL = { cancelled: 'Cancelada', failed: 'Falhou' };

const pick = (...ss) => (ss.includes('need') ? 'need' : ss.includes('work') ? 'work' : 'wait');

// Esteira de agentes: seis estações, um agente em cada, na ordem em que o trabalho passa de mão em mão.
// O estado de cada estação sai dos MESMOS nós abaixo (nenhuma regra nova): roteiro vira Produto (Nina) + Direção (Theo),
// criativo vira Imagens (Iris), vídeo vira Vídeos (Lia); Revisão (Rui) e Entrega (Beto) são os próprios nós.
export const STATIONS = [
  { id: 'produto', agent: 'nina', title: 'Produto', tab: 'produto' },
  { id: 'direcao', agent: 'theo', title: 'Direção', tab: 'direcao' },
  { id: 'imagens', agent: 'iris', title: 'Imagens', tab: 'imagens' },
  { id: 'revisao', agent: 'rui', title: 'Revisão', tab: 'revisao' },
  { id: 'videos', agent: 'lia', title: 'Vídeos', tab: 'videos' },
  { id: 'entrega', agent: 'beto', title: 'Entrega', tab: 'entrega' },
];
// pending (apagada) · active (trabalhando) · need (esperando seu OK) · done · problem (pausa/falha) · ended (interrompida) · cancelled (selo)
export const STATION_LABEL = { pending: 'Pendente', active: 'Em andamento', need: 'Esperando seu OK', done: 'Concluída',
  problem: 'Com problema', ended: 'Interrompida', cancelled: 'Cancelada' };
const STATION_STATE = { done: 'done', work: 'active', need: 'need', wait: 'pending', ended: 'ended' };

// Em que estação a missão está em cada posição do fluxo (STAGES). Rui aparece duas vezes: revisa imagens (4) e takes (7).
export function stationAt(idx) {
  if (idx <= 0) return 'produto';
  if (idx === 1) return 'direcao';
  if (idx <= 3) return 'imagens';
  if (idx === 4) return 'revisao';
  if (idx <= 6) return 'videos';
  if (idx === 7) return 'revisao';
  return 'entrega';
}

// `ended` = 'cancelled' | 'failed' | null. Encerrada: nada fica "Em andamento" nem "Precisa de você"; o que não
// terminou aparece como Interrompido e o orquestrador mostra Cancelada/Falhou.
export function buildPipeline({ idx, statuses = {}, hasProd, paused = false, detail = {}, ended = null }) {
  const front = (done, ...ids) => (done ? 'done' : ended ? 'ended' : pick(...ids.map((i) => statuses[i])));
  const fronts = [
    { id: 'roteiro', title: 'Roteiro', agents: ['nina', 'theo'], tab: 'direcao', state: hasProd || idx > 0 ? front(idx >= 2, 'nina', 'theo') : front(false, 'nina') },
    { id: 'criativo', title: 'Criativo', agents: ['iris'], tab: 'imagens', state: front(idx >= 5, 'iris') },
    { id: 'video', title: 'Vídeo', agents: ['lia'], tab: 'videos', state: front(idx >= 8, 'lia') },
  ];
  const review = { id: 'revisao', title: 'Revisão e aprovação', agents: ['rui'], tab: 'revisao', state: idx >= 8 ? 'done' : ended ? 'ended' : pick(statuses.rui) };
  const delivery = { id: 'entrega', title: 'Entrega concluída', agents: ['beto'], tab: 'entrega', state: idx >= 10 ? 'done' : ended ? 'ended' : idx === 9 ? 'need' : idx === 8 ? 'work' : 'wait' };
  const anyWork = !ended && (fronts.some((f) => f.state === 'work') || review.state === 'work' || delivery.state === 'work');
  const orchestrator = { id: 'orquestrador', title: 'Orquestrador Kiroo', agents: [], state: !hasProd ? 'wait' : ended ? 'ended' : paused ? 'need' : idx >= 10 ? 'done' : 'work', busy: anyWork };
  const goal = { id: 'objetivo', title: 'Objetivo do usuário', agents: [], tab: 'produto', state: hasProd ? 'done' : 'need' };
  const all = [goal, orchestrator, ...fronts, review, delivery];
  all.forEach((n) => { n.detail = detail[n.id] || ''; n.label = STATE_LABEL[n.state]; });
  if (ended) orchestrator.label = ENDED_LABEL[ended] || 'Encerrada';

  // Estações da esteira (mesmas regras dos nós, separadas por agente)
  const nodeState = {
    produto: !hasProd ? 'need' : idx >= 1 ? 'done' : front(false, 'nina'),
    direcao: idx >= 2 ? 'done' : !hasProd || idx < 1 ? 'wait' : front(false, 'theo'),
    imagens: fronts[1].state, revisao: review.state, videos: fronts[2].state, entrega: delivery.state,
  };
  const stations = STATIONS.map((s) => ({ ...s, state: STATION_STATE[nodeState[s.id]], detail: detail[s.id] || '' }));
  const here = hasProd ? stationAt(idx) : 'produto';
  const at = stations.find((s) => s.id === here);
  if (hasProd && ended) {   // congelada: o que não terminou fica Interrompida; onde parou leva o selo
    if (at.state !== 'done') at.state = ended === 'cancelled' ? 'cancelled' : 'problem';
  } else if (hasProd && paused && at.state !== 'done') at.state = 'problem';
  stations.forEach((s) => { s.label = STATION_LABEL[s.state]; });
  if (hasProd && ended === 'failed' && at.state === 'problem') at.label = 'Falhou';
  else if (hasProd && paused && !ended && at.state === 'problem') at.label = 'Pausada';
  const live = stations.find((s) => ['active', 'need', 'problem', 'cancelled'].includes(s.state));
  const current = live ? live.id : hasProd && idx < 10 ? here : null;
  stations.forEach((s) => { s.current = s.id === current; });

  return { goal, orchestrator, fronts, review, delivery, all, stations, current,
    progress: Math.round((all.filter((n) => n.state === 'done').length / all.length) * 100) };
}

// Filtro da lista de missões. "Em andamento" = não encerrada; falha aparece só em "Todas" (não é andamento nem cancelamento).
export const MISSION_FILTERS = [
  { id: 'todas', label: 'Todas' }, { id: 'andamento', label: 'Em andamento' },
  { id: 'concluidas', label: 'Concluídas' }, { id: 'canceladas', label: 'Canceladas' },
];
const ENDED_STATUSES = ['completed', 'cancelled', 'failed'];
export function filterMissions(list, filter) {
  if (filter === 'andamento') return list.filter((p) => !ENDED_STATUSES.includes(p.status));
  if (filter === 'concluidas') return list.filter((p) => p.status === 'completed');
  if (filter === 'canceladas') return list.filter((p) => p.status === 'cancelled');
  return list;
}

// O que precisa de decisão agora, em ordem de urgência (alimenta a Central).
export function attention({ paused, pauseReason, rooms = [], ended = null }) {
  const out = [];
  if (ended) return out;   // missão encerrada não pede decisão de ninguém
  if (paused) out.push({ id: 'pausa', kind: 'pause', title: 'Missão pausada', text: pauseReason || 'A missão pausou e espera sua decisão.' });
  rooms.filter((r) => r.need).forEach((r) => out.push({ id: r.id, kind: 'agent', title: r.name, who: r.who, text: r.status, room: r }));
  return out;
}
