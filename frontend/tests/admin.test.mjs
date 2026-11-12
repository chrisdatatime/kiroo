import assert from 'node:assert/strict';
import { adminTabVisible, auditLine, checkCredits, confirmSpec, isReauthError, needsReason, needsTypedEmail, newIdemKey, parseCredits } from '../src/ui/admin.js';

// a aba só aparece para administrador da plataforma
assert.equal(adminTabVisible({ admin: true }), true);
for (const a of [null, undefined, {}, { admin: false }, { admin: 'true' }, { admin: 1 }]) assert.equal(adminTabVisible(a), false);

// chave de idempotência: formato aceito pelo servidor e diferente a cada intenção
const k1 = newIdemKey(), k2 = newIdemKey();
assert.match(k1, /^[A-Za-z0-9_-]{8,80}$/);
assert.notEqual(k1, k2);

// créditos digitados
assert.equal(parseCredits('12,5'), 12.5);
assert.equal(parseCredits('-20'), -20);
assert.ok(Number.isNaN(parseCredits('1e3')));
assert.ok(Number.isNaN(parseCredits('10,123')));

// limites: por lançamento e por dia (o servidor confere de novo)
const limits = { max_grant: 200, left_today_cc: 15000 };
assert.equal(checkCredits('grant', 100, limits), null);
assert.match(checkCredits('grant', 201, limits), /CLI/);
assert.match(checkCredits('grant', 151, limits), /limite diário/);
assert.match(checkCredits('adjust', -201, limits), /CLI/);
assert.equal(checkCredits('adjust', -150, limits), null);   // ajuste negativo não consome o limite diário
assert.match(checkCredits('grant', -1, limits), /positiva/);
assert.match(checkCredits('adjust', 0, limits), /diferente de zero/);

// confirmação: e-mail digitado só no ajuste negativo; motivo nos créditos e ao subir a própria conta
assert.equal(needsTypedEmail('adjust', { credits: -5 }), true);
assert.equal(needsTypedEmail('adjust', { credits: 5 }), false);
assert.equal(needsTypedEmail('grant', { credits: 5 }), false);
assert.equal(needsReason('grant'), true);
assert.equal(needsReason('set-cap', { self: true, input: { usd: 5 }, account: { monthly_cap_usd: 1 } }), true);
assert.equal(needsReason('set-cap', { self: true, input: { usd: 0 }, account: { monthly_cap_usd: 1 } }), false);
assert.equal(needsReason('set-cap', { self: false, input: { usd: 5 }, account: { monthly_cap_usd: 1 } }), false);

const acc = { email: 'ana@exemplo.com', workspace: { name: 'Estúdio da Ana' }, balance: '10', balance_cc: 1000, mode: 'simulated', monthly_cap_usd: 0 };
const neg = confirmSpec('adjust', acc, { credits: -3 });
assert.equal(neg.typeEmail, 'ana@exemplo.com');
assert.equal(neg.financial, true);
assert.ok(neg.lines.some((l) => l.includes('10 → 7')));
const mine = confirmSpec('set-cap', acc, { usd: 3 }, { self: true });
assert.ok(mine.lines.at(-1).includes('SUA conta') && mine.reason === true);
assert.equal(confirmSpec('deny-real', acc).financial, false);

// auditoria e reautenticação
assert.equal(auditLine({ action: 'grant', amount_cc: 2000, result: 'ok' }), 'grant +20 créditos');
assert.equal(auditLine({ action: 'grant', amount_cc: 2000, result: 'duplicate' }), 'grant +20 créditos (repetida, sem efeito)');
assert.equal(isReauthError({ status: 403, data: { code: 'reauth_required' } }), true);
assert.equal(isReauthError({ status: 403, data: { code: 'csrf' } }), false);

console.log('admin: ok');
