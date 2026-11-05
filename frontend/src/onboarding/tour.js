// Kit de onboarding (Fase 5): passos e lógica pura do tour. Sem React nem DOM aqui: testado em tests/onboarding.test.mjs.
//
// Como adicionar um passo: inclua um objeto em STEPS (ordem = ordem do tour) com
//   id       identificador estável (não reaproveite ids: o passo salvo no servidor é o índice em STEPS)
//   kind     'dialog' (centralizado, sem alvo) ou 'spot' (recorte em volta do alvo)
//   targets  valores de data-tour="..." em ordem de preferência; o primeiro visível vence; nenhum → card centralizado
//   view     view do Shell a abrir antes de mostrar o passo (opcional)
//   side     lado preferido do card: bottom | right | top | left
//   interactive  true deixa usar o alvo (o mundo) com o tour aberto
//   skip(ctx)    true pula o passo (ex.: mundo desligado)
//   title / body texto ou função (ctx) => texto
// e marque o elemento real com data-tour="<alvo>".

export const STEPS = [
  { id: 'welcome', kind: 'dialog', title: 'Boas-vindas ao Kiroo',
    body: 'O Kiroo é uma equipe de agentes que transforma um produto em uma missão de produção. Em 1 minutinho a gente mostra onde fica cada coisa.' },
  { id: 'team', kind: 'spot', view: 'central', targets: ['team', 'team-head'], side: 'right', title: 'Sua equipe',
    body: 'São 6 agentes, cada um numa etapa: Nina prepara, Theo dirige, Iris faz as imagens, Lia os vídeos, Rui revisa e Beto edita. O pontinho mostra quem está livre ou trabalhando; clique para abrir a etapa.' },
  { id: 'new-mission', kind: 'spot', view: 'central', targets: ['new-mission'], side: 'bottom', title: 'Nova missão',
    body: 'Tudo começa aqui. Você descreve o produto e a equipe organiza o fluxo.' },
  { id: 'overview', kind: 'spot', view: 'central', targets: ['overview'], side: 'bottom', title: 'Central',
    body: 'Decisões pendentes, a missão em curso e o consumo de créditos. É o painel para bater o olho.' },
  { id: 'needs-you', kind: 'spot', view: 'central', targets: ['needs-you', 'next-action'], side: 'top', title: 'Precisa de você',
    body: 'Aprovações, liberações de gasto e decisões aparecem aqui e na Próxima ação do painel. Quem depende de você ganha um “!”.' },
  { id: 'modes', kind: 'spot', view: 'central', targets: ['top-modes'], side: 'bottom', title: 'Saldo e piloto',
    body: (c) => `${c.walletExempt ? '“Isento” é o seu saldo: este estúdio não paga pelo consumo, só registra.' : 'Aqui fica o seu saldo de créditos; clique para ver o extrato.'} `
      + `E o Piloto${c.pilotLabel ? ` (${c.pilotLabel})` : ''}, aqui no topo ou no menu do logo, define quanto a equipe decide sozinha: Manual, Assistido ou Automático.` },
  { id: 'office', kind: 'spot', view: 'escritorio', targets: ['office', 'office-rail'], side: 'inside', interactive: true, skip: (c) => c.world === false,
    title: 'O escritório',
    body: 'Ande com WASD, setas ou clicando no chão, sente nas cadeiras e chegue perto de alguém para conversar (E). Quem mostra o “!” precisa de você. Pode testar agora.' },
  { id: 'account', kind: 'spot', targets: ['account'], side: 'right', title: 'Conta e preferências',
    body: 'Aqui ficam sua conta, os créditos, Sobre e créditos e o “Rever tutorial”, se quiser ver tudo de novo.' },
  { id: 'done', kind: 'dialog', final: true, title: 'Tudo pronto!',
    body: 'Sua equipe está esperando o primeiro produto. Bora?' },
];

export const text = (x, ctx) => (typeof x === 'function' ? x(ctx || {}) : x);

/** Índices (em STEPS) que valem para este usuário. */
export function activeSteps(ctx = {}, steps = STEPS) {
  return steps.map((s, i) => i).filter((i) => !(steps[i].skip && steps[i].skip(ctx)));
}

/** Onde o tour começa ao entrar: null se já concluiu/pulou; senão o passo salvo (ajustado a um passo ativo). */
export function resumeIndex(onboarding, ctx = {}, steps = STEPS) {
  if (!onboarding || onboarding.done_at) return null;
  return nearestActive(Number(onboarding.step) || 0, ctx, steps);
}

export function nearestActive(i, ctx = {}, steps = STEPS) {
  const act = activeSteps(ctx, steps);
  const k = Math.max(0, Math.min(steps.length - 1, i | 0));
  return act.find((x) => x >= k) ?? act[act.length - 1];
}

/** Progresso mostrado no card ("3 de 8"): conta só os passos ativos que não são a conclusão. */
export function progress(i, ctx = {}, steps = STEPS) {
  const act = activeSteps(ctx, steps).filter((x) => !steps[x].final);
  return { n: Math.max(1, act.indexOf(i) + 1), total: act.length };
}

/**
 * Controlador do tour: guarda o índice e chama save() com o que o servidor precisa.
 *   save({ step })             passo atual (para retomar)
 *   save({ step, done: true }) concluído ou pulado
 */
export function createTour({ start = 0, ctx = {}, steps = STEPS, save = () => {} } = {}) {
  let i = nearestActive(start, ctx, steps);
  const act = () => activeSteps(ctx, steps);
  const t = {
    get index() { return i; },
    get step() { return steps[i]; },
    get isFirst() { return act()[0] === i; },
    get isLast() { const a = act(); return a[a.length - 1] === i; },
    go(k) { i = nearestActive(k, ctx, steps); save({ step: i }); return i; },
    next() { const a = act(); const p = a.indexOf(i); if (p < a.length - 1) { i = a[p + 1]; save({ step: i }); } return i; },
    prev() { const a = act(); const p = a.indexOf(i); if (p > 0) { i = a[p - 1]; save({ step: i }); } return i; },
    close() { save({ step: i }); },                       // Esc / fechar: volta daqui no próximo login
    skip() { save({ step: i, done: true }); },            // pular: conta como concluído
    finish() { save({ step: 0, done: true }); },          // terminou: "Rever tutorial" recomeça do 1
  };
  return t;
}

/** Primeiro alvo visível (retângulo com área e dentro da tela). query(id) devolve o elemento ou null. */
export function findTarget(ids, query, vp) {
  for (const id of ids || []) {
    const el = query(id);
    if (!el) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    if (vp && (r.right <= 0 || r.bottom <= 0 || r.left >= vp.w || r.top >= vp.h)) continue;
    return { id, el, rect: { x: r.left, y: r.top, w: r.width, h: r.height } };
  }
  return null;
}

/** Como mostrar um passo: dialog, spot (com recorte) ou center (alvo ausente → card no centro). */
export function layoutFor(step, query, vp) {
  if (!step || step.kind === 'dialog') return { mode: 'dialog' };
  const t = findTarget(step.targets, query, vp);
  if (!t) return { mode: 'center' };
  return { mode: 'spot', target: t.id, rect: clipRect(t.rect, vp) };
}

const PAD = 6;
function clipRect(r, vp) {
  if (!vp) return r;
  const x = Math.max(4, r.x - PAD), y = Math.max(4, r.y - PAD);
  return { x, y, w: Math.min(vp.w - 4, r.x + r.w + PAD) - x, h: Math.min(vp.h - 4, r.y + r.h + PAD) - y };
}

/**
 * Posição do card ao lado do alvo. Tenta o lado preferido, depois os outros; se nada couber (alvo enorme, como o mundo),
 * fica por dentro, no canto superior direito. Devolve { x, y, side, arrow } (arrow = deslocamento da seta no card).
 */
export function placeCard(rect, size, vp, prefer = 'bottom', gap = 14, margin = 12) {
  const order = [prefer, 'bottom', 'right', 'top', 'left'].filter((s, k, a) => s !== 'inside' && a.indexOf(s) === k);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2;
  const fits = {
    bottom: rect.y + rect.h + gap + size.h <= vp.h - margin,
    top: rect.y - gap - size.h >= margin,
    right: rect.x + rect.w + gap + size.w <= vp.w - margin,
    left: rect.x - gap - size.w >= margin,
  };
  if (prefer !== 'inside') {
    for (const side of order) {
      if (!fits[side]) continue;
      if (side === 'bottom' || side === 'top') {
        const x = clamp(cx - size.w / 2, margin, vp.w - margin - size.w);
        const y = side === 'bottom' ? rect.y + rect.h + gap : rect.y - gap - size.h;
        return { x, y, side, arrow: clamp(cx - x, 18, size.w - 18) };
      }
      const y = clamp(cy - size.h / 2, margin, vp.h - margin - size.h);
      const x = side === 'right' ? rect.x + rect.w + gap : rect.x - gap - size.w;
      return { x, y, side, arrow: clamp(cy - y, 18, size.h - 18) };
    }
  }
  // por dentro, no canto superior direito: o centro (onde a câmera põe o jogador) e o HUD de baixo ficam livres
  const x = clamp(rect.x + rect.w - size.w - 16, margin, vp.w - margin - size.w);
  const y = clamp(rect.y + 16, margin, vp.h - margin - size.h);
  return { x, y, side: 'inside', arrow: null };
}
