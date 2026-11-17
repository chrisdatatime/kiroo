// Planos (/pricing, Fase 6): lógica pura (shell/pricing.js) e marcação renderizada (shell/Pricing.jsx), sem navegador.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { createServer } from 'vite';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';

const P = await import('../src/shell/pricing.js');
const T = { unit_price_cents: 44, min_credits: 50, max_credits: 1000, shortcuts: [100, 200, 500] };

// ---------------------------------------------------------------- avulso: quantidade e total
assert.equal(P.brl(3990), 'R$ 39,90');
assert.equal(P.brl(44000), 'R$ 440,00');
assert.equal(P.parseQty('100'), 100);
for (const bad of ['', '50,5', '50.5', '-10', '1e3', 'abc', ' ', null]) assert.ok(Number.isNaN(P.parseQty(bad)), String(bad));
assert.equal(P.topupCheck(49, T).ok, false);
assert.match(P.topupCheck(49, T).error, /mínimo é 50/);
assert.equal(P.topupCheck(50, T).ok, true);
assert.equal(P.topupCheck(1000, T).ok, true);
assert.match(P.topupCheck(1001, T).error, /máximo por compra é 1\.000/);
assert.equal(P.topupCheck(50.5, T).ok, false);
assert.equal(P.topupCheck(-10, T).ok, false);
assert.equal(P.topupCheck(NaN, T).ok, false);
assert.equal(P.topupTotalCents(50, T), 2200);            // R$ 22,00
assert.equal(P.topupTotalCents(1000, T), 44000);         // R$ 440,00
assert.equal(P.topupTotalCents(1001, T), 0);
assert.equal(P.topupTotalCents(100, T), 4400);

// sem saldo: avulso em um clique com o que falta (pelo menos o mínimo)
assert.deepEqual(P.oneClickTopup(2000, T), { credits: 50, amount_cents: 2200, label: 'Comprar 50 créditos · R$ 22,00' });
assert.equal(P.oneClickTopup(150000, T).credits, 1000);
assert.equal(P.oneClickTopup(2000, null), null);

// "Este vídeo usa 20 créditos · saldo N"
const offer = { cc: 2000, credits: '20' };
assert.equal(P.videoCostLine(offer, { balance: '80', balance_cc: 8000 }), 'Este vídeo usa 20 créditos · saldo 80');
assert.equal(P.videoCostLine(offer, { exempt: true }), 'Este vídeo usa 20 créditos · saldo isento');
assert.equal(P.videoCostLine({ cc: 0, credits: '0' }, { balance: '0' }), '');      // DEMO: nada é cobrado
assert.equal(P.missingFor(offer, { balance_cc: 1500 }), 500);
assert.equal(P.missingFor(offer, { balance_cc: 2000 }), 0);
assert.equal(P.missingFor(offer, { balance_cc: 0, exempt: true }), 0);

// ---------------------------------------------------------------- planos: botão de cada card
const pro = { code: 'pro', name: 'Pro' }, basico = { code: 'basico', name: 'Básico' };
assert.deepEqual(P.planAction(pro, { plan: 'free', subscription: null }, true), { kind: 'subscribe', label: 'Assinar Pro', disabled: false });
const sub = { plan: 'pro', subscription: { status: 'active' } };
assert.deepEqual(P.planAction(pro, sub, true), { kind: 'current', label: 'Plano atual', disabled: true });
assert.deepEqual(P.planAction(basico, sub, true), { kind: 'change', label: 'Mudar para Básico', disabled: false });
assert.equal(P.planAction(basico, { plan: 'free', subscription: { status: 'canceled' } }, true).kind, 'subscribe');
assert.equal(P.planAction(pro, { plan: 'free' }, false).disabled, true);                    // compra desligada
assert.deepEqual(P.phonePlans([{ code: 'basico' }, { code: 'pro', highlight: true }, { code: 'estudio' }]).map((p) => p.code), ['pro', 'basico', 'estudio']);

// perguntas: [confirmar] fora; no celular só as dele
const desk = P.faqFor(false).map((f) => f.q), cel = P.faqFor(true).map((f) => f.q);
assert.ok(!desk.includes('Posso pedir reembolso?') && !desk.includes('Preciso de nota fiscal?'));
assert.ok(desk.includes('Posso trocar de plano?') && !cel.includes('Posso trocar de plano?') && cel.includes('Quanto custa cada vídeo?'));
assert.ok(!JSON.stringify(P.faqFor(false)).includes('[confirmar'));

// volta do checkout
assert.deepEqual(P.returnState('?compra=kpay_0123456789'), { order: 'kpay_0123456789', canceled: false, portal: false });
assert.deepEqual(P.returnState('?compra=../x&cancelado=1'), { order: null, canceled: true, portal: false });
assert.equal(P.orderMessage({ status: 'paid', kind: 'topup', credits: 100, balance: '180' }).text, 'Pagamento confirmado: 100 créditos adicionados. Saldo agora: 180.');
assert.equal(P.orderMessage({ status: 'pending' }).tone, 'wait');
assert.equal(P.orderMessage({ status: 'expired' }).tone, 'off');
assert.equal(P.shortDay('2026-12-16T12:00:00+00:00'), '16/12');
console.log('ok: pricing (lógica)');

// ---------------------------------------------------------------- marcação
const front = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const vite = await createServer({ root: front, configFile: path.join(front, 'vite.config.js'), logLevel: 'error', server: { middlewareMode: true, hmr: false }, appType: 'custom',
  optimizeDeps: { noDiscovery: true, include: [] } });
try {
  const { PricingView } = await vite.ssrLoadModule('/src/shell/Pricing.jsx');
  const plan = (code, name, credits, price, extra = {}) => ({ code, name, credits, price_cents: price, highlight: false, tagline: `t-${code}`,
    note: `n-${code}`, contact_note: false, features_lead: 'Tudo, mais:', features: [{ text: `f-${code}` }], ...extra });
  const cat = (over = {}) => ({ online: true, annual_enabled: false, welcome_credits: 20, video_price_credits: 20,
    plans: [plan('basico', 'Básico', 120, 3990), plan('pro', 'Pro', 320, 9990, { highlight: true }), plan('estudio', 'Estúdio', 800, 22990, { note: '', contact_note: true })],
    topup: T, plan: { plan: 'free', subscription: null, support: { whatsapp: null } }, contact: null, ...over });
  const render = (props) => renderToStaticMarkup(React.createElement(PricingView, { cat: cat(), user: {}, phone: false, notice: null, err: null, busy: null,
    raw: '100', setRaw() {}, onPlan() {}, onTopup() {}, onStatement() {}, ...props }));
  const count = (html, re) => (html.match(re) || []).length;

  let html = render({});
  assert.match(html, /Planos para vender com vídeo todo dia/);
  assert.match(html, /Seu primeiro vídeo é por nossa conta/); assert.match(html, /ganha 20 créditos de boas-vindas/);
  assert.ok(!/anualmente|Anual/.test(html));                                                 // sem chave mensal/anual na v1
  assert.equal(count(html, /<article/g), 3);
  assert.match(html, /Recomendado/);
  assert.match(html, />Assinar Básico</); assert.match(html, />Assinar Pro</); assert.match(html, />Assinar Estúdio</);
  assert.match(html, /R\$ 39,90/); assert.match(html, /R\$ 99,90/); assert.match(html, /R\$ 229,90/);
  assert.match(html, /fale com a gente/);
  assert.match(html, /Créditos avulsos/);
  assert.match(html, /aria-pressed="true"[^>]*><svg[^]*?100 créditos/);                      // atalho 100 escolhido
  assert.equal(count(html, /class="pr-chip"/g), 3);
  assert.match(html, /Outra quantidade/); assert.match(html, /Você paga <b>R\$ 44,00<\/b>/); assert.match(html, />Comprar 100 créditos</);
  assert.match(html, /Tem perguntas\?/); assert.match(html, /Contatar suporte/);
  assert.match(html, /aria-current="page">Planos</); assert.match(html, />Extrato</);
  assert.ok(!/<details/.test(html));                                                          // desktop: grade de perguntas

  html = render({ raw: '49' });
  assert.match(html, /aria-invalid="true"/); assert.match(html, /O mínimo é 50 créditos/); assert.match(html, /Você paga <b>R\$ 0,00<\/b>/);
  assert.match(html, /<button type="button" class="pr-btn pr-btn-auto" disabled=""/);
  html = render({ raw: '1000' });
  assert.match(html, /Você paga <b>R\$ 440,00<\/b>/);

  // com assinatura Pro: "Plano atual" e "Mudar para X"
  html = render({ cat: cat({ plan: { plan: 'pro', subscription: { status: 'active', cancel_at_period_end: false }, support: {} } }) });
  assert.match(html, />Plano atual</); assert.match(html, />Mudar para Básico</); assert.match(html, />Mudar para Estúdio</);
  assert.ok(!/Assinar /.test(html));

  // compra desligada: aviso e botões desligados
  html = render({ cat: cat({ online: false }) });
  assert.match(html, /compra pelo site ainda não está disponível/);
  assert.ok(count(html, /disabled=""/g) >= 4);

  // celular: Pro primeiro, perguntas em <details>, sem a troca Planos/Extrato
  html = render({ phone: true });
  assert.ok(html.indexOf('>Pro<') < html.indexOf('>Básico<'));
  assert.match(html, /<details class="pr-det">/); assert.ok(!/pr-seg/.test(html));

  // nenhum id da Stripe nem preço vindo do navegador
  const jsx = readFileSync(new URL('../src/shell/Pricing.jsx', import.meta.url), 'utf8');
  assert.ok(!/price_[A-Za-z0-9]{6}/.test(jsx) && /kind: 'topup', credits: n/.test(jsx) && /kind: 'plan', plan: p\.code/.test(jsx));
  console.log('ok: pricing (marcação)');
} finally {
  await vite.close();
}
