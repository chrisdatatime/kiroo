// Configurações (Perfil | Créditos): lógica pura, sem React (tests/settings.test.mjs).
import { ORIGIN_NOTES, VIDEO_CREDITS } from '../config/appConfig.js';

export const SETTINGS_TABS = [{ id: 'perfil', label: 'Perfil' }, { id: 'creditos', label: 'Créditos' }];

// Barra de uma origem: quanto resta do que entrou (0–100). Nada entrou: 0.
export function barPct(o) {
  const got = Number(o && o.received_cc) || 0, left = Number(o && o.left_cc) || 0;
  if (got <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((left / got) * 100)));
}

// Linhas das barras por origem (vindas de /api/credits → origins), com a nota de configuração de cada uma.
export function originRows(origins) {
  return (origins || []).map((o) => ({ key: o.key, label: o.label, note: ORIGIN_NOTES[o.key] || '', left: o.left, received: o.received,
    pct: barPct(o), accent: o.key === 'bonus' }));
}

// "Cada vídeo usa 20 créditos. Com o saldo atual, dá para ≈ 4 vídeos."
export function balanceSentence(d, perVideo = VIDEO_CREDITS) {
  if (!d) return '';
  if (d.exempt) return 'Conta isenta: o consumo é registrado, mas não precisa de saldo.';
  const cc = Number(d.balance_cc);
  const n = Number.isFinite(cc) ? Math.max(0, Math.floor(cc / 100 / perVideo)) : 0;
  return { lead: `Cada vídeo usa ${perVideo} créditos. Com o saldo atual, dá para`, strong: `≈ ${n} ${n === 1 ? 'vídeo' : 'vídeos'}` };
}

const pad = (n) => String(n).padStart(2, '0');
// Data curta do extrato: "15/11".
export function shortDate(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? `${pad(d.getDate())}/${pad(d.getMonth() + 1)}` : '';
}

// Linha do extrato: "Produção · Skate", valor com sinal e o tom (entrada verde, saída tinta, sem custo cinza).
export function statementLine(e) {
  const title = [e.title, e.subtitle].filter(Boolean).join(' · ');
  const amt = String(e.credits == null ? '0' : e.credits);
  const tone = amt.startsWith('+') ? 'in' : (amt.startsWith('−') || amt.startsWith('-')) ? 'out' : 'zero';
  const status = e.status && !['done', 'paid', 'gift'].includes(e.status) ? e.status_label || '' : '';
  return { id: e.id, date: shortDate(e.at), title, amount: amt, tone, status };
}

// Formulário do perfil: o que mudou (só manda o que mudou). CPF/CNPJ vazio = mantém o atual.
export function profileChanges(user, form) {
  const out = {};
  const name = String(form.name || '').replace(/\s+/g, ' ').trim();
  if (name && name !== String((user && user.name) || '').trim()) out.name = name;
  const doc = String(form.tax || '').trim();
  if (doc) out.tax = doc;
  return out;
}
