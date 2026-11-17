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

// as telas usam esses textos; a compra online (Stripe) é pela tela de Planos, não por estas janelas
const read = (f) => readFileSync(new URL('../src/' + f, import.meta.url), 'utf8');
const pw = read('ui/ProdWindow.jsx'), cr = read('ui/Credits.jsx'), tu = read('ui/TopUp.jsx'), app = read('App.jsx');
assert.ok(/NoBalance/.test(pw) && /KEEP_LABEL/.test(pw) && /ADD_LABEL/.test(pw));
// o cliente não vê o detalhe por chamada/etapa (só no admin): a tela não usa usageRows nem o consumo por produção
assert.ok(/ADD_LABEL/.test(cr) && !/usageRows|\.usage/.test(cr) && /reservedText/.test(cr));
assert.ok(/credits\/topup/.test(tu) && /Stripe/.test(tu) && !/Mercado Pago/.test(tu));
assert.ok(/noBalanceFromError/.test(app) && /adjustFunds/.test(app));
// sem saldo o ajuste não pede autorização: a checagem vem antes de abrir a confirmação
assert.ok(app.indexOf('adjustFunds({ costCc') < app.indexOf('this.setUI({ confirmExtra: { scene: idx'));
assert.ok(!/Já tenho créditos: retomar/.test(pw));

console.log('ok: credits');

// Comprar créditos (ui/buy.js, Asaas: Pix QR, CPF, limites de cartão) saiu na Fase 6: a compra é a tela de Planos
// (shell/pricing.js), testada em tests/pricing.test.mjs.

// ---------------------------------------------------------------- saldo inteiro, arredondado para baixo (só exibição)
{
  const { fmtBalance, noBalanceNotice: nb } = await import('../src/ui/credits.js');
  assert.equal(fmtBalance(1999), '19');
  assert.equal(fmtBalance(2000), '20');
  assert.equal(fmtBalance(0), '0');
  assert.equal(fmtBalance(-40), '−1');
  assert.equal(fmtBalance(200000), '2.000');
  assert.equal(nb({ scene: 1, costCc: 2000, balanceCc: 1999 }).balance, '19');
  console.log('ok: saldo inteiro');
}

// ---------------------------------------------------------------- bônus de boas-vindas (ui/welcome.js)
{
  const W = await import('../src/ui/welcome.js');
  const acc = { welcome: { credits: 20, granted_at: '2026-11-14T10:00:00+00:00' } };
  assert.deepEqual(W.emptyMissionsCopy(acc, []), { title: 'Seus 20 créditos estão esperando.',
    text: 'Solte a foto do seu produto e veja o vídeo pronto em 3 minutos.', cta: 'Criar meu primeiro vídeo' });
  assert.equal(W.emptyMissionsCopy(acc, [{ id: 'p1' }]), null);
  assert.equal(W.emptyMissionsCopy({ welcome: null }, []), null);
  const P = { status: 'awaiting_final_review' };
  const low = { balance_cc: 0, exempt: false };
  // faixa do primeiro vídeo: texto vem de config/appConfig.js, sem valor em reais e sem "pacotes"
  const copy = W.firstVideoCopy({ P, productions: [P], wallet: low });
  assert.equal(copy.text, 'Seu produto já tem um vídeo pronto para vender. Que tal dar o mesmo impulso ao próximo da sua loja?');
  assert.equal(copy.cta, 'Criar outro vídeo');
  assert.doesNotMatch(copy.text + copy.cta, /R\$|vendendo sozinho|pacote/i);
  assert.ok(W.firstVideoCopy({ P, productions: [P], wallet: { balance_cc: 2000 } }), 'aparece também com saldo (o fluxo de nova produção cuida da compra)');
  assert.ok(W.firstVideoCopy({ P: { status: 'completed' }, productions: [{ status: 'completed' }], wallet: null }));
  assert.equal(W.firstVideoCopy({ P, productions: [P, { status: 'completed' }], wallet: low }), null); // não é o primeiro
  assert.equal(W.firstVideoCopy({ P: { status: 'producing' }, productions: [P], wallet: low }), null);
  assert.equal(W.firstVideoCopy({ P, productions: [P], wallet: { balance_cc: 0, exempt: true } }), null);
  assert.equal(W.NO_BALANCE_CREATE, 'Você já sabe o resultado. Escolha quantos vídeos quer fazer este mês.');
  assert.ok(W.isNoFunds({ status: 402 }) && W.isNoFunds({ data: { insufficient_credits: true } }) && !W.isNoFunds({ status: 400 }));
  console.log('ok: bônus de boas-vindas');
}

// saldo insuficiente ao criar (402): a criação devolve noFunds e o App troca pelo convite dos pacotes
{
  const { startFal } = await import('../src/ui/falFlow.js');
  const r = await startFal(async () => { throw Object.assign(new Error('Este vídeo custa 20 créditos e o saldo do estúdio é 0.'), { status: 402, data: { insufficient_credits: true } }); }, { body: {}, cc: 2000 });
  assert.equal(r.ok, false);
  assert.equal(r.noFunds, true);
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.ok(/r\.noFunds \? NO_BALANCE_CREATE : r\.error/.test(app));
  console.log('ok: saldo insuficiente ao criar');
}
