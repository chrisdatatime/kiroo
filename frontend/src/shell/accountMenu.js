// Menu da conta (popover no desktop, gaveta no celular) e menu lateral: lógica pura, sem React (tests/account-menu.test.mjs).
import { DARK_THEME_ENABLED, LEGAL_PATHS, PRICING_PATH, SUPPORT_EMAIL_FALLBACK, VIDEO_CREDITS, FEATURES } from '../config/appConfig.js';
import { countsOf } from './inicio.js';

const clean = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();

// "Estúdio de Christian": o nome do workspace (o servidor já cria assim); sem nome, monta pelo nome da pessoa.
export function studioName(account) {
  const ws = clean(account && account.workspace && account.workspace.name);
  if (ws) return ws;
  const first = clean(account && account.user && account.user.name).split(' ')[0];
  return first ? `Estúdio de ${first}` : 'Seu estúdio';
}

export function displayName(account) {
  const u = (account && account.user) || {};
  return clean(u.name) || clean(u.email).split('@')[0] || 'Minha conta';
}

// Saldo inteiro como o servidor manda ("80"); conta isenta não tem número.
export function balanceShort(wallet) {
  if (!wallet) return '';
  return wallet.exempt ? 'Isento' : String(wallet.balance);
}
export function balanceLong(wallet) {
  if (!wallet) return '';
  if (wallet.exempt) return 'Isento de créditos';
  const n = Number(String(wallet.balance).replace(/\./g, ''));
  return `${wallet.balance} ${n === 1 ? 'crédito' : 'créditos'}`;
}

// "≈ 4 vídeos" pelo preço fixo do vídeo. Isento ou sem saldo legível: nada.
export function videosApprox(wallet, perVideo = VIDEO_CREDITS) {
  if (!wallet || wallet.exempt || !(perVideo > 0)) return '';
  const cc = Number(wallet.balance_cc);
  const n = Number.isFinite(cc) ? Math.floor(cc / 100 / perVideo) : Math.floor(Number(String(wallet.balance).replace(/\./g, '')) / perVideo);
  if (!Number.isFinite(n) || n < 0) return '';
  return `≈ ${n} ${n === 1 ? 'vídeo' : 'vídeos'}`;
}

// Links legais: na landing (`landing_url` do /api/config, ex. https://kiroo.io); sem ela, no próprio app (o servidor
// também serve /termos e /privacidade). Só aceita https:// como base.
export function legalLinks(landingUrl) {
  const base = /^https:\/\/[^\s/]+$/i.test(clean(landingUrl).replace(/\/+$/, '')) ? clean(landingUrl).replace(/\/+$/, '') : '';
  return [
    { id: 'terms', label: 'Termos de Uso', href: base + LEGAL_PATHS.terms },
    { id: 'privacy', label: 'Política de Privacidade', href: base + LEGAL_PATHS.privacy },
    { id: 'cookies', label: 'Cookies', href: base + LEGAL_PATHS.cookies },
  ];
}

// Contato de suporte já configurado no servidor (STUDIO_SUPPORT_CONTACT → plan.support.email).
export function supportEmail(account) {
  const e = account && account.plan && account.plan.support && account.plan.support.email;
  return clean(e) || SUPPORT_EMAIL_FALLBACK;
}
export function supportHref(account) {
  return `mailto:${supportEmail(account)}?subject=${encodeURIComponent('Suporte Kiroo')}`;
}

// Aparência: com o tema escuro desligado, só "Claro".
export function appearanceOptions(dark = DARK_THEME_ENABLED) {
  return dark
    ? [{ id: 'auto', label: 'Automático' }, { id: 'light', label: 'Claro' }, { id: 'dark', label: 'Escuro' }]
    : [{ id: 'light', label: 'Claro' }];
}
export const appearanceLabel = (id, dark = DARK_THEME_ENABLED) => (appearanceOptions(dark).find((o) => o.id === id) || appearanceOptions(dark)[0]).label;

// Submenu Créditos (desktop e gaveta).
export function creditItems() {
  return [
    { id: 'statement', label: 'Saldo e extrato' },
    { id: 'pricing', label: 'Planos e créditos', href: PRICING_PATH },
    { id: 'receipts', label: 'Recibos', soon: !FEATURES.receipts },
  ];
}

// Menu lateral: Início, Escritório (AO VIVO), Produções (contador de "aguardando você"), Entregas.
// AO VIVO só quando há produção gerando agora (o selo não mente com o estúdio parado).
export function sideNav(v) {
  const c = countsOf(v.productions || []);
  const waiting = c.aprovacao + c.decisao;
  const live = c.gerando > 0;
  const inApp = !v.win || !['account', 'credits'].includes(v.win);
  return [
    { id: 'inicio', label: 'Início', view: 'central', on: v.view === 'central' && inApp },
    { id: 'escritorio', label: 'Escritório', view: 'escritorio', live, on: v.view === 'escritorio' && inApp },
    { id: 'producoes', label: 'Produções', view: 'missao', badge: waiting, on: v.view === 'missao' && inApp },
    { id: 'entregas', label: 'Entregas', view: 'missao', on: false },   // sem tela própria até a Fase 5: abre Produções
  ];
}

// Barra inferior do celular: Início, Escritório, +, Produções, Entregas.
export function phoneTabs(v) {
  const nav = sideNav(v);
  const by = Object.fromEntries(nav.map((x) => [x.id, x]));
  return [by.inicio, by.escritorio, { id: 'nova', label: 'Nova produção', plus: true }, by.producoes, by.entregas];
}

// Navegação por setas na gaveta (o popover do desktop usa a do Radix): próximo índice, com volta.
export function nextIndex(i, n, key) {
  if (n <= 0) return -1;
  if (key === 'ArrowDown') return (i + 1 + n) % n;
  if (key === 'ArrowUp') return (i - 1 + n) % n;
  if (key === 'Home') return 0;
  if (key === 'End') return n - 1;
  return i;
}
