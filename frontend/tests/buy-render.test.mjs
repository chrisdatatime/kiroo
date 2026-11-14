// Comprar créditos v2: marcação renderizada (sem navegador). Rádios de verdade (input radio + label) num radiogroup,
// seleção (classe is-sel, botão preto "Comprar Pro"), Free não selecionável, Free some para quem já comprou, celular.
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';

const front = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const vite = await createServer({ root: front, configFile: path.join(front, 'vite.config.js'), logLevel: 'error', server: { middlewareMode: true, hmr: false }, appType: 'custom',
  optimizeDeps: { noDiscovery: true, include: [] } });
try {
  const { Plans } = await vite.ssrLoadModule('/src/ui/BuyCredits.jsx');
  const f = (text, strong) => ({ text, strong: !!strong });
  const packages = [
    { code: 'inicial', name: 'Inicial', credits: 200, price_cents: 7990, per_credit_cents: 40, savings_pct: 20, features: [f('Suporte por e-mail')] },
    { code: 'pro', name: 'Pro', credits: 600, price_cents: 19990, per_credit_cents: 33, savings_pct: 33, highlight: true, features: [f('Tudo do Inicial'), f('Suporte por WhatsApp', true)] },
    { code: 'escala', name: 'Escala', credits: 2000, price_cents: 54990, per_credit_cents: 27, savings_pct: 45, features: [f('Novos estilos antes de todos')] },
  ];
  const free = { name: 'Free', credits: 20, tagline: 'Só para conhecer', price_note: 'Crédito de boas-vindas', missing: ['Sem suporte por WhatsApp'] };
  const cat = (plan) => ({ packages, free, plan });
  const render = (props) => renderToStaticMarkup(React.createElement(Plans, { setPkg: () => {}, onBuy: () => {}, onAvulso: () => {}, phone: false, ...props }));
  const count = (html, re) => (html.match(re) || []).length;

  // conta sem compra: 4 cards, Free primeiro e não selecionável, Pro selecionado
  let html = render({ cat: cat({ plan: 'free', has_purchase: false }), pkg: 'pro' });
  assert.match(html, /role="radiogroup" aria-label="Pacotes de créditos" class="bv-grid" data-n="4"/);
  assert.equal(count(html, /type="radio"/g), 3);                                  // Free não é rádio
  assert.equal(count(html, /checked=""/g), 1);
  assert.match(html, /<input[^>]*id="bv-pro"[^>]*checked=""/);
  assert.equal(count(html, /class="bv-card is-sel"/g), 1);
  assert.ok(html.indexOf('bv-card is-free') < html.indexOf('bv-inicial'));         // Free à esquerda
  assert.match(html, /<button type="button" class="bv-btn is-sel" tabindex="0">Comprar Pro<\/button>/);
  assert.equal(count(html, />Comprar<\/button>/g), 2);                             // Inicial e Escala em contorno
  assert.match(html, /<button type="button" class="bv-btn is-off" disabled="">Seu plano atual<\/button>/);
  assert.match(html, /class="bv-badge">Mais escolhido</);
  assert.match(html, /Economize 33%/);
  assert.ok(!/1 vídeo =|≈|rende até/.test(html));
  assert.match(html, /Precisa de outra quantidade\? <button type="button" class="bv-link">Comprar avulso<\/button>/);
  assert.match(html, /Pix ou cartão · pagamento seguro via Asaas/);
  // rádio fora da seleção sai do Tab (setas navegam no grupo); o selecionado fica no Tab
  assert.match(html, /id="bv-inicial" tabindex="-1"/);
  assert.match(html, /id="bv-pro" tabindex="0"/);

  // trocar a seleção (clique/teclado chamam setPkg) move a borda e o botão preto
  html = render({ cat: cat({ plan: 'free', has_purchase: false }), pkg: 'escala' });
  assert.match(html, /<input[^>]*id="bv-escala"[^>]*checked=""/);
  assert.match(html, />Comprar Escala<\/button>/);
  assert.equal(count(html, />Comprar<\/button>/g), 2);

  // já comprou o Pro: sem Free (3 cards), etiqueta "Seu plano atual" no Pro, "Comprar de novo", sem "Mais escolhido"
  html = render({ cat: cat({ plan: 'pro', has_purchase: true }), pkg: 'pro' });
  assert.match(html, /data-n="3"/);
  assert.ok(!/is-free/.test(html) && !/Mais escolhido/.test(html));
  assert.match(html, /<span class="bv-name">Pro<\/span><span class="bv-tag">Seu plano atual<\/span>/);
  assert.match(html, />Comprar de novo<\/button>/);

  // celular: Pro primeiro e aberto; os outros compactos; Free por último; barra fixa com o resumo
  html = render({ cat: cat({ plan: 'free', has_purchase: false }), pkg: 'pro', phone: true });
  const order = [...html.matchAll(/id="bv-(inicial|pro|escala)"/g)].map((m) => m[1]);
  assert.deepEqual(order, ['pro', 'inicial', 'escala']);
  assert.ok(html.lastIndexOf('is-free') > html.indexOf('bv-escala'));
  assert.equal(count(html, /class="bv-card is-compact"/g), 2);
  assert.match(html, /class="bv-bar"><span class="bv-bar-sum">600 créditos · R\$.199,90<\/span>/);
  console.log('ok: comprar créditos (render)');
} finally {
  await vite.close();
}
