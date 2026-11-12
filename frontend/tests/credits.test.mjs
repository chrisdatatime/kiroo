import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ADD_LABEL, KEEP_LABEL, NO_BALANCE_TITLE, adjustFunds, fmtCc, noBalanceFromError, noBalanceNotice, noBalanceRows, safeHref, usageRows } from '../src/ui/credits.js';

// formato igual ao do servidor
assert.equal(fmtCc(1800), '18');
assert.equal(fmtCc(1850), '18,50');
assert.equal(fmtCc(5), '0,05');
assert.equal(fmtCc(-300), '−3');

// textos fixos do aviso
assert.equal(NO_BALANCE_TITLE, 'Saldo insuficiente para um novo ajuste');
assert.equal(KEEP_LABEL, 'Manter meu vídeo como está');
assert.equal(ADD_LABEL, 'Adicionar créditos');

// saldo x custo do ajuste extra
assert.deepEqual(adjustFunds({ costCc: 1800, balanceCc: 500, exempt: false }), { enough: false, missingCc: 1300 });
assert.deepEqual(adjustFunds({ costCc: 1800, balanceCc: 1800, exempt: false }), { enough: true, missingCc: 0 });
assert.deepEqual(adjustFunds({ costCc: 1800, balanceCc: 9000, exempt: false }), { enough: true, missingCc: 0 });
assert.deepEqual(adjustFunds({ costCc: 1800, balanceCc: -50000, exempt: true }), { enough: true, missingCc: 0 }); // conta isenta

// o aviso mostra saldo, custo e quanto falta
const n = noBalanceNotice({ scene: 2, costCc: 1800, balanceCc: 500 });
assert.deepEqual(noBalanceRows(n), [['Seu saldo', '5 créditos'], ['Custo do ajuste', '18 créditos'], ['Faltam', '13 créditos']]);
assert.equal(noBalanceNotice({ scene: 1, costCc: 100, balanceCc: 900 }).missing_cc, 0); // nunca negativo

// a resposta 402 do servidor vira o mesmo aviso; outros erros não
const err = { data: { insufficient_credits: true, kind: 'adjustment', balance_cc: 500, cost_cc: 1800, missing_cc: 1300, balance: '5', cost: '18', missing: '13', topup: { online: false } } };
assert.deepEqual(noBalanceRows(noBalanceFromError(err, 3)), noBalanceRows(n));
assert.equal(noBalanceFromError(err, 3).scene, 3);
assert.equal(noBalanceFromError({ data: { insufficient_credits: true, kind: 'create' } }, 1), null);
assert.equal(noBalanceFromError(new Error('x'), 1), null);
assert.equal(noBalanceFromError(null, 1), null);

// link de contato: só https ou mailto
assert.equal(safeHref('https://wa.me/55'), 'https://wa.me/55');
assert.equal(safeHref('mailto:a@b.co?subject=x'), 'mailto:a@b.co?subject=x');
assert.equal(safeHref('javascript:alert(1)'), null);
assert.equal(safeHref('http://inseguro'), null);
assert.equal(safeHref(null), null);

// consumo por cena → operação; "sem cena" (roteiro) em linha própria
const rows = usageRows({ scenes: [
  { scene: 1, credits: '20', operations: [{ operation: 'Imagens', credits: '12', calls: 2 }] },
  { scene: null, credits: '1', operations: [{ operation: 'Direção (roteiro)', credits: '1', calls: 1 }] },
] });
assert.deepEqual(rows.map((r) => r.title), ['Cena 1', 'Roteiro e conferências gerais']);
assert.deepEqual(usageRows({}), []);

// as telas usam esses textos e nenhuma sugere pagar online (ainda não existe)
const read = (f) => readFileSync(new URL('../src/' + f, import.meta.url), 'utf8');
const pw = read('ui/ProdWindow.jsx'), cr = read('ui/Credits.jsx'), tu = read('ui/TopUp.jsx'), app = read('App.jsx');
assert.ok(/NoBalance/.test(pw) && /KEEP_LABEL/.test(pw) && /ADD_LABEL/.test(pw));
assert.ok(/ADD_LABEL/.test(cr) && /usageRows/.test(cr) && /Reservado/.test(cr));
assert.ok(/credits\/topup/.test(tu) && /Mercado Pago/.test(tu));
assert.ok(/noBalanceFromError/.test(app) && /adjustFunds/.test(app));
// sem saldo o ajuste não pede autorização: a checagem vem antes de abrir a confirmação
assert.ok(app.indexOf('adjustFunds({ costCc') < app.indexOf('this.setUI({ confirmExtra: { scene: idx'));
assert.ok(!/Já tenho créditos: retomar/.test(pw));

console.log('ok: credits');
