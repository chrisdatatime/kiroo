// Créditos: contas e rótulos da tela "Créditos e extrato" e do aviso "Saldo insuficiente para um novo ajuste".
// Lógica pura (tests/credits.test.mjs). Valores em centésimos de crédito (cc), como o servidor guarda.

export const NO_BALANCE_TITLE = 'Saldo insuficiente para um novo ajuste';
export const KEEP_LABEL = 'Manter meu vídeo como está';
export const ADD_LABEL = 'Adicionar créditos';

// 1850 → "18,50"; 1800 → "18" (mesmo formato do servidor)
export function fmtCc(cc) {
  const n = Math.abs(Number(cc) || 0) / 100;
  let s = n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (s.endsWith(',00')) s = s.slice(0, -3);
  return (cc < 0 ? '−' : '') + s;
}

// Dá para pagar um ajuste extra com o saldo livre? Conta isenta nunca fica sem saldo. Nunca devolve "faltam" negativo.
export function adjustFunds({ costCc, balanceCc, exempt }) {
  const cost = Math.max(Number(costCc) || 0, 0), bal = Number(balanceCc) || 0;
  if (exempt) return { enough: true, missingCc: 0 };
  return { enough: bal >= cost, missingCc: Math.max(cost - bal, 0) };
}

// Monta o aviso a partir da conta feita no navegador (antes de pedir ao servidor)...
export function noBalanceNotice({ scene, costCc, balanceCc, topup }) {
  const missing = Math.max(costCc - balanceCc, 0);
  return { scene, balance_cc: balanceCc, cost_cc: costCc, missing_cc: missing,
    balance: fmtCc(balanceCc), cost: fmtCc(costCc), missing: fmtCc(missing), topup: topup || null };
}

// ...ou aproveita a resposta 402 do servidor (a fonte da verdade quando as duas contas divergem).
export function noBalanceFromError(err, scene) {
  const d = err && err.data;
  if (!d || !d.insufficient_credits || d.kind !== 'adjustment') return null;
  return { scene, balance_cc: d.balance_cc, cost_cc: d.cost_cc, missing_cc: d.missing_cc,
    balance: d.balance, cost: d.cost, missing: d.missing, topup: d.topup || null };
}

// Linhas da conta mostradas no aviso.
export function noBalanceRows(n) {
  return [['Seu saldo', `${n.balance} créditos`], ['Custo do ajuste', `${n.cost} créditos`], ['Faltam', `${n.missing} créditos`]];
}

// Contato de "Adicionar créditos": só abre link http(s) ou mailto; qualquer outra coisa vira texto.
export function safeHref(href) {
  return typeof href === 'string' && /^(https:\/\/|mailto:)/i.test(href) ? href : null;
}

// Consumo de uma produção em linhas: cena → operações. Cena nula = roteiro e conferências gerais.
export function usageRows(u) {
  return (u.scenes || []).map((s) => ({
    key: s.scene === null || s.scene === undefined ? 'geral' : 'cena-' + s.scene,
    title: s.scene === null || s.scene === undefined ? 'Roteiro e conferências gerais' : 'Cena ' + s.scene,
    credits: s.credits, operations: s.operations,
  }));
}
