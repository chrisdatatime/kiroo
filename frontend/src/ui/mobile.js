// Celular (<= 640 px): lógica pura da interface mobile-first (tests/mobile.test.mjs). Sem React.
// O layout de celular troca a lateral pela barra inferior, abre a Nova produção em tela cheia, desenha a esteira na
// vertical e simplifica o Escritório. Nada aqui muda o desktop.

export const PHONE_MAX = 640;
export const PHONE_MQ = `(max-width: ${PHONE_MAX}px)`;

// Status da missão em UMA palavra, com tom (cor + texto: o estado nunca depende só da cor).
// tone: done | work | need | warn | bad | off
const WORD = {
  received: ['Criando', 'work'], validated: ['Criando', 'work'], scripted: ['Criando', 'work'], producing: ['Criando', 'work'], editing: ['Criando', 'work'],
  awaiting_references: ['Aguardando', 'need'], awaiting_final_review: ['Pronto', 'done'], completed: ['Exportado', 'done'],
  paused: ['Pausada', 'warn'], failed: ['Falhou', 'bad'], cancelled: ['Cancelada', 'off'],
};
// Missão fal parada antes do /run (recebido/validado) está esperando você, não criando. `live` = falStatus(P).kind da
// missão aberta (estado real do servidor), quando existe: vence o resumo da lista.
const LIVE = { waiting: ['Aguardando', 'need'], running: ['Criando', 'work'], finalizing: ['Criando', 'work'], limit: ['Pausada', 'warn'], paused: ['Pausada', 'warn'],
  failed: ['Falhou', 'bad'], cancelled: ['Cancelada', 'off'], partial: ['Parcial', 'warn'], done: ['Pronto', 'done'] };
const FAL_IDLE = ['received', 'validated', 'scripted'];
export function missionWord(p, live = null) {
  if (!p) return { word: '—', tone: 'off' };
  if (p.ended === 'cancelled' || p.ended === 'failed') return missionWord({ status: p.ended });
  if (live && LIVE[live]) return live === 'done' && p.status === 'completed' ? missionWord({ status: 'completed' }) : { word: LIVE[live][0], tone: LIVE[live][1] };
  if (p.engine === 'fal' && FAL_IDLE.includes(p.status)) return { word: 'Aguardando', tone: 'need' };
  const w = WORD[p.status];
  return w ? { word: w[0], tone: w[1] } : { word: 'Aguardando', tone: 'need' };
}

// Preenchimento (0..100) da barra de cada etapa na esteira vertical, a partir do MESMO progresso geral da esteira do
// desktop (pipeline.progress / falProgress): concluída = 100, pendente = 0, atual = a fatia do progresso geral que cai
// no trecho dela, presa entre 6 e 94 para nunca parecer vazia nem pronta antes da hora. `bounds` = [[de, até], ...] por
// etapa (fal: FAL_STEP_BOUNDS, a mesma curva de falProgress); sem ele, trechos iguais.
export function stepFills(stations, progress, bounds = null) {
  const n = stations.length || 1;
  const p = Math.max(0, Math.min(100, Number(progress) || 0));
  return stations.map((s, k) => {
    if (s.state === 'done') return 100;
    if (s.state === 'pending') return 0;
    if (s.state === 'active') {
      const [lo, hi] = bounds && bounds[k] ? bounds[k] : [(k * 100) / n, ((k + 1) * 100) / n];
      return Math.round(Math.max(6, Math.min(94, ((p - lo) / (hi - lo)) * 100)));
    }
    return s.current ? 100 : 0;   // aguardando você / pausada / cancelada: barra cheia na cor do estado (só a atual)
  });
}

// Foto vinda da câmera/galeria do celular: alguns aparelhos entregam o arquivo sem extensão. Se o tipo é JPG/PNG/WEBP,
// completa o nome; senão devolve o nome como veio (a validação de sempre recusa).
const EXT_OF = { 'image/jpeg': '.jpg', 'image/jpg': '.jpg', 'image/png': '.png', 'image/webp': '.webp' };
export function normalizeImageName(name, type) {
  const n = (name || '').trim() || 'foto';
  if (/\.(jpe?g|png|webp)$/i.test(n)) return n;
  const ext = EXT_OF[(type || '').toLowerCase()];
  return ext ? n.replace(/\.[a-z0-9]{1,5}$/i, '') + ext : n;
}

// Web Share com arquivo: só quando o navegador diz que consegue compartilhar ESTE arquivo. Senão, download.
export function canShareFile(nav, file) {
  try { return !!(nav && typeof nav.share === 'function' && typeof nav.canShare === 'function' && file && nav.canShare({ files: [file] })); } catch { return false; }
}
// Pode valer a pena buscar o arquivo antes do toque (o iOS perde o "gesto do usuário" se o share esperar um download)?
export const shareSupported = (nav) => !!(nav && typeof nav.share === 'function' && typeof nav.canShare === 'function');

// O que fazer quando o share termina: cancelado pelo usuário = nada; outro erro = cair para o download.
export const shareFallback = (err) => !(err && err.name === 'AbortError');

// Nome do arquivo ao compartilhar/baixar: nome do produto "seguro" + papel.
export function shareName(product, role, ext) {
  const base = (product || 'kiroo').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '').toLowerCase().slice(0, 40) || 'kiroo';
  return `${base}-${role}${ext}`;
}
