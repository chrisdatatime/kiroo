// Esteira de agentes: lógica pura da transição (o "salto" da tarefa entre estações), do texto para leitor de tela
// e dos créditos por etapa. Sem React: testável em Node (tests/conveyor.test.mjs). As estações vêm de pipeline.js.
import { fmtCc } from '../ui/credits.js';

export const HOP_MS = 900;   // duração do salto (CSS usa o mesmo valor em --hop-ms)
const live = (s) => s === 'active' || s === 'need';

// Compara o snapshot anterior com o atual da MESMA missão. Devolve { from, to } quando uma estação deixou de estar
// viva (concluiu ou passou a bola) e outra passou a trabalhar/esperar você; null no primeiro desenho (sem anterior),
// em missão encerrada/pausada (nada se move) e quando nada mudou. Abrir a tela depois mostra só o estado final.
export function hopBetween(prev, next) {
  if (!prev || !next || prev.length !== next.length) return null;
  if (next.some((s) => s.state === 'cancelled' || s.state === 'problem' || s.state === 'ended')) return null;
  const was = Object.fromEntries(prev.map((s) => [s.id, s.state]));
  const from = next.find((s) => live(was[s.id]) && !live(s.state));
  if (!from) return null;
  const i = next.indexOf(from);
  const to = next.find((s) => live(s.state) && !live(was[s.id])) || next.slice(i + 1).find((s) => live(s.state));
  return to && to.id !== from.id ? { from: from.id, to: to.id } : null;
}

// O salto só acontece com movimento permitido e com snapshot anterior da mesma missão.
export function shouldHop({ reduced, prevKey, key, prev, next }) {
  if (reduced || prevKey !== key) return null;
  return hopBetween(prev, next);
}

// Posição do salto: centro das duas estações em relação à faixa (px). Puro: recebe medidas, não o DOM.
export function hopGeometry(from, to) {
  if (!from || !to) return null;
  return { x0: from.left + from.width / 2, x1: to.left + to.width / 2 };
}

// Ícone genérico da tarefa quando não há miniatura: o que cada estação entrega.
export const TASK_ICON = { produto: 'box', direcao: 'edit', imagens: 'image', revisao: 'shield', videos: 'video', entrega: 'box' };

// Miniatura da tarefa que sai da estação: a última imagem/take aprovado, quando existe. Senão null (ícone genérico).
export function taskThumb(station, { imgSlots = [], vidSlots = [] } = {}) {
  const last = (list) => list.filter((x) => x.status === 'aprovada' && x.url).slice(-1)[0];
  if (station === 'imagens') { const s = last(imgSlots); return s ? { url: s.url, video: false } : null; }
  if (station === 'videos') { const s = last(vidSlots); return s ? { url: s.url, video: true } : null; }
  return null;
}

// Rótulo completo da estação (botão e leitor de tela): "Iris, Imagens: Em andamento. Criando cena 2."
export function stationAria(s, name) {
  const now = s.detail && s.detail !== s.label ? ' ' + s.detail + '.' : '';
  return `${name}, ${s.title}: ${s.label}.${now}${s.state === 'need' ? ' Abrir para decidir.' : ''}`;
}

// Créditos já usados por estação, a partir do consumo real do extrato (/api/credits → usage[].stages).
// O extrato rotula as operações; só o que tem estação conhecida entra. Sem dado: objeto vazio (nada é inventado).
export const LEDGER_STATION = { Imagens: 'imagens', 'Vídeos': 'videos', 'Conferência das imagens': 'revisao',
  'Conferência dos takes': 'revisao', 'Direção (roteiro)': 'direcao' };
export function creditsByStation(usage, pid) {
  const u = (usage || []).find((x) => x.production_id === pid);
  if (!u) return {};
  const cc = {};
  for (const s of u.stages || []) {
    const id = LEDGER_STATION[s.stage];
    if (id && Number(s.cc) > 0) cc[id] = (cc[id] || 0) + Number(s.cc);
  }
  return Object.fromEntries(Object.entries(cc).map(([id, v]) => [id, fmtCc(v)]));
}
