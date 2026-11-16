// Tela inicial ("Início"): lógica pura, sem React (tests/inicio.test.mjs).
// Tudo vem de dados reais do estado: produções (/api/state), saldo (account/credits), oferta (settings.fal_offer), bônus (account.welcome).
// Nada de custo, saldo, bônus ou tempo escrito aqui: sem dado, a frase some ou cai no texto neutro.
import { EST_WORKFLOW_S } from '../ui/falBelt.js';

// ---------------------------------------------------------------- status da produção → rótulo da tela
// tone: need (laranja) | work (azul) | done (verde) | sent (cinza-azulado) | off (cinza) | bad (vermelho)
// Os status vêm do servidor (ProductionStatus); nenhum status novo.
export const STATUS_VIEW = {
  aprovacao: { key: 'aprovacao', label: 'Aguardando aprovação', tone: 'need', action: 'Assistir e aprovar', needsYou: true },
  decisao: { key: 'decisao', label: 'Aguardando você', tone: 'need', action: 'Resolver', needsYou: true },
  gerando: { key: 'gerando', label: 'Gerando', tone: 'work', action: 'Acompanhar', needsYou: false },
  pronto: { key: 'pronto', label: 'Pronto', tone: 'done', action: 'Baixar', needsYou: false },
  baixado: { key: 'baixado', label: 'Baixado', tone: 'sent', action: 'Abrir', needsYou: false },
  cancelado: { key: 'cancelado', label: 'Cancelado', tone: 'off', action: 'Abrir', needsYou: false },
  erro: { key: 'erro', label: 'Erro', tone: 'bad', action: 'Ver detalhes', needsYou: false },
};
export const ERROR_NOTE = 'Se foi erro técnico, não cobramos.';

const FAL_IDLE = ['received', 'validated', 'scripted'];
// Produção fal parada antes do /run espera você (mesma regra de missionWord em ui/mobile.js).
export function statusOf(p) {
  if (!p) return STATUS_VIEW.gerando;
  const st = p.ended || p.status;
  if (st === 'failed') return STATUS_VIEW.erro;
  if (st === 'cancelled') return STATUS_VIEW.cancelado;
  if (st === 'awaiting_final_review') return STATUS_VIEW.aprovacao;
  if (st === 'completed') return p.downloaded ? STATUS_VIEW.baixado : STATUS_VIEW.pronto;   // o servidor não informa download: `downloaded` só existe se um dia vier
  if (st === 'paused' || st === 'awaiting_references') return STATUS_VIEW.decisao;
  if (p.engine === 'fal' && FAL_IDLE.includes(st) && !p.running) return STATUS_VIEW.decisao;
  return STATUS_VIEW.gerando;
}

// ---------------------------------------------------------------- nome do produto (nunca o id cru)
const RAW_ID = /^(prod|p|pid)[_-][0-9a-f]{6,}$/i;
const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
const pad = (n) => String(n).padStart(2, '0');
const toDate = (iso) => { const d = iso ? new Date(iso) : null; return d && !Number.isNaN(d.getTime()) ? d : null; };
export const dayHour = (d) => `${pad(d.getDate())}/${pad(d.getMonth() + 1)}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;

// 1) nome do produto; 2) título gerado pela IA (só a produção aberta o traz); 3) "Produção de DD/MM, HH:mm".
export function productName(p, aiTitle = '') {
  const own = clean(p && p.name);
  if (own && !RAW_ID.test(own) && own !== (p && p.id)) return own;
  const ai = clean(aiTitle);
  if (ai && !RAW_ID.test(ai)) return ai;
  const d = toDate(p && p.created_at);
  return d ? `Produção de ${dayHour(d)}` : 'Produção sem nome';
}

// ---------------------------------------------------------------- datas
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
export function relativeDate(iso, now = new Date()) {
  const d = toDate(iso); if (!d) return '';
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (sameDay(d, now)) return `Hoje, ${hm}`;
  const y = new Date(now); y.setDate(y.getDate() - 1);
  if (sameDay(d, y)) return `Ontem, ${hm}`;
  return dayHour(d);
}
export function agoLabel(iso, now = new Date()) {
  const d = toDate(iso); if (!d) return '';
  const min = Math.max(0, Math.round((now - d) / 60000));
  if (min < 1) return 'agora';
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  const days = Math.floor(h / 24);
  return `há ${days} ${days === 1 ? 'dia' : 'dias'}`;
}

// ---------------------------------------------------------------- saudação e resumo
export function greeting(date = new Date()) {
  const h = date.getHours();
  return h >= 5 && h < 12 ? 'Bom dia' : h >= 12 && h < 18 ? 'Boa tarde' : 'Boa noite';   // madrugada = Boa noite
}
export const firstName = (user) => clean((user && user.name) || '').split(' ')[0];

const join = (parts) => (parts.length < 2 ? parts[0] || '' : parts.slice(0, -1).join(', ') + ' e ' + parts[parts.length - 1]);
export function countsOf(productions) {
  const c = { aprovacao: 0, decisao: 0, gerando: 0, pronto: 0, baixado: 0, cancelado: 0, erro: 0 };
  (productions || []).forEach((p) => { c[statusOf(p).key] += 1; });
  return c;
}
// Sem produções: null (a tela oculta a frase). Sem pendência nem andamento: "Tudo em dia."
export function summaryLine(productions) {
  if (!productions || productions.length === 0) return null;
  const c = countsOf(productions);
  const parts = [];
  if (c.aprovacao) parts.push(`${c.aprovacao} ${c.aprovacao === 1 ? 'vídeo espera' : 'vídeos esperam'} sua aprovação`);
  if (c.decisao) parts.push(`${c.decisao} ${c.decisao === 1 ? 'produção precisa' : 'produções precisam'} de você`);
  if (c.gerando) parts.push(`${c.gerando} ${c.gerando === 1 ? 'está sendo produzido' : 'estão sendo produzidos'}`);
  return parts.length ? `${join(parts)}.` : 'Tudo em dia.';
}

// ---------------------------------------------------------------- "precisa de você"
// A mais antiga primeiro; `extra` alimenta o link "+N aguardando".
export function needsYou(productions) {
  const list = (productions || []).filter((p) => statusOf(p).needsYou)
    .sort((a, b) => (toDate(a.created_at) || 0) - (toDate(b.created_at) || 0));
  return { first: list[0] || null, extra: Math.max(0, list.length - 1), total: list.length };
}

// ---------------------------------------------------------------- filtros da tabela
export const FILTERS = [
  { id: 'todas', label: 'Todas' }, { id: 'andamento', label: 'Em andamento' },
  { id: 'prontas', label: 'Prontas' }, { id: 'baixadas', label: 'Baixadas' },
];
const FILTER_KEYS = { andamento: ['gerando', 'decisao'], prontas: ['aprovacao', 'pronto'], baixadas: ['baixado'] };
export function filterProductions(list, filter) {
  const keys = FILTER_KEYS[filter];
  return keys ? (list || []).filter((p) => keys.includes(statusOf(p).key)) : (list || []);
}
export function filterCounts(list) {
  const out = {}; FILTERS.forEach((f) => { out[f.id] = filterProductions(list, f.id).length; });
  return out;
}
export const TABLE_ROWS = 5;

// ---------------------------------------------------------------- saldo
// "Dá para ≈ N vídeos" = floor(saldo / custo do vídeo). O custo vem de settings.fal_offer (em centésimos, como o livro);
// no DEMO o servidor manda cc 0 e a frase some (sem custo real não há conta a fazer). Conta isenta também não mostra.
export function videosLeft(wallet, offer) {
  const cost = Number(offer && offer.cc) || 0;
  const bal = Number(wallet && wallet.balance_cc);
  if (!wallet || wallet.exempt || cost <= 0 || !Number.isFinite(bal)) return null;
  return Math.max(0, Math.floor(bal / cost));
}
export const videosLine = (n) => (n == null ? '' : `Dá para ≈ ${n} ${n === 1 ? 'vídeo' : 'vídeos'}`);
// Barra do saldo: contra o bônus real da conta (account.welcome.credits, em créditos inteiros). Sem referência, sem barra.
export function balanceRatio(wallet, welcome) {
  const ref = Number(welcome && welcome.credits) * 100, bal = Number(wallet && wallet.balance_cc);
  if (!(ref > 0) || !Number.isFinite(bal)) return null;
  return Math.max(0, Math.min(1, bal / ref));
}

// Tempo estimado: constante de configuração do app (falBelt.EST_WORKFLOW_S). Sem base: "poucos minutos".
export function estimateLabel(seconds = EST_WORKFLOW_S) {
  const s = Number(seconds);
  if (!(s > 0)) return 'poucos minutos';
  return `cerca de ${Math.max(1, Math.round(s / 60))} min`;
}

// ---------------------------------------------------------------- primeiro acesso
export function firstSteps({ account, productions }) {
  const list = productions || [];
  const verified = !!(account && account.user && account.user.email_verified);
  const steps = [
    { id: 'email', label: 'Confirmar e-mail', hint: 'Para receber o aviso quando o vídeo ficar pronto.', done: verified },
    { id: 'video', label: 'Criar o primeiro vídeo', hint: 'Envie a foto do produto e escolha o cenário.', done: list.length > 0 },
    { id: 'publish', label: 'Baixar e publicar', hint: 'Baixe o vídeo, o título e a legenda.', done: list.some((p) => ['pronto', 'baixado'].includes(statusOf(p).key) && (p.status === 'completed')) },
  ];
  return { steps, done: steps.filter((s) => s.done).length, total: steps.length, all: steps.every((s) => s.done) };
}
export const stepsVisible = (fs, productions) => !fs.all && (productions || []).length <= 2;
// "Como funciona": 0 a 2 produções, e nunca junto com "Primeiros passos".
export const showHowItWorks = (productions, stepsShown) => (productions || []).length <= 2 && !stepsShown;
export const showWelcome = (productions) => (productions || []).length === 0;

// ---------------------------------------------------------------- equipe
// Quem espera o usuário (status 'need' do estado real dos agentes).
export function teamSummary(team, statuses) {
  const waiting = (team || []).filter((a) => (statuses || {})[a.id] === 'need');
  const busy = (team || []).filter((a) => (statuses || {})[a.id] === 'work').length;
  const line = waiting.length ? `${waiting[0].name} espera você` : '';
  const status = waiting.length ? `${waiting.length} ${waiting.length === 1 ? 'espera' : 'esperam'} você` : busy ? 'Trabalhando' : 'Livre para produzir';
  return { waiting, busy, line, status, count: (team || []).length };
}

// Miniatura: foto do produto (só a produção aberta a traz) → cenário escolhido → nada.
export function thumbOf(p, photoUrl, sceneThumb) {
  if (p && p.current && photoUrl) return photoUrl;
  return p && p.scene ? sceneThumb(p.scene) : null;
}
