import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CONFIRM_LABEL, NO_EXTRA_COST, balanceLabel, needsConfirmation, summaryRows, usedLabel } from '../src/ui/nextVideo.js';

const sm = {
  product: 'Copo com alça', format: '9:16', scenes: 3, included_adjustments_per_scene: 1,
  total_cc: 15741, total_credits: '157,41', total_brl: null, balance_cc: 50000, balance: '500', exempt: false,
  balance_after: '342,59', no_extra_cost: NO_EXTRA_COST,
};
const rows = Object.fromEntries(summaryRows(sm));

// o resumo traz produto, formato, cenas, ajustes incluídos, custo total e saldo
assert.equal(rows['Produto'], 'Copo com alça');
assert.equal(rows['Formato'], '9:16 (vertical)');
assert.equal(rows['Cenas'], '3');
assert.equal(rows['Ajustes incluídos por cena'], '1');
assert.equal(rows['Custo total autorizado'], '157,41 créditos');
assert.equal(rows['Saldo atual'], '500 créditos');
assert.equal(rows['Saldo depois de reservar'], '342,59 créditos');
assert.equal(NO_EXTRA_COST, 'Nenhum custo adicional será aplicado sem sua autorização.');
assert.equal(CONFIRM_LABEL, 'Confirmar e criar vídeo');

// sem tabela de preço configurada (total_brl nulo) não aparece R$ em lugar nenhum; com ela, aparece
assert.ok(!JSON.stringify(summaryRows(sm)).includes('R$'));
assert.equal(summaryRows({ ...sm, total_brl: '78,71' }).find(([k]) => k === 'Custo total autorizado')[1], '157,41 créditos (≈ R$ 78,71)');

// conta isenta: sem saldo numérico
const ex = Object.fromEntries(summaryRows({ ...sm, exempt: true }));
assert.equal(ex['Saldo atual'], 'Conta isenta');
assert.ok(!('Saldo depois de reservar' in ex));

// o resumo só aparece enquanto há confirmação pendente (DEMO e produções antigas: nunca)
assert.equal(needsConfirmation({ confirmation: { required: true, confirmed: false, summary: sm } }), true);
assert.equal(needsConfirmation({ confirmation: { required: true, confirmed: true, summary: sm } }), false);
assert.equal(needsConfirmation({ confirmation: { required: false, confirmed: true, summary: null } }), false);
assert.equal(needsConfirmation({}), false);
assert.equal(needsConfirmation(null), false);

// rótulos: "Saldo" e "Usado neste vídeo", nunca "X de Y créditos"
assert.equal(balanceLabel({ balance: '500', exempt: false }), 'Saldo: 500');
assert.equal(balanceLabel({ exempt: true }), 'Saldo: isento');
assert.equal(balanceLabel(null), '');
assert.equal(usedLabel({ spent: 70, budget: 80 }), 'Usado neste vídeo: 70');
assert.ok(!/ de \d/.test(usedLabel({ spent: 70, budget: 80 })));

// nenhuma tela oferece "Subir limite" nem mostra "gasto de limite" ao cliente
const read = (f) => readFileSync(new URL('../src/' + f, import.meta.url), 'utf8');
const screens = ['App.jsx', 'ui/ProdWindow.jsx', 'ui/Hud.jsx', 'shell/Central.jsx', 'shell/MissionView.jsx', 'ui/Pilot.jsx', 'landing/Landing.jsx'].map(read).join('\n');
assert.ok(!/Subir limite/i.test(screens), '"Subir limite" ainda aparece');
assert.ok(!/credits\.budget|P\.credits\.budget/.test(screens), 'a tela ainda usa o limite da produção como rótulo');
assert.ok(!/Limite desta produção/i.test(screens));
assert.ok(!/' de ' \+ cr\(/.test(screens), 'ainda monta "X de Y créditos"');
assert.ok(/Usado neste vídeo/.test(screens) && /Seu próximo vídeo/.test(screens));

// a confirmação autoriza o valor visto ANTES de mandar a direção (e só em produção com resumo pendente)
const app = read('App.jsx');
const i = app.indexOf('/confirm`'), j = app.indexOf('/direction`', i);
assert.ok(i > 0 && j > i, 'confirm deve vir antes de direction');
assert.ok(/needsConfirmation\(P\) \? P\.confirmation\.summary\.total_cc : null/.test(app));

console.log('ok: nextVideo');
