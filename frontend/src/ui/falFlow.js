// Fluxo do motor fal.ai: 1 foto + estilo (Escuro/Claro) → pacote de 4 arquivos. Lógica pura (tests/falflow.test.mjs).
// Só aparece quando o servidor diz `settings.video_engine === 'fal'` ou a produção aberta é `engine === 'fal'`.

export const STYLES = [
  { id: 'dark', label: 'Escuro', hint: 'Cinematográfico: iluminação dramática, cenário premium e apresentação de impacto.' },
  { id: 'light', label: 'Claro', hint: 'Lifestyle: ambientes residenciais claros, luz natural e fundo predominantemente branco.' },
];
export const FINAL_FINALIZING = 'Estamos finalizando o seu pacote. Avisaremos quando estiver pronto.';
export const IMAGE_EXT = /\.(jpe?g|png|webp)$/i;

export const isFalProduction = (P) => !!(P && P.engine === 'fal');
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

// Estado mostrado ao cliente. Detalhe técnico (pausas, códigos) nunca aparece: pausa de entrega = "em finalização".
export function falView(P) {
  if (!isFalProduction(P)) return null;
  const f = P.fal || {};
  const ended = P.ended || (P.status === 'cancelled' || P.status === 'failed' ? P.status : null);
  let phase = 'creating';
  if (ended === 'cancelled') phase = 'cancelled';
  else if (ended === 'failed') phase = 'failed';
  else if (P.status === 'completed') phase = 'done';
  else if (P.status === 'awaiting_final_review') phase = 'ready';
  else if (f.finalizing) phase = 'finalizing';
  else if (P.status === 'paused') phase = 'paused';
  else if (P.status === 'editing') phase = 'composing';
  else if (P.status === 'producing') phase = f.remote_status === 'IN_QUEUE' ? 'queued' : 'working';
  const LABEL = { creating: 'Preparando a foto', queued: 'Na fila', working: 'Criando o vídeo e as fotos', composing: 'Montando o vídeo final',
    ready: 'Pacote pronto', done: 'Exportado', finalizing: 'Em finalização', paused: 'Pausado', failed: 'Não foi possível gerar', cancelled: 'Cancelada' };
  return { phase, label: LABEL[phase], styleLabel: f.style_label || '', finalizing: phase === 'finalizing',
    queuePosition: phase === 'queued' && Number.isFinite(f.queue_position) ? f.queue_position : null, busy: ['creating', 'queued', 'working', 'composing'].includes(phase) };
}

// Galeria: vídeo principal + 3 fotos com rótulo e download por item. Só o que existe tem link.
export function downloadUrl(url) { return url ? url + (url.includes('?') ? '&' : '?') + 'download=1' : null; }
export function gallery(P) {
  if (!isFalProduction(P)) return null;
  const d = P.delivery || {}, f = P.fal || {};
  return {
    video: d['final.mp4'] ? { url: d['final.mp4'], download: downloadUrl(d['final.mp4']), name: 'final.mp4' } : null,
    cover: d['cover.jpg'] || null,
    images: (f.images || []).map((i) => ({ role: i.role, label: i.label, url: i.url, download: downloadUrl(i.url), name: i.file })),
    partial: f.delivery_status === 'partial', missing: f.missing_images || [],
    description: f.description || '', narrationText: f.narration_text || '', warnings: f.warnings || [],
    caption: d['caption.txt'] ? { download: downloadUrl(d['caption.txt']) } : null,
  };
}

// Linhas do "Seu próximo vídeo" no motor fal.ai (o resumo do servidor traz engine/style).
export function falSummaryRows(sm, credits) {
  const rows = [['Produto', sm.product || 'A partir da sua foto'], ['Estilo', (STYLES.find((s) => s.id === sm.style) || {}).label || '—'],
    ['O que você recebe', 'Vídeo de ~15 s (vertical, com narração e trilha) + 3 fotos publicitárias'],
    ['Custo total autorizado', credits(sm.total_credits) + (sm.total_brl ? ` (≈ R$ ${sm.total_brl})` : '')],
    ['Saldo atual', sm.exempt ? 'Conta isenta' : credits(sm.balance)]];
  if (!sm.exempt) rows.push(['Saldo depois de reservar', credits(sm.balance_after)]);
  return rows;
}
