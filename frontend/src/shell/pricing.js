// Planos (/pricing, Fase 6): lógica pura da tela, sem React (tests/pricing.test.mjs).
// O navegador só EXIBE preço. Quem cobra é a Stripe, com o preço escolhido pelo servidor; o pedido leva só o código do
// plano ou a quantidade de créditos avulsos, que o servidor valida de novo (inteiro, mínimo e máximo).
import { PRICING_FAQ } from '../config/appConfig.js';

// 3990 → "R$ 39,90"
export function brl(cents) {
  const n = (Number(cents) || 0) / 100;
  return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const fmtInt = (n) => Number(n).toLocaleString('pt-BR');

// ---------------------------------------------------------------- avulso
// Campo "outra quantidade": só dígitos viram número; "50,5", "-10", "1e3" e vazio viram NaN (o botão fica desligado).
export function parseQty(raw) {
  const t = String(raw == null ? '' : raw).trim();
  return /^\d{1,6}$/.test(t) ? Number(t) : NaN;
}

// { ok, error } para a quantidade, com os limites que o servidor mandou (`topup.min_credits` / `max_credits`).
export function topupCheck(n, t) {
  if (!t) return { ok: false, error: 'Compra avulsa indisponível.' };
  if (!Number.isInteger(n)) return { ok: false, error: 'Digite um número inteiro de créditos.' };
  if (n < t.min_credits) return { ok: false, error: `O mínimo é ${fmtInt(t.min_credits)} créditos.` };
  if (n > t.max_credits) return { ok: false, error: `O máximo por compra é ${fmtInt(t.max_credits)} créditos.` };
  return { ok: true, error: null };
}

// "Você paga R$ X": quantidade × preço por crédito (0 se a quantidade não vale).
export const topupTotalCents = (n, t) => (topupCheck(n, t).ok ? n * t.unit_price_cents : 0);

// Sem saldo para o vídeo: compra avulsa em um clique com o que falta (pelo menos o mínimo, no máximo o máximo).
export function oneClickTopup(missingCc, t) {
  if (!t || !t.min_credits) return null;
  const need = Math.ceil(Math.max(Number(missingCc) || 0, 0) / 100);
  const credits = Math.min(Math.max(need, t.min_credits), t.max_credits);
  return { credits, amount_cents: credits * t.unit_price_cents, label: `Comprar ${fmtInt(credits)} créditos · ${brl(credits * t.unit_price_cents)}` };
}

// "Este vídeo usa 20 créditos · saldo 80" (antes de cada vídeo). Sem preço (DEMO): vazio.
export function videoCostLine(offer, wallet) {
  if (!offer || !(offer.cc > 0)) return '';
  const base = `Este vídeo usa ${offer.credits} ${offer.credits === '1' ? 'crédito' : 'créditos'}`;
  if (!wallet) return base;
  return `${base} · saldo ${wallet.exempt ? 'isento' : wallet.balance}`;
}

// Saldo menor que o preço do vídeo (conta isenta e DEMO nunca faltam).
export function missingFor(offer, wallet) {
  if (!offer || !(offer.cc > 0) || !wallet || wallet.exempt) return 0;
  const bal = Number(wallet.balance_cc);
  return Number.isFinite(bal) && bal < offer.cc ? offer.cc - bal : 0;
}

// ---------------------------------------------------------------- planos
const LIVE = ['active', 'trialing', 'past_due'];

// Botão de cada card: sem assinatura "Assinar X"; com assinatura valendo, o plano dela vira "Plano atual" e os outros
// "Mudar para X" (pelo Portal do cliente da Stripe). Compra desligada: botão desligado.
export function planAction(p, plan, online) {
  const sub = plan && plan.subscription && LIVE.includes(plan.subscription.status) ? plan.subscription : null;
  if (sub && plan.plan === p.code) return { kind: 'current', label: 'Plano atual', disabled: true };
  if (sub) return { kind: 'change', label: `Mudar para ${p.name}`, disabled: !online };
  return { kind: 'subscribe', label: `Assinar ${p.name}`, disabled: !online };
}

// Celular: o recomendado primeiro, depois os outros na ordem do catálogo (design `CelPrecos`).
export function phonePlans(plans) {
  const list = plans || [];
  return [...list.filter((p) => p.highlight), ...list.filter((p) => !p.highlight)];
}

// "120 créditos por mês" e "≈ 6 vídeos"
export const creditsLine = (p) => `${fmtInt(p.credits)} créditos`;

// Perguntas mostradas: as confirmadas; no celular, só as marcadas para ele.
export function faqFor(phone, list = PRICING_FAQ) {
  return list.filter((f) => f.show !== false && (!phone || f.phone !== false));
}

// Volta do checkout: ?compra=kpay_... (acompanhar a compra) ou ?cancelado=1. `plano=1` = volta do Portal.
export function returnState(search) {
  let q;
  try { q = new URLSearchParams(search || ''); } catch { return { order: null, canceled: false, portal: false }; }
  const order = q.get('compra');
  return { order: /^kpay_[0-9a-f]{10}$/.test(order || '') ? order : null, canceled: q.get('cancelado') === '1', portal: q.get('plano') === '1' };
}

// Mensagem depois da volta do checkout, a partir do status da compra no servidor.
export function orderMessage(p) {
  if (!p) return { tone: 'wait', text: 'Confirmando o pagamento…' };
  if (p.status === 'paid') {
    return p.kind === 'plan'
      ? { tone: 'ok', text: `Assinatura ativa. Os créditos do plano entram no saldo assim que a Stripe confirmar a primeira cobrança.` }
      : { tone: 'ok', text: `Pagamento confirmado: ${fmtInt(p.credits)} créditos adicionados${p.balance ? `. Saldo agora: ${p.balance}.` : '.'}` };
  }
  if (p.status === 'processing') return { tone: 'wait', text: 'Pagamento em processamento. Avisamos aqui quando confirmar (Pix pode levar alguns minutos).' };
  if (p.status === 'pending' || p.status === 'creating') return { tone: 'wait', text: 'Confirmando o pagamento…' };
  return { tone: 'off', text: 'Nada foi cobrado por esta compra. Você pode tentar de novo.' };
}

// Data curta "16/12" (fim do ciclo)
export function shortDay(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}` : '';
}
