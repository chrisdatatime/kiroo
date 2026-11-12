// Por que a produção pausou? Decide pelo CÓDIGO estável do servidor (pause_code); o texto só vale para
// produções antigas, que pausaram antes de existir o código.
//
// Regra do produto: o orçamento operacional da produção é um freio INTERNO do Kiroo. Quando ele pausa, o cliente
// vê "estamos finalizando" — nunca um botão para pagar mais para terminar o que foi prometido.

export const OPS_BUDGET_REACHED = 'ops_budget_reached';

export function pauseKind(code, reason) {
  const c = code || '';
  if (c === OPS_BUDGET_REACHED) return 'finalizando';
  if (c === 'provider_billing') return 'provedor';
  if (c === 'monthly_cap') return 'mensal';
  if (c === 'credits_insufficient') return 'saldo';
  if (c.startsWith('paid_gate')) return 'outro';
  const r = reason || '';
  if (/provedor de IA sem saldo/i.test(r)) return 'provedor';
  if (/teto mensal/i.test(r)) return 'mensal';
  if (/saldo de créditos/i.test(r)) return 'saldo';
  // Pausa antiga pelo orçamento da produção: também é freio interno — o cliente não paga para terminar.
  if (!r || /orçamento/i.test(r)) return 'finalizando';
  return 'outro';
}

// Ajuste pedido pelo cliente numa cena: incluído (sem custo extra) ou extra (precisa de autorização com o custo).
// `adj` vem do servidor (scene.adjustments); produções antigas não têm a regra (null) e seguem como antes.
export function adjustmentGate(adj, stage) {
  if (!adj) return { needsAuth: false, cost: 0 };
  if (adj.free_left > 0) return { needsAuth: false, cost: 0 };
  return { needsAuth: true, cost: (adj.extra_cost_credits || {})[stage] || 0 };
}
