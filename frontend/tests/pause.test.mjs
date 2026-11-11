import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { adjustmentGate, pauseKind } from '../src/ui/pause.js';

// freio interno (código estável): "estamos finalizando", nunca pedido de upgrade
assert.equal(pauseKind('ops_budget_reached', 'Estamos finalizando seu vídeo.'), 'finalizando');
// pausas antigas pelo orçamento da produção (sem código) também não pedem dinheiro
assert.equal(pauseKind(null, 'orçamento insuficiente para image da cena 2: ...'), 'finalizando');
assert.equal(pauseKind(null, ''), 'finalizando');

// os outros motivos continuam com a saída de cada um
assert.equal(pauseKind('provider_billing', 'x'), 'provedor');
assert.equal(pauseKind('monthly_cap', 'x'), 'mensal');
assert.equal(pauseKind('credits_insufficient', 'x'), 'saldo');
assert.equal(pauseKind('paid_gate:kill_switch', 'x'), 'outro');
assert.equal(pauseKind(null, 'provedor de IA sem saldo: 429'), 'provedor');
assert.equal(pauseKind(null, 'teto mensal atingido para image'), 'mensal');
assert.equal(pauseKind(null, 'saldo de créditos insuficiente para image'), 'saldo');
assert.equal(pauseKind(null, 'pausa manual'), 'outro');

// ajustes: incluído não pede nada; extra pede autorização com o custo visível; produção antiga não tem a regra
assert.deepEqual(adjustmentGate({ free_left: 1, extra_cost_credits: { image: 18, video: 17 } }, 'image'), { needsAuth: false, cost: 0 });
assert.deepEqual(adjustmentGate({ free_left: 0, extra_cost_credits: { image: 18, video: 17 } }, 'video'), { needsAuth: true, cost: 17 });
assert.deepEqual(adjustmentGate(null, 'image'), { needsAuth: false, cost: 0 });

// a tela de pausa não oferece mais "Subir limite" da produção ao cliente
const win = readFileSync(new URL('../src/ui/ProdWindow.jsx', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
assert.ok(!/Subir limite/.test(win), 'ProdWindow ainda oferece "Subir limite"');
assert.ok(!/raiseLimit|\/budget`/.test(app + win), 'cliente ainda chama a rota de limite da produção');
assert.ok(/Estamos finalizando/.test(win));

console.log('ok: pause');
