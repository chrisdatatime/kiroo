// Aba Administrador: lógica pura (tests/admin.test.mjs). A autorização é SEMPRE do servidor (/api/admin/* responde 404
// para quem não é administrador); aqui só se decide o que mostrar e o texto das confirmações.
import { fmtCc } from './credits.js';

// A aba só existe no menu para administrador da plataforma (/api/me.admin === true). Qualquer outra coisa esconde.
export const adminTabVisible = (account) => !!account && account.admin === true;

// Chave de idempotência por intenção de lançamento: o duplo clique reusa a mesma chave e o servidor não credita duas vezes.
export function newIdemKey(rand = Math.random, now = Date.now) {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return 'adm-' + c.randomUUID();
  return 'adm-' + now().toString(36) + '-' + Array.from({ length: 4 }, () => Math.floor(rand() * 1e9).toString(36)).join('');
}

export const usd = (x) => (x === null || x === undefined ? '—' : 'US$ ' + Number(x).toFixed(2));

// Créditos digitados ("12,5" ou "12.5") → número; NaN se inválido.
export function parseCredits(text) {
  const t = String(text ?? '').trim().replace(/\s/g, '').replace(',', '.');
  if (!/^[-+]?\d+(\.\d{1,2})?$/.test(t)) return NaN;
  return Number(t);
}

// Conferência no navegador antes de pedir (o servidor confere de novo). limits: {max_grant, left_today_cc}
export function checkCredits(kind, credits, limits) {
  if (!Number.isFinite(credits)) return 'Digite um número de créditos (até 2 casas).';
  if (kind === 'grant' && credits <= 0) return 'A concessão precisa ser positiva. Para tirar créditos, use o ajuste.';
  if (kind === 'adjust' && credits === 0) return 'O ajuste precisa ser diferente de zero.';
  if (limits && Math.abs(credits) > limits.max_grant) return `Acima de ${limits.max_grant} créditos por lançamento: só pela CLI.`;
  if (limits && credits > 0 && Math.round(credits * 100) > limits.left_today_cc) return `Passa do seu limite diário (restam ${fmtCc(limits.left_today_cc)} créditos hoje): só pela CLI.`;
  return null;
}

// Pede para digitar o e-mail da conta alvo? (ajuste negativo; apagar conta não existe no site)
export const needsTypedEmail = (action, input) => action === 'adjust' && Number(input?.credits) < 0;

// Motivo obrigatório? (créditos sempre; mexer na própria conta subindo teto/saldo/modo também)
export function needsReason(action, { self = false, input = {}, account = {} } = {}) {
  if (action === 'grant' || action === 'adjust') return true;
  if (!self) return false;
  if (action === 'allow-real') return !account.allow_real;
  if (action === 'set-mode') return input.mode === 'real' && account.mode !== 'real';
  if (action === 'set-cap') return Number(input.usd) > Number(account.monthly_cap_usd || 0);
  return false;
}

// Resumo do efeito mostrado no modal de confirmação. financial = aviso de efeito financeiro em destaque.
export function confirmSpec(action, account, input = {}, { self = false } = {}) {
  const who = account ? `${account.email} (${account.workspace?.name || 'estúdio'})` : '';
  const c = Number(input.credits);
  const specs = {
    'allow-real': { title: 'Liberar o modo real', financial: true,
      lines: [`Conta: ${who}`, 'O estúdio poderá gerar com IA real (custo de verdade, dentro do teto efetivo).', 'Ainda é preciso ligar o modo real e ter teto > 0.'] },
    'deny-real': { title: 'Bloquear o modo real', financial: false,
      lines: [`Conta: ${who}`, 'O estúdio volta para DEMO e não gera custo.'] },
    'set-mode': { title: `Trocar o modo para ${input.mode === 'real' ? 'REAL' : 'DEMO'}`, financial: input.mode === 'real',
      lines: [`Conta: ${who}`, `Modo: ${account?.mode === 'real' ? 'REAL' : 'DEMO'} → ${input.mode === 'real' ? 'REAL' : 'DEMO'}`,
        input.mode === 'real' ? 'Produções novas deste estúdio passam a gerar custo real.' : 'Produções novas ficam sem custo (DEMO).'] },
    'set-cap': { title: 'Definir o teto mensal', financial: true,
      lines: [`Conta: ${who}`, `Teto: ${usd(account?.monthly_cap_usd)} → ${usd(Number(input.usd))}`, 'Nunca acima do teto da plataforma; vale o menor dos dois.'] },
    grant: { title: 'Conceder créditos', financial: true,
      lines: [`Conta: ${who}`, `+${fmtCc(Math.round(c * 100))} créditos`, `Saldo: ${account?.balance ?? '?'} → ${fmtCc((account?.balance_cc || 0) + Math.round(c * 100))}`] },
    adjust: { title: c < 0 ? 'Tirar créditos (ajuste negativo)' : 'Ajustar créditos', financial: true,
      lines: [`Conta: ${who}`, `${c > 0 ? '+' : ''}${fmtCc(Math.round(c * 100))} créditos`, `Saldo: ${account?.balance ?? '?'} → ${fmtCc((account?.balance_cc || 0) + Math.round(c * 100))}`] },
    'verify-email': { title: 'Confirmar o e-mail à mão', financial: false,
      lines: [`Conta: ${who}`, 'Só depois de conferir com a pessoa por outro canal.'] },
    'reset-link': { title: 'Gerar link de nova senha', financial: false,
      lines: [`Conta: ${who}`, 'Vale 30 minutos e uma vez; invalida o link anterior. Aparece uma única vez.', 'Entregue por canal privado.'] },
    export: { title: 'Exportar os dados da conta', financial: false,
      lines: [`Conta: ${who}`, 'O arquivo tem dados pessoais: guarde com cuidado e apague depois.'] },
    'create-invite': { title: 'Criar convite', financial: false,
      lines: [`Validade: ${input.days} dia(s)`, input.email ? `Só para ${input.email}` : 'Qualquer e-mail', 'O código aparece UMA vez.'] },
    'revoke-invite': { title: 'Revogar convite', financial: false, lines: [`Convite ${input.id}`] },
  };
  const s = specs[action] || { title: action, financial: false, lines: [] };
  return { ...s, self, lines: self ? [...s.lines, 'Atenção: esta é a SUA conta. A ação fica em destaque na auditoria.'] : s.lines,
    typeEmail: needsTypedEmail(action, input) ? account?.email : null,
    reason: needsReason(action, { self, input, account }) };
}

// Linha da auditoria em texto curto.
export function auditLine(e) {
  const amount = e.amount_cc === null || e.amount_cc === undefined ? '' : ` ${e.amount_cc > 0 ? '+' : ''}${fmtCc(e.amount_cc)} créditos`;
  const result = { ok: '', refused: ' (recusada)', duplicate: ' (repetida, sem efeito)' }[e.result] ?? ` (${e.result})`;
  return `${e.action}${amount}${result}`;
}

// Erro do servidor que pede reautenticação.
export const isReauthError = (err) => !!err && err.status === 403 && err.data && err.data.code === 'reauth_required';
