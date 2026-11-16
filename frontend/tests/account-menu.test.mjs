// Fase 1 do novo layout: menu lateral, menu da conta, avatar kiroo e Configurações (Perfil | Créditos).
// Lógica pura + renderização sem navegador (Vite SSR), como inicio-render.test.mjs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';

const front = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const vite = await createServer({ root: front, configFile: path.join(front, 'vite.config.js'), logLevel: 'error', server: { middlewareMode: true, hmr: false }, appType: 'custom',
  optimizeDeps: { noDiscovery: true, include: [] } });
try {
  const m = await vite.ssrLoadModule('/src/shell/accountMenu.js');
  const av = await vite.ssrLoadModule('/src/ui/avatar.js');
  const st = await vite.ssrLoadModule('/src/shell/settings.js');
  const cfg = await vite.ssrLoadModule('/src/config/appConfig.js');
  const { PHONE_MAX } = await vite.ssrLoadModule('/src/ui/mobile.js');

  // ---- avatar: o id do servidor vira um look; id ausente/desconhecido cai no padrão (nunca quebra)
  assert.equal(av.KIROO_IDS.length, 12);
  assert.deepEqual(av.KIROO_IDS.slice(0, 2), ['k01', 'k02'], 'mesmos ids de src/studio/avatars.py');
  const py = fs.readFileSync(path.join(front, '..', 'src', 'studio', 'avatars.py'), 'utf8');
  assert.ok(/range\(1, 13\)/.test(py), 'o servidor sorteia entre os mesmos 12 ids');
  assert.deepEqual(av.kirooLook({ avatar_kiroo: 'k07' }), av.KIROO_LOOKS.k07);
  assert.deepEqual(av.kirooLook({}), av.KIROO_LOOKS.k01);
  assert.deepEqual(av.kirooLook({ avatar_kiroo: 'k99' }), av.KIROO_LOOKS.k01);
  assert.equal(av.kirooTint({ shirt: '#FF8FC0' }), '#FF8FC033');

  // ---- textos do menu
  assert.equal(m.studioName({ workspace: { name: 'Estúdio de Ana' } }), 'Estúdio de Ana');
  assert.equal(m.studioName({ workspace: { name: '' }, user: { name: 'Ana Souza' } }), 'Estúdio de Ana');
  assert.equal(m.displayName({ user: { name: '', email: 'ana@x.io' } }), 'ana');
  assert.equal(m.balanceShort({ balance: '80', exempt: false }), '80');
  assert.equal(m.balanceShort({ exempt: true }), 'Isento');
  assert.equal(m.balanceLong({ balance: '1', exempt: false }), '1 crédito');
  assert.equal(m.balanceLong({ balance: '2.000', exempt: false }), '2.000 créditos');
  assert.equal(m.videosApprox({ balance_cc: 8000, balance: '80' }), '≈ 4 vídeos', 'vídeo a 20 créditos fixos');
  assert.equal(m.videosApprox({ balance_cc: 2500, balance: '25' }), '≈ 1 vídeo');
  assert.equal(m.videosApprox({ exempt: true }), '');
  assert.equal(cfg.VIDEO_CREDITS, 20);

  // ---- links legais pela landing_url (só https); sem ela, no próprio app
  assert.deepEqual(m.legalLinks('https://kiroo.io').map((l) => l.href), ['https://kiroo.io/termos', 'https://kiroo.io/privacidade', 'https://kiroo.io/privacidade#p7-t']);
  assert.equal(m.legalLinks('https://kiroo.io/')[0].href, 'https://kiroo.io/termos');
  assert.equal(m.legalLinks('')[0].href, '/termos');
  assert.equal(m.legalLinks('javascript:alert(1)')[0].href, '/termos', 'base que não é https é ignorada');
  assert.equal(m.supportHref({ plan: { support: { email: 'ajuda@kiroo.io' } } }), `mailto:ajuda@kiroo.io?subject=${encodeURIComponent('Suporte Kiroo')}`);
  assert.ok(m.supportHref(null).startsWith('mailto:suporte@kiroo.io'));

  // ---- Aparência: tema escuro atrás da flag (desligada) → só "Claro"
  assert.equal(cfg.DARK_THEME_ENABLED, false);
  assert.deepEqual(m.appearanceOptions().map((o) => o.label), ['Claro']);
  assert.deepEqual(m.appearanceOptions(true).map((o) => o.label), ['Automático', 'Claro', 'Escuro']);
  assert.deepEqual(m.creditItems().map((c) => c.label), ['Saldo e extrato', 'Planos e créditos', 'Recibos']);
  assert.equal(m.creditItems()[1].href, '/pricing');
  assert.equal(m.creditItems()[2].soon, true, 'Recibos sem backend: "em breve"');

  // ---- navegação: 4 destinos; celular com o "+" no meio
  const prod = (status, extra = {}) => ({ id: 'prod_' + status, status, engine: 'fal', created_at: new Date().toISOString(), ...extra });
  const v = { view: 'central', win: null, productions: [prod('awaiting_final_review'), prod('producing', { running: true }), prod('completed')] };
  const nav = m.sideNav(v);
  assert.deepEqual(nav.map((x) => x.label), ['Início', 'Escritório', 'Produções', 'Entregas']);
  assert.equal(nav[0].on, true);
  assert.equal(nav[1].live, true);
  assert.equal(nav[2].badge, 1);
  assert.equal(m.sideNav({ ...v, productions: [] })[1].live, false);
  assert.deepEqual(m.phoneTabs(v).map((x) => x.id), ['inicio', 'escritorio', 'nova', 'producoes', 'entregas']);
  assert.equal(m.sideNav({ ...v, view: 'config' }).some((x) => x.on), false, 'Configurações não acende nenhum destino');

  // ---- setas na gaveta
  assert.equal(m.nextIndex(0, 3, 'ArrowDown'), 1);
  assert.equal(m.nextIndex(2, 3, 'ArrowDown'), 0);
  assert.equal(m.nextIndex(0, 3, 'ArrowUp'), 2);
  assert.equal(m.nextIndex(1, 3, 'Home'), 0);
  assert.equal(m.nextIndex(1, 3, 'End'), 2);
  assert.equal(m.nextIndex(0, 0, 'ArrowDown'), -1);

  // ---- Configurações: barras por origem, frase do saldo, extrato e formulário
  assert.equal(st.barPct({ received_cc: 2000, left_cc: 500 }), 25);
  assert.equal(st.barPct({ received_cc: 0, left_cc: 0 }), 0);
  const rows = st.originRows([{ key: 'bonus', label: 'Bônus de boas-vindas', received_cc: 2000, left_cc: 2000, received: '20', left: '20' }]);
  assert.equal(rows[0].accent, true);
  assert.equal(rows[0].note, cfg.ORIGIN_NOTES.bonus);
  const s = st.balanceSentence({ balance_cc: 8000 });
  assert.equal(s.strong, '≈ 4 vídeos');
  assert.ok(s.lead.includes('Cada vídeo usa 20 créditos'));
  assert.ok(st.balanceSentence({ exempt: true }).startsWith('Conta isenta'));
  const line = st.statementLine({ id: 'e1', at: '2026-11-15T12:00:00', title: 'Produção', subtitle: 'Skate', credits: '−20', status: 'done' });
  assert.deepEqual([line.date, line.title, line.tone, line.status], ['15/11', 'Produção · Skate', 'out', '']);
  assert.equal(st.statementLine({ id: 'e2', credits: '+20', status: 'gift', status_label: 'Presente' }).status, '');
  assert.equal(st.statementLine({ id: 'e3', credits: '0', status: 'not_charged', status_label: 'Não cobrado' }).tone, 'zero');
  assert.deepEqual(st.profileChanges({ name: 'Ana' }, { name: ' Ana ', tax: '' }), {});
  assert.deepEqual(st.profileChanges({ name: 'Ana' }, { name: 'Ana  Souza', tax: '529.982.247-25' }), { name: 'Ana Souza', tax: '529.982.247-25' });

  // ---- render: Configurações
  const { ProfileView, CreditsTabView, SettingsTabs } = await vite.ssrLoadModule('/src/shell/Settings.jsx');
  const noop = () => {};
  const tabs = renderToStaticMarkup(React.createElement(SettingsTabs, { tab: 'creditos', onTab: noop }));
  assert.ok(tabs.includes('aria-current="page"') && tabs.indexOf('Perfil') < tabs.indexOf('Créditos'));
  const a = { user: { name: 'Ana Souza', email: 'ana@x.io', email_verified: true, has_password: true, google: true, tax_doc: '•••.•••.•••-25', avatar_kiroo: 'k03' } };
  let html = renderToStaticMarkup(React.createElement(ProfileView, { a, busy: false, msg: null, onSave: noop, onVerify: noop, onCode: noop, codeSent: false,
    pwOpen: false, setPwOpen: noop, onPassword: noop, del: false, setDel: noop, onDelete: noop }));
  ['Ana Souza', 'Verificado', 'CPF ou CNPJ', '•••.•••.•••-25', 'Segurança', 'Login com Google', 'Conectado', 'Trocar senha', 'Notificações por e-mail',
    'Exportar meus dados', 'href="/api/account/export"', 'Excluir conta', 'Seu kiroo é sorteado'].forEach((t) => assert.ok(html.includes(t), t));
  assert.ok(html.includes('em breve'), 'notificações e desconectar Google sem backend: em breve');
  assert.ok(/<input[^>]*type="checkbox"[^>]*disabled/.test(html), 'interruptores desabilitados');
  html = renderToStaticMarkup(React.createElement(ProfileView, { a: { user: { ...a.user, email_verified: false, google: false, has_password: false } }, busy: false, msg: null,
    onSave: noop, onVerify: noop, onCode: noop, codeSent: false, pwOpen: false, setPwOpen: noop, onPassword: noop, del: false, setDel: noop, onDelete: noop }));
  assert.ok(html.includes('Confirmar e-mail') && html.includes('Não conectado') && !html.includes('Trocar senha'));

  const d = { balance: '80', balance_cc: 8000, exempt: false,
    origins: [{ key: 'bonus', label: 'Bônus de boas-vindas', received_cc: 2000, left_cc: 0, received: '20', left: '0' },
      { key: 'purchased', label: 'Créditos comprados', received_cc: 20000, left_cc: 8000, received: '200', left: '80' }],
    statement: [{ id: 'e1', at: '2026-11-15T12:00:00', title: 'Uso', subtitle: 'Skate', credits: '−20', status: 'done' },
      { id: 'e2', at: '2026-11-14T12:00:00', title: 'Falha técnica', credits: '0', status: 'not_charged', status_label: 'Não cobrado' }] };
  html = renderToStaticMarkup(React.createElement(CreditsTabView, { d, onPricing: noop }));
  ['Seus créditos', 'Planos e créditos', 'Cada vídeo usa 20 créditos', '≈ 4 vídeos', 'Bônus de boas-vindas', '0 / 20', 'Créditos comprados', '80 / 200',
    'os créditos voltam automaticamente', 'Recibos', 'Extrato', 'Baixar CSV', '/api/credits/statement.csv', '15/11', 'Uso · Skate', '−20', 'Não cobrado']
    .forEach((t) => assert.ok(html.includes(t), t));
  assert.ok(!html.includes('Asaas'), 'sem nome de provedor de pagamento fixo');
  html = renderToStaticMarkup(React.createElement(CreditsTabView, { d: { balance: '0', exempt: true, origins: [], statement: [] }, onPricing: noop }));
  assert.ok(html.includes('Isento') && !html.includes('Planos e créditos') && html.includes('Sem lançamentos'));

  // ---- bug do "Comprar créditos" no celular: o CSS da tela de compra vira celular no mesmo ponto que o JS (usePhone)
  const css = fs.readFileSync(path.join(front, 'src/ui/buyv2.css'), 'utf8');
  assert.ok(css.includes(`@media (max-width: ${PHONE_MAX}px)`), 'buyv2.css usa PHONE_MAX');
  assert.ok(!/max-width:\s*640px/.test(css), 'sem o limite antigo de 640 px (a barra Comprar sumia entre 641 e 767 px)');

  console.log('account-menu.test ok');
} finally { await vite.close(); }
