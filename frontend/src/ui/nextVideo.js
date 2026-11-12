// "Seu próximo vídeo": resumo mostrado ANTES de gastar (lógica pura, testada em tests/nextVideo.test.mjs).
// Os números vêm prontos do servidor (production.confirmation.summary); aqui só viram linhas rotuladas.

export const CONFIRM_LABEL = 'Confirmar e criar vídeo';
export const NO_EXTRA_COST = 'Nenhum custo adicional será aplicado sem sua autorização.';

export const plural = (n, one, many) => `${n} ${Number(n) === 1 ? one : many}`;
export const credits = (txt) => `${txt} ${txt === '1' ? 'crédito' : 'créditos'}`;

// A confirmação só existe em produção real com pré-orçamento (o servidor diz). Sem ela (DEMO, produção antiga) nada muda.
export function needsConfirmation(P) {
  const c = P && P.confirmation;
  return !!(c && c.required && !c.confirmed && c.summary);
}

// Linhas do resumo, na ordem em que o cliente lê. R$ só aparece se o servidor mandar (preço do crédito configurado).
export function summaryRows(sm) {
  const rows = [
    ['Produto', sm.product],
    ['Formato', `${sm.format} (vertical)`],
    ['Cenas', String(sm.scenes)],
    ['Ajustes incluídos por cena', String(sm.included_adjustments_per_scene)],
    ['Custo total autorizado', credits(sm.total_credits) + (sm.total_brl ? ` (≈ R$ ${sm.total_brl})` : '')],
    ['Saldo atual', sm.exempt ? 'Conta isenta' : credits(sm.balance)],
  ];
  if (!sm.exempt) rows.push(['Saldo depois de reservar', credits(sm.balance_after)]);
  return rows;
}

// Indicador discreto de saldo no cabeçalho (nunca "X de Y créditos").
export function balanceLabel(wallet) {
  if (!wallet) return '';
  return wallet.exempt ? 'Saldo: isento' : `Saldo: ${wallet.balance}`;
}

// "Usado neste vídeo" é o consumo real do vídeo; o limite operacional nunca aparece para o cliente.
export function usedLabel(credits_) {
  return `Usado neste vídeo: ${credits_ ? credits_.spent : 0}`;
}
