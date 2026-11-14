// Progresso da esteira da missão fal. Lógica pura (tests/falbelt.test.mjs).
//
// ESTIMATIVA, NÃO MEDIÇÃO. A fal só informa IN_QUEUE / IN_PROGRESS / COMPLETED: não há evento por nó na fila (o stream
// de nós do playground não funciona sobre a fila e não dá para assistir a uma execução já enviada). Então as quatro etapas
// do workflow (PLANEJAMENTO, ROTEIRO, IMAGENS, VÍDEOS) avançam por TEMPO desde o envio, com pesos tirados de uma rodada
// real (~180 s no total, a maior parte em VÍDEOS). Uma etapa cuja janela de tempo já passou fica "Concluída" (100%);
// só UMA fica em andamento, e essa nunca passa de 95% por estimativa (VÍDEOS fica em 95% com "Finalizando…" se a fal
// demorar). Quando a fal responde COMPLETED, as etapas restantes são preenchidas em sequência (~400 ms cada, sem pular)
// e só depois aparece "Pronto". REVISÃO e EDIÇÃO são etapas reais do nosso servidor (download + validação; composição +
// pacote), derivadas de `fal.stage` e do status da produção.
//
// Fonte ÚNICA do progresso das 6 etapas: a esteira do desktop (Conveyor) e a vertical do celular (BeltVertical) leem
// o `level` de cada estação calculado aqui (via falFlow.falStations).
export const EST_WORKFLOW_S = 180;                       // duração estimada do workflow (não vem da fal)
export const EST_WEIGHTS = [0.08, 0.14, 0.20, 0.58];     // fração do tempo: planejamento, roteiro, imagens, vídeos
export const EST_CAP = 95;                               // teto por estimativa
export const FILL_MS = 400;                              // preenchimento de cada etapa quando a fal termina
export const REAL_HOLD = 50;                             // REVISÃO/EDIÇÃO em andamento no servidor (sem subprogresso)
export const STEP_COUNT = 6;

const RANK = { idle: 0, queued: 1, running: 2, reviewing: 3, editing: 4, delivered: 5 };
const FAL_DONE_STAGES = ['ingesting', 'ingested', 'incomplete', 'delivered'];   // fal.stage: o workflow já terminou
const clamp01 = (x) => Math.max(0, Math.min(1, x));

// Níveis das 4 etapas do workflow após `elapsedS` segundos. Cada etapa tem uma janela de tempo: janela já passada =
// 100 (Concluída); janela atual = curva rápida no começo que desacelera até 95; janela futura = 0. A última (VÍDEOS)
// nunca chega a 100 por estimativa: só a resposta COMPLETED da fal a conclui.
export function estimateLevels(elapsedS) {
  let start = 0;
  return EST_WEIGHTS.map((w, i) => {
    const dur = w * EST_WORKFLOW_S;
    const x = clamp01((elapsedS - start) / dur);
    start += dur;
    if (x >= 1 && i < EST_WEIGHTS.length - 1) return 100;
    return Math.round(EST_CAP * (1 - Math.pow(1 - x, 3)));
  });
}

const notStarted = (P) => ['received', 'awaiting_references', 'validated', 'scripted'].includes(P.status) && !P.running;

// O que o servidor diz que é verdade agora. phase: idle | queued | running | reviewing | editing | delivered.
export function falFacts(P, now = Date.now()) {
  const f = (P && P.fal) || {};
  const st = P ? P.status : '';
  const ended = !!(P && P.ended) || st === 'failed' || st === 'cancelled';
  let phase;
  if (st === 'awaiting_final_review' || st === 'completed') phase = 'delivered';
  else if (st === 'editing') phase = 'editing';
  else if (FAL_DONE_STAGES.includes(f.stage)) phase = 'reviewing';
  else if (notStarted(P) && !f.submitted_at) phase = 'idle';
  else if (f.remote_status === 'IN_QUEUE') phase = 'queued';
  else phase = 'running';
  const sent = f.submitted_at ? Date.parse(f.submitted_at) : NaN;
  const elapsedS = phase === 'running' && Number.isFinite(sent) ? Math.max(0, (now - sent) / 1000) : 0;
  return { phase, rank: RANK[phase], elapsedS, frozen: ended || st === 'paused' };
}

// Níveis "onde o mundo real está", sem animação (primeiro desenho, tela aberta depois, missão parada).
export function settledLevels(facts) {
  const H = REAL_HOLD;
  switch (facts.phase) {
    case 'running': return [...estimateLevels(facts.elapsedS), 0, 0];
    case 'reviewing': return [100, 100, 100, 100, H, 0];
    case 'editing': return [100, 100, 100, 100, 100, H];
    case 'delivered': return [100, 100, 100, 100, 100, 100];
    default: return [0, 0, 0, 0, 0, 0];
  }
}

const fresh = (facts, now) => ({ levels: settledLevels(facts), anim: [], rank: facts.rank, phase: facts.phase, t: now });
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

// Um tique: leva o estado exibido em direção ao estado real. Primeiro tique (ou a missão recomeçou): sem animação.
// Etapa que a estimativa já passou vira 100 na hora; etapa concluída pelo servidor (a fal terminou) é preenchida até
// 100 em FILL_MS. Uma etapa só começa a andar
// depois que a anterior chegou em 100, então há no máximo UMA em andamento e o fim da fal enche as restantes em
// sequência. Nada volta atrás.
export function stepBelt(prev, facts, now) {
  if (!prev || facts.rank < prev.rank) return fresh(facts, now);
  if (facts.frozen) return prev;
  const target = settledLevels(facts);
  const levels = prev.levels.slice();
  const anim = prev.anim.slice();
  let started = false;   // começar uma animação também é mudança (senão o início dela se perderia)
  for (let i = 0; i < STEP_COUNT; i++) {
    const tg = target[i];
    if (i > 0 && levels[i - 1] < 100) continue;
    if (tg >= 100) {
      if (levels[i] >= 100) continue;
      if (facts.phase === 'running') { levels[i] = 100; continue; }   // a estimativa passou da janela: Concluída na hora (sem 96..99% "em andamento")
      if (!anim[i]) { anim[i] = { from: levels[i], t0: now }; started = true; }
      const p = clamp01((now - anim[i].t0) / FILL_MS);
      levels[i] = p >= 1 ? 100 : Math.max(levels[i], Math.round(anim[i].from + (100 - anim[i].from) * p));
    } else if (tg > levels[i]) levels[i] = tg;
  }
  if (!started && same(levels, prev.levels) && facts.rank === prev.rank) return prev;
  return { levels, anim, rank: facts.rank, phase: facts.phase, t: now };
}

// Etapa atual (0..5; 6 = tudo pronto; null = ainda não começou): a primeira ainda não em 100.
export function currentStep(levels, phase) {
  if (phase === 'idle') return null;
  const i = levels.findIndex((l) => l < 100);
  return i < 0 ? STEP_COUNT : i;
}

export const overallProgress = (levels) => Math.round(levels.reduce((a, b) => a + b, 0) / STEP_COUNT);
