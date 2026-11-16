// Início renderizado (sem navegador): o Vite compila o JSX em modo SSR e o React gera o HTML de cada estado.
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
  const { default: Inicio } = await vite.ssrLoadModule('/src/shell/Inicio.jsx');
  const { default: Sidebar } = await vite.ssrLoadModule('/src/shell/Sidebar.jsx');
  const noop = () => {};
  const team = ['nina', 'theo', 'iris', 'rui', 'lia', 'beto'].map((id) => ({ id, name: id[0].toUpperCase() + id.slice(1), role: 'x', look: { shirt: '#FF8FC0', acc: 'bone' } }));
  const scenes = [{ id: 'home_light', label: 'Casa Clara' }, { id: 'studio', label: 'Estúdio' }, { id: 'natural', label: 'Natural' }, { id: 'dark_premium', label: 'Escuro Premium' }];
  const platforms = [{ id: 'shopee_video', label: 'Shopee Vídeo' }, { id: 'tiktok_shop', label: 'TikTok Shop' }, { id: 'mercado_livre', label: 'Mercado Livre' }];
  const prod = (id, status, extra = {}) => ({ id, status, engine: 'fal', name: 'Skate Completo', scene: 'dark_premium', platform: 'shopee_video', created_at: new Date().toISOString(), open: noop, ...extra });
  const base = (over = {}) => ({
    productions: [], team, statuses: {}, setView: noop, newProd: noop, openPrefs: noop, openBuy: noop, view: 'central', win: null, P: null, falMission: null,
    account: { user: { name: 'Christian Silva', email: 'c@x.io', email_verified: true }, workspace: { name: 'Estúdio de Christian' }, plan: { plan_label: 'avulso', support: { email: 'suporte@kiroo.io' } }, welcome: null },
    wallet: { balance: '80', balance_cc: 8000, exempt: false }, offer: { cc: 2000, credits: '20' },
    falNew: { scenes, platforms, scene: 'home_light', platform: 'shopee_video', file: null, errors: ['a foto do produto'], error: null, busy: false, demo: false, pick: noop, pickFile: noop, setScene: noop, setPlatform: noop, create: noop, openBuy: noop, reuseBlocked: false },
    ...over });
  const render = (v, phone = false) => renderToStaticMarkup(React.createElement(Inicio, { v, phone }));
  const has = (html, s) => html.includes(s);
  const count = (html, re) => (html.match(re) || []).length;
  const REMOVED = ['Workspace operacional', 'Decisões pendentes', 'Missão em curso', 'Usado neste vídeo', 'Próxima ação', 'Assistido', 'Ver entrega'];
  const noRemoved = (html) => REMOVED.forEach((t) => assert.ok(!has(html, t), `não deve mostrar "${t}"`));

  // 1) conta ativa, com pendência + em andamento + pronta (2 em andamento/pendentes e 1 pronta = 3: "Como funciona" fora)
  const aprov = prod('prod_c67de26276', 'awaiting_final_review', { name: 'prod_c67de26276', created_at: '2026-11-14T10:00:00' });   // nome = id cru
  const gen = prod('prod_2', 'producing', { name: 'Tênis Run' });
  const done = prod('prod_3', 'completed', { name: 'Garrafa Térmica' });
  let html = render(base({ productions: [aprov, gen, done], statuses: { beto: 'need' } }));
  noRemoved(html);
  assert.ok(has(html, '1 vídeo espera sua aprovação e 1 está sendo produzido.'));
  assert.ok(has(html, 'Aguardando sua aprovação'));
  assert.equal(count(html, /Assistir e aprovar/g), 2);                 // cartão "precisa de você" + a linha dessa produção na tabela
  assert.ok(!has(html, 'prod_c67de26276'), 'o id cru nunca aparece como nome');
  assert.ok(/Produção de 14\/11, \d\d:\d\d/.test(html));
  assert.ok(has(html, 'Beto espera você'));
  assert.ok(!has(html, 'Como funciona'), 'com 3 produções, "Como funciona" some');
  assert.ok(!has(html, '+1 aguardando') && !has(html, 'aguardando</button>'));
  assert.ok(has(html, '<th scope="col">Produto</th>') && has(html, '<th scope="col">Status</th>'));
  assert.ok(has(html, 'aria-pressed="true"'));                          // cenário e plataforma escolhidos
  assert.ok(has(html, 'Fica pronto em cerca de'));
  assert.ok(has(html, 'Custa 20 créditos'));
  assert.ok(has(html, 'Garrafa Térmica') && has(html, 'Pronto') && has(html, 'Gerando'));

  // 2) "+N aguardando": duas pendências → mostra a mais antiga e o link
  html = render(base({ productions: [aprov, prod('prod_9', 'awaiting_final_review', { name: 'Outro' })] }));
  assert.ok(has(html, '+1 aguardando'));
  assert.ok(has(html, '2 vídeos esperam sua aprovação.'));
  assert.ok(has(html, 'Primeiros passos') && !has(html, 'Como funciona'), 'Primeiros passos visível: "Como funciona" fica de fora');
  html = render(base({ productions: [done, prod('prod_8', 'completed', { name: 'Outra' })] }));
  assert.ok(has(html, 'Como funciona') && !has(html, 'Primeiros passos'), 'com 2 produções e passos feitos, "Como funciona" aparece');

  // 3) sem pendência: sem cartão "precisa de você", resumo "Tudo em dia."
  html = render(base({ productions: [done, prod('prod_4', 'cancelled', { name: 'Cancelada X' })] }));
  assert.ok(has(html, 'Tudo em dia.'));
  assert.ok(!has(html, 'Aguardando sua aprovação'));
  assert.ok(has(html, 'Cancelado'));
  noRemoved(html);

  // 4) gerando, com percentual real da produção aberta (barra de progresso)
  html = render(base({ productions: [prod('prod_5', 'producing', { current: true, name: 'Em geração' })], falMission: { status: { kind: 'running' }, progress: 42 } }));
  assert.ok(has(html, 'role="progressbar"') && has(html, 'aria-valuenow="42"'));
  assert.ok(has(html, '1 está sendo produzido.'));

  // 5) primeiro acesso (sem produções): bônus real, Primeiros passos e SEM "Como funciona"
  html = render(base({ account: { user: { name: 'Ana', email_verified: false }, workspace: { name: 'Ana' }, welcome: { credits: 20 } } }));
  assert.ok(has(html, 'Seus 20 créditos de boas-vindas'));
  assert.ok(has(html, 'Primeiros passos') && has(html, 'Confirmar e-mail') && has(html, 'Criar o primeiro vídeo') && has(html, 'Baixar e publicar'));
  assert.ok(!has(html, 'Como funciona'));
  assert.ok(has(html, 'Suas produções aparecem aqui.'));
  assert.ok(!has(html, 'Tudo em dia.'), 'sem produções a frase de resumo some');
  noRemoved(html);

  // 5b) bônus diferente vem do dado (nada fixo)
  html = render(base({ productions: [], account: { user: { name: 'Ana', email_verified: true }, workspace: { name: 'Ana' }, welcome: { credits: 35 } } }));
  assert.ok(has(html, 'Seus 35 créditos de boas-vindas'));

  // 6) erro: selo vermelho, ação "Ver detalhes" e a regra dos créditos
  html = render(base({ productions: [prod('prod_6', 'failed', { name: 'Deu ruim' })] }));
  assert.ok(has(html, 'data-tone="bad"') && has(html, 'Erro') && has(html, 'Ver detalhes'));
  assert.ok(has(html, 'Se foi erro técnico, não cobramos.'));

  // 7) celular: cartões de produção, dois botões grandes (câmera e galeria), sem tabela
  html = render(base({ productions: [aprov, gen] }), true);
  assert.ok(has(html, 'capture="environment"') && has(html, 'Tirar foto') && has(html, 'Galeria'));
  assert.ok(!has(html, '<table'));
  assert.ok(has(html, 'in-pcard'));
  noRemoved(html);

  // 8) sem o fluxo de foto+cenário no motor: o cartão vira convite para "Nova produção"
  html = render(base({ falNew: null }));
  assert.ok(has(html, 'Nova produção'));

  // 9) barra lateral: 5 destinos, badge de pendências, saldo e "≈ N vídeos" do custo configurado
  const side = (v) => renderToStaticMarkup(React.createElement(Sidebar, { v, menuItems: null }));
  html = side(base({ productions: [aprov, gen] }));
  ['Início', 'Produções', 'Entregas', 'Equipe', 'Créditos'].forEach((t) => assert.ok(has(html, `>${t}<`), t));
  assert.ok(has(html, '1 esperando ação'));
  assert.ok(has(html, 'Dá para ≈ 4 vídeos'));
  assert.ok(has(html, 'suporte@kiroo.io') && has(html, 'Ajuda e suporte'));
  html = side(base({ offer: { cc: 4000, credits: '40' } }));
  assert.ok(has(html, 'Dá para ≈ 2 vídeos'), 'o custo vem da configuração');
  html = side(base({ offer: { cc: 0, credits: '0' } }));
  assert.ok(!has(html, 'Dá para'), 'sem custo real (DEMO) a frase some');
  assert.ok(!has(side(base({ productions: [] })), 'esperando ação'));

  console.log('inicio-render.test ok');
} finally { await vite.close(); }
