// Fluxo do motor fal.ai: 1 foto + estilo (Escuro/Claro) → vídeo (com narração) + 1 foto + título e legenda. Lógica pura (tests/falflow.test.mjs).
// Só aparece quando o servidor diz `settings.video_engine === 'fal'` ou a produção aberta é `engine === 'fal'`.

export const STYLES = [
  { id: 'dark', label: 'Escuro', hint: 'Cinematográfico: iluminação dramática, cenário premium e apresentação de impacto.' },
  { id: 'light', label: 'Claro', hint: 'Lifestyle: ambientes residenciais claros, luz natural e fundo predominantemente branco.' },
];
// Estilos que o servidor libera (settings.fal_styles). Hoje só o Claro: sem seletor, o envio é sempre o Claro.
export const availableStyles = (S) => {
  const ids = ((S && S.settings && S.settings.fal_styles) || []).map((x) => x.id);
  const list = STYLES.filter((s) => ids.includes(s.id));
  return list.length ? list : STYLES.filter((s) => s.id === 'light');
};
export const effectiveStyle = (S, chosen) => {
  const av = availableStyles(S);
  return av.some((s) => s.id === chosen) ? chosen : (av.length === 1 ? av[0].id : null);
};
export const FINAL_FINALIZING = 'Estamos finalizando o seu pacote. Avisaremos quando estiver pronto.';
export const IMAGE_EXT = /\.(jpe?g|png|webp)$/i;

export const isFalProduction = (P) => !!(P && P.engine === 'fal');
const incompleteDelivery = (P) => ['incomplete', 'partial'].includes((P.fal && P.fal.delivery_status) || P.delivery_status);
// O fluxo fal.ai vale para a missão nova (motor da conta) e para qualquer produção que já seja fal.
export const falActive = (S, P, draftMode) => (draftMode || !P ? !!(S && S.settings && S.settings.video_engine === 'fal') : isFalProduction(P));

// UUID por envio: o mesmo valor é reutilizado em um reenvio, e o servidor devolve a produção que já existe (duplo clique).
export function newRequestId(rnd = () => globalThis.crypto && globalThis.crypto.randomUUID && globalThis.crypto.randomUUID()) {
  const id = rnd();
  return id || `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

export function draftErrors({ style, file }) {
  const e = [];
  if (!file) e.push('a foto do produto');
  else if (!IMAGE_EXT.test(file.name || '')) e.push('uma foto JPG, PNG ou WEBP');
  if (!style) e.push('o estilo (Escuro ou Claro)');
  return e;
}

export function createPayload({ style, file, requestId, name }) {
  const body = { style, client_request_id: requestId, files: [{ name: file.name, data: file.data }] };
  if (name && name.trim()) body.name = name.trim();
  return body;
}

// ---------------------------------------------------------------- "Criar vídeo": create → confirm → run
// Um clique = consentimento explícito. Os três passos vão em sequência, com await; se um falhar, a tela continua aberta
// e mostra a mensagem do servidor (em português). 409 `already_started` no confirm/run = a mesma produção já começou
// (ex.: reenvio depois de uma resposta perdida): é sucesso, nunca um segundo envio.
export const FRIENDLY_FALLBACK = 'Não deu certo agora. Tente de novo em instantes.';
const friendly = (e) => {
  const m = (e && e.message) || '';
  return !m || /^HTTP \d+/.test(m) || /failed to fetch|network/i.test(m) ? FRIENDLY_FALLBACK : m;
};

export async function continueFal(post, pid, cc) {
  try { await post(`/api/productions/${pid}/confirm`, cc > 0 ? { total_cc: cc } : {}); } catch (e) {
    if (e && e.code === 'already_started') return { ok: true, pid, already: true };
    return { ok: false, pid, step: 'confirm', error: friendly(e) };
  }
  try { await post(`/api/productions/${pid}/run`, {}); } catch (e) {
    if (e && e.code === 'already_started') return { ok: true, pid, already: true };
    return { ok: false, pid, step: 'run', error: friendly(e) };
  }
  return { ok: true, pid };
}

export async function startFal(post, { body, cc }) {
  let pid;
  try { pid = (await post('/api/productions', body)).pid; } catch (e) { return { ok: false, pid: null, step: 'create', error: friendly(e) }; }
  return continueFal(post, pid, cc);
}

// Preço do botão "Criar vídeo · N créditos": o mesmo pré-orçamento que o servidor reserva e confere no /confirm.
export function offerFor(S, styleId) {
  const o = ((S && S.settings && S.settings.fal_styles) || []).find((x) => x.id === styleId);
  return o ? { cc: o.cc || 0, credits: o.credits || '0' } : { cc: 0, credits: '0' };
}
export const createLabel = (offer, demo) => (demo || !offer.cc ? 'Criar vídeo' : `Criar vídeo · ${offer.credits} créditos`);
export const RECEIVE_LINE = 'Você recebe: vídeo ~15 s com narração, 1 foto, título e legenda. Se falhar por erro técnico, não é cobrado.';

// ---------------------------------------------------------------- esteira (ESTIMATIVA por tempo)
// A fal só informa IN_QUEUE / IN_PROGRESS / COMPLETED. O avanço por etapa abaixo é uma ESTIMATIVA pelo tempo decorrido
// desde o envio (EST_WORKFLOW_S), só para a esteira ter vida. Nunca passa de REVISÃO enquanto o workflow roda, e
// EDIÇÃO só fica concluída com a entrega baixada e validada (servidor em awaiting_final_review/completed).
export const FAL_STEPS = [
  { id: 'planejamento', title: 'PLANEJAMENTO', label: 'Planejamento', agent: 'nina' },
  { id: 'roteiro', title: 'ROTEIRO', label: 'Roteiro', agent: 'theo' },
  { id: 'imagens', title: 'IMAGENS', label: 'Imagens', agent: 'iris' },
  { id: 'videos', title: 'VÍDEOS', label: 'Vídeos', agent: 'lia' },
  { id: 'revisao', title: 'REVISÃO', label: 'Revisão', agent: 'rui' },
  { id: 'edicao', title: 'EDIÇÃO', label: 'Edição', agent: 'beto' },
];
export const EST_WORKFLOW_S = 180;          // ESTIMATIVA da duração do workflow (não vem da fal)
const EST_CUTS = [0.12, 0.35, 0.85];         // ESTIMATIVA: roteiro → imagens → vídeos → revisão (fração de EST_WORKFLOW_S)

const isRunning = (P) => !!P.running || ['producing', 'editing'].includes(P.status);
const notStarted = (P) => ['received', 'awaiting_references', 'validated', 'scripted'].includes(P.status) && !P.running;

// Índice da etapa atual (0..5), 6 = tudo pronto, null = ainda não começou. `now` em ms (testável).
export function falStepIndex(P, now = Date.now()) {
  if (!isFalProduction(P)) return null;
  if (P.status === 'awaiting_final_review' || P.status === 'completed') return 6;
  if (P.status === 'editing') return 5;
  const f = P.fal || {};
  if (notStarted(P) && !f.submitted_at) return null;
  const sent = f.submitted_at ? Date.parse(f.submitted_at) : NaN;
  if (!Number.isFinite(sent) || f.remote_status === 'IN_QUEUE') return 0;
  const frac = Math.max(0, (now - sent) / 1000) / EST_WORKFLOW_S;
  return 1 + EST_CUTS.filter((c) => frac >= c).length;          // 1..4: nunca EDIÇÃO só pelo tempo
}

export function falProgress(P, now = Date.now()) {
  const i = falStepIndex(P, now);
  if (i === null) return 0;
  if (i >= 6) return 100;
  if (i === 5) return 95;
  if (i === 0) return 4;
  const f = P.fal || {};
  const frac = Math.max(0, (now - Date.parse(f.submitted_at)) / 1000) / EST_WORKFLOW_S;
  return Math.round(8 + Math.min(frac, 1) * 82);                // até 90%: o resto é a entrega validada
}

// Estado mostrado ao cliente, SEMPRE derivado do servidor. Nada de "Preparando"/"Criando" antes do /run aceito.
// kind: waiting | running | limit | finalizing | paused | failed | cancelled | partial | done
export function falStatus(P, now = Date.now()) {
  if (!isFalProduction(P)) return null;
  const f = P.fal || {};
  const ended = endedOfStatus(P);
  if (ended === 'failed') return { kind: 'failed', label: 'Não deu certo', text: 'Não deu certo. Nada foi cobrado.' };
  if (ended === 'cancelled') return incompleteDelivery(P)
    ? { kind: 'partial', label: 'Entrega parcial', text: 'A foto não ficou pronta e a missão foi encerrada. Nada mais é cobrado.' }
    : { kind: 'cancelled', label: 'Cancelada', text: 'Missão cancelada. Nada mais é gerado nem cobrado.' };
  if (P.status === 'completed') return { kind: 'done', label: 'Pronto', text: 'Pronto e exportado.' };
  if (P.status === 'awaiting_final_review') return { kind: 'done', label: 'Pronto', text: 'Seu vídeo está pronto.' };
  if (P.status === 'paused') {
    const code = P.pause_code || '';
    if (code === 'monthly_cap') return { kind: 'limit', label: 'Pausada: limite mensal atingido', text: 'Nada foi cobrado. A missão continua quando o limite for renovado.' };
    if (code === 'credits_insufficient') return { kind: 'limit', label: 'Pausada: saldo insuficiente', text: 'Nada foi cobrado. Adicione créditos para continuar.' };
    if (code.startsWith('paid_gate')) return { kind: 'limit', label: 'Pausada', text: P.reason || 'A geração está pausada no momento. Nada foi cobrado.' };
    if (f.finalizing) return { kind: 'finalizing', label: 'Em finalização', text: FINAL_FINALIZING };
    return { kind: 'paused', label: 'Pausada', text: P.reason || 'A missão pausou.' };
  }
  if (P.status === 'awaiting_references') return { kind: 'waiting', label: 'Aguardando você', text: P.reason || 'Envie outra foto do produto.', action: null };
  if (notStarted(P)) return { kind: 'waiting', label: 'Aguardando você', text: 'O vídeo ainda não começou. Nada foi cobrado.', action: 'start' };
  if (isRunning(P)) {
    const i = falStepIndex(P, now);
    const step = FAL_STEPS[Math.min(i === null ? 0 : i, 5)];
    return { kind: 'running', label: step.label, step: step.id, estimated: i !== 5,
      text: 'Estamos criando seu vídeo. Pode sair desta tela: avisamos quando terminar.' };
  }
  return { kind: 'waiting', label: 'Aguardando você', text: 'O vídeo ainda não começou. Nada foi cobrado.', action: 'start' };
}

// Estações da esteira (mesmo formato que o Conveyor desenha). `tab` vazio: a missão fal não tem janelas por etapa.
export function falStations(P, now = Date.now()) {
  const st = falStatus(P, now);
  const i = falStepIndex(P, now);
  const where = i === null ? -1 : Math.min(i, 6);
  const stations = FAL_STEPS.map((s, k) => {
    let state = k < where ? 'done' : k === where ? 'active' : 'pending';
    if (where === 6) state = 'done';
    return { id: s.id, agent: s.agent, title: s.title, tab: null, state, detail: '', current: false };
  });
  const at = stations[Math.max(0, Math.min(where, 5))];
  if (st && (st.kind === 'failed' || st.kind === 'cancelled' || st.kind === 'partial')) {
    stations.forEach((s) => { if (s.state === 'active') s.state = 'pending'; });
    if (at.state !== 'done') at.state = st.kind === 'failed' ? 'problem' : 'cancelled';
  } else if (st && ['limit', 'finalizing', 'paused'].includes(st.kind) && at.state !== 'done') at.state = 'problem';
  else if (st && st.kind === 'waiting') { stations.forEach((s) => { s.state = 'pending'; }); stations[0].state = 'need'; }
  const LBL = { pending: 'Pendente', active: 'Em andamento', need: 'Aguardando você', done: 'Concluída', problem: st && st.kind === 'failed' ? 'Falhou' : 'Pausada', cancelled: 'Cancelada', ended: 'Interrompida' };
  stations.forEach((s) => { s.label = LBL[s.state]; });
  if (at.state === 'active' && st && st.estimated) at.detail = 'etapa estimada';
  const cur = stations.find((s) => ['active', 'need', 'problem', 'cancelled'].includes(s.state));
  if (cur) cur.current = true;
  return { stations, progress: falProgress(P, now), current: cur ? cur.id : null, status: st };
}

// Status por agente para o Escritório e a equipe (o agente da etapa atual trabalha; "Aguardando você" chama a Nina).
export function falAgentStatus(P, now = Date.now()) {
  const out = {}; FAL_STEPS.forEach((s) => { out[s.agent] = 'idle'; });
  if (!isFalProduction(P)) return out;
  const b = falStations(P, now);
  const cur = b.stations.find((s) => s.current);
  if (cur && cur.state === 'active') out[cur.agent] = 'work';
  if (cur && cur.state === 'need') out[cur.agent] = 'need';
  if (b.status && b.status.kind === 'done' && P.status === 'awaiting_final_review') out.beto = 'need';
  return out;
}

// Entrega: vídeo + 1 foto (hero) + título e legenda copiáveis. Só o que existe tem link.
// Missão encerrada com a entrega incompleta (a foto não ficou pronta) mostra "Entrega parcial", não "Missão cancelada".
export const endedLabel = (P) => (isFalProduction(P) && endedOfStatus(P) === 'cancelled' && incompleteDelivery(P) ? 'Entrega parcial' : null);
const endedOfStatus = (P) => P.ended || (P.status === 'cancelled' || P.status === 'failed' ? P.status : null);
export function downloadUrl(url) { return url ? url + (url.includes('?') ? '&' : '?') + 'download=1' : null; }
export function gallery(P) {
  if (!isFalProduction(P)) return null;
  const d = P.delivery || {}, f = P.fal || {};
  return {
    video: d['final.mp4'] ? { url: d['final.mp4'], download: downloadUrl(d['final.mp4']), name: 'final.mp4' } : null,
    cover: d['cover.jpg'] || null,
    image: f.image ? { role: f.image.role, label: f.image.label, url: f.image.url, download: downloadUrl(f.image.url), name: f.image.file } : null,
    partial: f.delivery_status === 'partial', missing: f.missing_images || [],
    title: f.title || '', caption: f.caption || '', textMissing: !f.title && !f.caption, warnings: f.warnings || [],
    captionFile: d['caption.txt'] ? { download: downloadUrl(d['caption.txt']) } : null,
  };
}

// Linhas do "Seu próximo vídeo" no motor fal.ai (o resumo do servidor traz engine/style).
export function falSummaryRows(sm, credits) {
  const rows = [['Produto', sm.product || 'A partir da sua foto'], ['Estilo', (STYLES.find((s) => s.id === sm.style) || {}).label || '—'],
    ['O que você recebe', 'Vídeo de ~15 s (vertical, com narração) + 1 foto publicitária + título e legenda'],
    ['Custo total autorizado', credits(sm.total_credits) + (sm.total_brl ? ` (≈ R$ ${sm.total_brl})` : '')],
    ['Saldo atual', sm.exempt ? 'Conta isenta' : credits(sm.balance)]];
  if (!sm.exempt) rows.push(['Saldo depois de reservar', credits(sm.balance_after)]);
  return rows;
}
