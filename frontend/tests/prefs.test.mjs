// Preferências v2: regras puras (saldo inteiro, selos, vantagens por plano, itens por env, máscara) e marcação renderizada
// de Créditos e extrato, Minha conta e Sobre (sem navegador).
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
  const P = await vite.ssrLoadModule('/src/ui/prefs.js');
  const { fmtBalance } = await vite.ssrLoadModule('/src/ui/credits.js');
  const h = React.createElement;

  // saldo inteiro, arredondado para baixo
  assert.equal(fmtBalance(1999), '19'); assert.equal(fmtBalance(99), '0'); assert.equal(fmtBalance(200000), '2.000'); assert.equal(fmtBalance(-40), '−1');
  assert.equal(P.reservedText({ held: '0', held_cc: 0 }), 'Nada reservado no momento');
  assert.equal(P.reservedText({ held: '40', held_cc: 4000 }), '40 reservados para vídeos em andamento');
  assert.equal(P.reservedText({ held: '1', held_cc: 100 }), '1 reservado para um vídeo em andamento');
  assert.equal(P.reservedText({ held: '0', held_cc: 50 }), 'Nada reservado no momento');   // 0,5 crédito não vira "0 reservados"

  // selos do extrato (cores do pedido)
  assert.deepEqual(P.statusStyle('paid'), { fg: '#166534', bg: '#DCFCE7' });
  assert.deepEqual(P.statusStyle('done'), { fg: '#3A3935', bg: '#F1F0EC' });
  assert.deepEqual(P.statusStyle('not_charged'), { fg: '#9A3412', bg: '#FFEDD5' });
  assert.deepEqual(P.statusStyle('gift'), { fg: '#1E40AF', bg: '#DBEAFE' });
  assert.match(P.statusStyle('reversed').fg, /^#[0-9A-F]{6}$/);
  assert.deepEqual(P.statusStyle('???'), P.statusStyle('done'));
  assert.equal(P.amountTone('+20'), '#166534'); assert.equal(P.amountTone('−20'), '#141414'); assert.equal(P.amountTone('0'), '#5F5E5A');

  // plano e vantagens reais
  const free = { plan: 'free', plan_label: 'Free', priority_queue: false, early_access: false, support: { whatsapp: null, email: 'a@b.com' } };
  const ini = { ...free, plan: 'basico', plan_label: 'Básico' };   // Fase 6: Básico/Pro/Estúdio (antes Inicial/Pro/Escala)
  const pro = { plan: 'pro', plan_label: 'Pro', priority_queue: true, early_access: false, support: { whatsapp: 'https://wa.me/5511999990000', email: 'a@b.com' } };
  const esc = { ...pro, plan: 'estudio', plan_label: 'Estúdio', early_access: true };
  assert.deepEqual([free, ini, pro, esc].map(P.planName), ['FREE', 'BÁSICO', 'PRO', 'ESTÚDIO']);
  assert.deepEqual(P.planPerks(free), []); assert.deepEqual(P.planPerks(ini), []);
  assert.deepEqual(P.planPerks(pro), ['Fila prioritária', 'Suporte por WhatsApp']);
  assert.deepEqual(P.planPerks(esc), ['Fila prioritária', 'Suporte por WhatsApp', 'Acesso antecipado a novidades']);

  // ajuda: WhatsApp só Pro/Escala com env; sem env cai no e-mail; Free/Inicial sempre e-mail
  const site = { contact: { label: 'ajuda@exemplo.com', href: 'mailto:ajuda@exemplo.com' } };
  assert.equal(P.helpCard(pro, site).kind, 'whatsapp'); assert.equal(P.helpCard(esc, site).href, 'https://wa.me/5511999990000');
  assert.equal(P.helpCard({ ...pro, support: { whatsapp: null } }, site).kind, 'email');
  assert.equal(P.helpCard(free, site).kind, 'email'); assert.equal(P.helpCard({ ...free, support: { whatsapp: 'https://wa.me/5511999990000' } }, site).kind, 'email');
  assert.equal(P.helpCard(free, {}), null);

  // CPF/CNPJ, exclusão, avatar
  assert.deepEqual(P.taxDocRow(''), { value: 'Não informado', action: 'Adicionar' });
  assert.deepEqual(P.taxDocRow('•••.•••.•••-25'), { value: '•••.•••.•••-25', action: 'Alterar' });
  assert.equal(P.canDelete(' Chris@Exemplo.com ', 'chris@exemplo.com'), true); assert.equal(P.canDelete('chris', 'chris@exemplo.com'), false); assert.equal(P.canDelete('', ''), false);
  assert.equal(P.initialOf({ name: 'ana', email: 'x@y.com' }), 'A'); assert.equal(P.initialOf({ name: '', email: 'zé@y.com' }), 'Z');

  // Sobre: itens condicionais por env
  assert.deepEqual(P.aboutCards({}, false), []); assert.deepEqual(P.aboutLinks({}), []);
  assert.deepEqual(P.aboutCards({ help_url: 'https://a.com' }, true).map((c) => c.id), ['help', 'tour']);
  assert.deepEqual(P.aboutCards({ help_url: 'https://a.com', contact: site.contact }, true).map((c) => c.id), ['help', 'contact', 'tour']);
  assert.deepEqual(P.aboutLinks({ terms_url: 'https://t.com' }).map((l) => l.id), ['terms']);
  assert.deepEqual(P.aboutLinks({ terms_url: 'https://t.com', privacy_url: 'https://p.com' }).map((l) => l.id), ['terms', 'privacy']);
  assert.equal(P.footerText({}), '© 2026 Kiroo');
  assert.equal(P.footerText({ legal_name: 'Kiroo Ltda', legal_cnpj: '11.222.333/0001-81' }), '© 2026 Kiroo · Kiroo Ltda · CNPJ 11.222.333/0001-81');

  // ---- renderização
  const { CreditsView } = await vite.ssrLoadModule('/src/ui/Credits.jsx');
  const d = { balance: '19', balance_cc: 1999, held: '20', held_cc: 2000, exempt: false, topup: { online: true },
    statement: [
      { id: '1', at: '2026-11-01T10:00:00', title: 'Compra · Pro', subtitle: 'Pix', status: 'paid', status_label: 'Pago', credits: '+600' },
      { id: '2', at: '2026-11-02T10:00:00', title: 'Vídeo · Tênis', subtitle: 'Estilo Claro', status: 'done', status_label: 'Concluído', credits: '−20' },
      { id: '3', at: '2026-11-03T10:00:00', title: 'Vídeo · Mochila', subtitle: 'Estilo Escuro', status: 'not_charged', status_label: 'Não cobrado', credits: '0' }],
    videos: [{ production_id: 'p1', at: '2026-11-02T10:00:00', product: 'Tênis', style: 'Estilo Claro', credits: '20', status: 'done', status_label: 'Concluído' }] };
  const cv = (props) => renderToStaticMarkup(h(CreditsView, { d, plan: pro, tab: 'extrato', setTab() {}, onBuy() {}, onPackages() {}, ...props }));
  let html = cv();
  assert.match(html, /<strong>19<\/strong><span>créditos<\/span>/);
  assert.match(html, /20 reservados para vídeos em andamento/);
  assert.match(html, />Comprar créditos<\/button>/); assert.match(html, /class="pf-plan">PRO</); assert.match(html, />Ver pacotes</);
  assert.ok(!/Fila prioritária/.test(html));                                       // sem lista de vantagens no card de créditos
  assert.match(html, /role="tab" class="pf-tab" aria-selected="true">Extrato/); assert.match(html, /Baixar extrato/);
  assert.match(html, /<th scope="col">Data<\/th><th scope="col">Descrição<\/th><th scope="col">Status<\/th><th scope="col">Créditos<\/th>/);
  assert.match(html, /color:#166534;background:#DCFCE7">Pago/); assert.match(html, /color:#9A3412;background:#FFEDD5">Não cobrado/);
  assert.ok(!/chamada|takes|etapa/i.test(html.replace(/Falhas técnicas[^<]*/, '')));
  assert.match(html, /Falhas técnicas não são cobradas\. Ao criar um vídeo, os créditos ficam reservados e só são descontados quando ele fica pronto\./);
  html = cv({ tab: 'video' });
  assert.match(html, /Tênis/); assert.match(html, /Estilo Claro/); assert.match(html, /aria-selected="true">Por vídeo/);
  html = cv({ d: { ...d, held: '0', held_cc: 0 }, plan: free });
  assert.match(html, /Nada reservado no momento/); assert.match(html, /class="pf-plan">FREE</);

  const { AccountView } = await vite.ssrLoadModule('/src/ui/Account.jsx');
  const acct = (plan, over = {}) => ({ user: { name: 'Ana Souza', email: 'ana@exemplo.com', email_verified: true, has_password: true, tax_doc: '', ...over }, plan, payments: { online: true } });
  const av = (a, props = {}) => renderToStaticMarkup(h(AccountView, { a, site, edit: null, setEdit() {}, onSave() {}, onVerify() {}, onCode() {}, onLogout() {}, onDelete() {}, openPackages() {}, del: false, setDel() {}, ...props }));
  html = av(acct(pro));
  assert.match(html, />A</); assert.match(html, /Verificado/); assert.match(html, /Editar perfil/);
  assert.match(html, /Fila prioritária/); assert.match(html, /Suporte por WhatsApp/); assert.ok(!/Acesso antecipado a novidades/.test(html));
  assert.match(html, /Falar no WhatsApp/); assert.match(html, /href="https:\/\/wa\.me\/5511999990000"/);
  assert.match(html, /••••••••••/); assert.match(html, /Não informado/); assert.match(html, />Adicionar</);
  assert.match(html, />Sair</); assert.match(html, /Excluir conta/);
  assert.match(av(acct(esc)), /Acesso antecipado a novidades/);
  html = av(acct(free, { email_verified: false, tax_doc: '•••.•••.•••-25' }));
  assert.ok(!/Fila prioritária|Falar no WhatsApp/.test(html)); assert.match(html, /Fale com a gente por e-mail/); assert.match(html, /ajuda@exemplo\.com/);
  assert.match(html, /Confirmar e-mail/); assert.ok(!/Verificado/.test(html)); assert.match(html, /•••\.•••\.•••-25/); assert.ok(!/Não informado/.test(html));
  html = av(acct(free), { del: true });
  assert.match(html, /Digite seu e-mail para confirmar|Digite <strong>ana@exemplo\.com<\/strong>/); assert.match(html, /disabled=""[^>]*>Excluir conta/);

  const { AboutView } = await vite.ssrLoadModule('/src/ui/About.jsx');
  const ab = (s, tour = true) => renderToStaticMarkup(h(AboutView, { site: s, hasTour: tour, onTour() {} }));
  html = ab({});
  assert.match(html, /Seu estúdio ganha vida\./); assert.match(html, /Vídeos de produto com narração, foto, título e legenda, a partir de uma foto\./);
  assert.ok(!/Arte da sede|Cenário de fundo|LimeZu|Forest of Illusion/.test(html));
  assert.ok(!/Versão|O que há de novo|Central de ajuda|Fale com a gente|Termos de uso|Política de privacidade|CNPJ/.test(html));
  assert.match(html, /Rever tutorial/); assert.match(html, /© 2026 Kiroo<\/span>/); assert.match(html, /Feito no Brasil/);
  assert.match(html, /--n:1/);
  html = ab({ version: '3e3373c', changelog_url: 'https://x.com/n', help_url: 'https://x.com/a', contact: site.contact, terms_url: 'https://x.com/t', privacy_url: 'https://x.com/p', legal_name: 'Kiroo Ltda', legal_cnpj: '11.222.333/0001-81' });
  assert.match(html, /Versão 3e3373c/); assert.match(html, /O que há de novo/); assert.match(html, /Central de ajuda/); assert.match(html, /Fale com a gente/);
  assert.match(html, /--n:3/); assert.match(html, /Termos de uso/); assert.match(html, /Política de privacidade/);
  assert.match(html, /© 2026 Kiroo · Kiroo Ltda · CNPJ 11\.222\.333\/0001-81/);
  console.log('ok prefs');
} finally { await vite.close(); }
