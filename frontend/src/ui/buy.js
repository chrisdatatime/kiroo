// "Comprar créditos": lógica pura da tela (tests/credits.test.mjs). Sem React.
// O navegador só EXIBE preço: o valor cobrado é calculado pelo servidor a partir do catálogo (o pedido leva apenas o
// código do pacote ou a quantidade avulsa). As contas daqui espelham src/studio/catalog.py para a tela não mentir.

// 7990 → "R$ 79,90" (espaço inquebrável: o preço não quebra no meio da linha)
export function brl(cents) {
  const n = (Number(cents) || 0) / 100;
  return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// "Economize X%" contra o avulso (arredonda para baixo, como o servidor).
export function savingsPct(credits, priceCents, unitCents) {
  const full = credits * unitCents;
  if (full <= 0 || priceCents >= full) return 0;
  return Math.floor(((full - priceCents) * 100) / full);
}

export const videosFor = (credits, perVideo) => (perVideo > 0 ? Math.floor(credits / perVideo) : 0);

// ---------------------------------------------------------------- avulso
export function customValid(n, c) {
  return Number.isInteger(n) && n >= c.min_credits && n <= c.max_credits && n % c.step_credits === 0;
}

// Leva qualquer número ao valor válido mais próximo (dentro de mínimo..máximo, múltiplo do incremento).
export function clampCustom(n, c) {
  const v = Math.round((Number(n) || 0) / c.step_credits) * c.step_credits;
  return Math.min(Math.max(v, c.min_credits), c.max_credits);
}

export const stepCustom = (n, dir, c) => clampCustom(clampCustom(n, c) + dir * c.step_credits, c);

export const customTotalCents = (n, c) => (customValid(n, c) ? n * c.unit_price_cents : 0);

// Dica a partir de N créditos: o pacote indicado sai mais barato por crédito.
export function customHint(n, cat) {
  const c = cat && cat.custom;
  if (!c || !c.hint_from_credits || n < c.hint_from_credits) return null;
  const p = (cat.packages || []).find((x) => x.code === c.hint_package);
  return p ? `No pacote ${p.name}, ${p.credits} créditos saem por ${brl(p.price_cents)}.` : null;
}

// ---------------------------------------------------------------- CPF / CNPJ (o servidor valida de novo)
export const cleanDoc = (s) => String(s || '').replace(/[^0-9A-Za-z]/g, '').toUpperCase();

function cpfOk(d) {
  if (!/^\d{11}$/.test(d) || /^(\d)\1{10}$/.test(d)) return false;
  for (const n of [9, 10]) {
    let s = 0;
    for (let i = 0; i < n; i++) s += Number(d[i]) * (n + 1 - i);
    if (((s * 10) % 11) % 10 !== Number(d[n])) return false;
  }
  return true;
}

// CNPJ numérico ou alfanumérico (07/2026): valor de cada caractere = código − 48.
function cnpjOk(d) {
  if (!/^[0-9A-Z]{12}\d{2}$/.test(d) || /^(.)\1{13}$/.test(d)) return false;
  const v = [...d].map((ch) => ch.charCodeAt(0) - 48);
  for (const n of [12, 13]) {
    const w = [];
    for (let k = n - 7; k > 1; k--) w.push(k);
    for (let k = 9; k > 1; k--) w.push(k);
    const r = v.slice(0, n).reduce((acc, x, i) => acc + x * w[i], 0) % 11;
    if ((r < 2 ? 0 : 11 - r) !== v[n]) return false;
  }
  return true;
}

export function docValid(raw) {
  const d = cleanDoc(raw);
  return d.length === 11 ? cpfOk(d) : d.length === 14 ? cnpjOk(d) : false;
}

// Máscara enquanto digita: 000.000.000-00 (CPF) ou 00.000.000/0000-00 (CNPJ).
export function maskDoc(raw) {
  const d = cleanDoc(raw).slice(0, 14);
  if (d.length <= 11) return d.replace(/^(.{3})(.)/, '$1.$2').replace(/^(.{3}\..{3})(.)/, '$1.$2').replace(/^(.{3}\..{3}\..{3})(.)/, '$1-$2');
  return d.replace(/^(.{2})(.{3})(.{3})(.{4})(.{0,2}).*/, (m, a, b, c, e, f) => `${a}.${b}.${c}/${e}${f ? '-' + f : ''}`);
}

// ---------------------------------------------------------------- cartão: o mesmo limite que o servidor aplica
// Devolve o motivo de o cartão não estar disponível para este valor (ou null).
export function cardBlock(amountCents, card) {
  if (!card) return null;
  if (card.disputed) return 'Esta conta tem uma contestação de cartão: compras só por Pix.';
  if (card.new_account && card.count_today >= 1) return 'Conta nova: 1 compra no cartão por dia. Use Pix ou tente amanhã.';
  if (amountCents > card.max_cents) {
    return card.new_account ? 'Conta nova: no cartão, o limite é o pacote Pro. Use Pix para valores maiores.'
      : `Passa do limite diário de ${brl(card.daily_limit_cents)} no cartão. Use Pix ou tente amanhã.`;
  }
  return null;
}

// ---------------------------------------------------------------- status da compra
const STATUS = {
  creating: ['Gerando a cobrança…', 'wait'], pending: ['Aguardando pagamento', 'wait'], paid: ['Pagamento confirmado', 'ok'],
  expired: ['Cobrança vencida', 'off'], canceled: ['Cobrança cancelada', 'off'], failed: ['Não foi possível gerar a cobrança', 'bad'],
  refunded: ['Compra estornada', 'off'], chargeback: ['Compra contestada', 'bad'], mismatch: ['Pagamento em análise pela equipe', 'bad'],
};
export const statusOf = (s) => { const x = STATUS[s] || STATUS.pending; return { label: x[0], tone: x[1] }; };
export const isFinal = (s) => s !== 'creating' && s !== 'pending';

// Pedido enviado ao servidor: só escolha, nunca valor.
export function checkoutBody({ tab, pkg, custom, method, doc }) {
  const body = { method };
  if (tab === 'pacotes') body.package = pkg; else body.credits = custom;
  if (doc) body.document = cleanDoc(doc);
  return body;
}

// ---------------------------------------------------------------- tela v2: cards de plano (Free + pacotes)
// `cat.plan` vem do servidor: {plan: free|inicial|pro|escala, has_purchase}. Plano = maior pacote PAGO (estorno recalcula).
// Free só aparece para conta sem compra paga (e é o "plano atual" dela). O card do plano atual pago ganha a etiqueta
// "Seu plano atual" e o botão "Comprar de novo". "Mais escolhido" fica no pacote em destaque (Pro), exceto se ele for o
// plano atual.
export const DEFAULT_PACK = 'pro';

export function planCards(cat) {
  const plan = (cat && cat.plan) || { plan: 'free', has_purchase: false };
  const current = plan.plan || 'free';
  const showFree = !plan.has_purchase;
  const paid = ((cat && cat.packages) || []).map((p) => ({
    ...p, kind: 'paid', current: p.code === current,
    badge: p.highlight && p.code !== current ? 'Mais escolhido' : null,
  }));
  const free = cat && cat.free ? { ...cat.free, code: 'free', kind: 'free', current: true, badge: null } : null;
  return { cards: showFree && free ? [free, ...paid] : paid, current, showFree: !!(showFree && free) };
}

// Pacote selecionado ao abrir: o Pro (ou o destaque do catálogo, ou o primeiro).
export function defaultSelection(cat) {
  const ps = (cat && cat.packages) || [];
  if (ps.some((p) => p.code === DEFAULT_PACK)) return DEFAULT_PACK;
  const hl = ps.find((p) => p.highlight);
  return hl ? hl.code : (ps[0] ? ps[0].code : null);
}

// Texto do botão de cada card pago.
export function buyLabel(card, selected) {
  if (card.current) return 'Comprar de novo';
  return selected ? `Comprar ${card.name}` : 'Comprar';
}

// Setas no grupo de rádios (só os pagos): direita/baixo = próximo, esquerda/cima = anterior (com volta), Home/End.
export function moveSelection(codes, cur, key) {
  const n = codes.length;
  if (!n) return cur;
  const i = Math.max(codes.indexOf(cur), 0);
  if (key === 'ArrowRight' || key === 'ArrowDown') return codes[(i + 1) % n];
  if (key === 'ArrowLeft' || key === 'ArrowUp') return codes[(i - 1 + n) % n];
  if (key === 'Home') return codes[0];
  if (key === 'End') return codes[n - 1];
  return cur;
}

// Celular: Pro primeiro, depois os outros pagos na ordem do catálogo, Free por último.
export function phoneOrder(cards) {
  const pro = cards.filter((c) => c.code === DEFAULT_PACK);
  const rest = cards.filter((c) => c.kind === 'paid' && c.code !== DEFAULT_PACK);
  const free = cards.filter((c) => c.kind === 'free');
  return [...pro, ...rest, ...free];
}

// Barra fixa do celular: "600 créditos · R$ 199,90".
export const barSummary = (p) => (p ? `${p.credits.toLocaleString('pt-BR')} créditos · ${brl(p.price_cents)}` : '');
