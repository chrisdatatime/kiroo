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
// o cliente não vê o detalhe por chamada/etapa (só no admin): a tela não usa usageRows nem o consumo por produção
assert.ok(/ADD_LABEL/.test(cr) && !/usageRows|\.usage/.test(cr) && /reservedText/.test(cr));
assert.ok(/credits\/topup/.test(tu) && /Mercado Pago/.test(tu));
assert.ok(/noBalanceFromError/.test(app) && /adjustFunds/.test(app));
// sem saldo o ajuste não pede autorização: a checagem vem antes de abrir a confirmação
assert.ok(app.indexOf('adjustFunds({ costCc') < app.indexOf('this.setUI({ confirmExtra: { scene: idx'));
assert.ok(!/Já tenho créditos: retomar/.test(pw));

console.log('ok: credits');

// ---------------------------------------------------------------- Comprar créditos (ui/buy.js)
{
  const B = await import('../src/ui/buy.js');
  const custom = { unit_price_cents: 50, min_credits: 40, step_credits: 20, max_credits: 1000, hint_from_credits: 140, hint_package: 'inicial' };
  const cat = { custom, packages: [{ code: 'inicial', name: 'Inicial', credits: 200, price_cents: 7990 }, { code: 'pro', name: 'Pro', credits: 600, price_cents: 19990 }] };
  assert.equal(B.brl(7990), 'R$ 79,90');
  assert.equal(B.brl(54990), 'R$ 549,90');
  // Economize X% contra R$ 0,50/crédito (igual ao servidor: 20, 33, 45)
  assert.deepEqual([[200, 7990], [600, 19990], [2000, 54990]].map(([c, p]) => B.savingsPct(c, p, 50)), [20, 33, 45]);
  assert.equal(B.savingsPct(100, 5000, 50), 0);
  assert.equal(B.videosFor(600, 20), 30);
  // avulso: mínimo 40, de 20 em 20, máximo 1.000
  assert.ok(B.customValid(40, custom) && B.customValid(1000, custom) && B.customValid(60, custom));
  assert.ok(!B.customValid(20, custom) && !B.customValid(50, custom) && !B.customValid(1020, custom) && !B.customValid(40.5, custom));
  assert.equal(B.clampCustom(10, custom), 40);
  assert.equal(B.clampCustom(5000, custom), 1000);
  assert.equal(B.clampCustom(51, custom), 60);
  assert.equal(B.stepCustom(40, -1, custom), 40);
  assert.equal(B.stepCustom(40, 1, custom), 60);
  assert.equal(B.stepCustom(1000, 1, custom), 1000);
  assert.equal(B.customTotalCents(100, custom), 5000);
  assert.equal(B.customTotalCents(50, custom), 0);
  // dica a partir de 140 créditos
  assert.equal(B.customHint(120, cat), null);
  assert.equal(B.customHint(140, cat), 'No pacote Inicial, 200 créditos saem por R$ 79,90.');
  // CPF / CNPJ (inclusive CNPJ alfanumérico)
  assert.ok(B.docValid('529.982.247-25') && B.docValid('11.222.333/0001-81') && B.docValid('12.ABC.345/01DE-35'));
  assert.ok(!B.docValid('111.111.111-11') && !B.docValid('123.456.789-00') && !B.docValid('11.222.333/0001-80') && !B.docValid('123'));
  assert.equal(B.maskDoc('52998224725'), '529.982.247-25');
  assert.equal(B.maskDoc('11222333000181'), '11.222.333/0001-81');
  // cartão: mesmo limite do servidor
  const fresh = { new_account: true, disputed: false, count_today: 0, max_cents: 19990, daily_limit_cents: 60000 };
  assert.equal(B.cardBlock(19990, fresh), null);
  assert.match(B.cardBlock(54990, fresh), /pacote Pro/);
  assert.match(B.cardBlock(7990, { ...fresh, count_today: 1, max_cents: 0 }), /1 compra no cartão por dia/);
  assert.match(B.cardBlock(7990, { ...fresh, new_account: false, max_cents: 5000 }), /limite diário de R\$ 600,00/);
  assert.match(B.cardBlock(100, { ...fresh, disputed: true }), /só por Pix/);
  // o pedido nunca leva valor
  assert.deepEqual(B.checkoutBody({ tab: 'pacotes', pkg: 'pro', custom: 100, method: 'pix', doc: '529.982.247-25' }), { method: 'pix', package: 'pro', document: '52998224725' });
  assert.deepEqual(B.checkoutBody({ tab: 'avulso', pkg: 'pro', custom: 100, method: 'card', doc: '' }), { method: 'card', credits: 100 });
  assert.equal(B.statusOf('paid').label, 'Pagamento confirmado');
  assert.ok(B.isFinal('paid') && !B.isFinal('pending'));
}

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

// ---------------------------------------------------------------- Comprar créditos v2: cards, seleção, celular
{
  const B = await import('../src/ui/buy.js');
  const pk = (code, name, credits, price, extra = {}) => ({ code, name, credits, price_cents: price, features: [], ...extra });
  const packages = [pk('inicial', 'Inicial', 200, 7990), pk('pro', 'Pro', 600, 19990, { highlight: true }), pk('escala', 'Escala', 2000, 54990)];
  const free = { name: 'Free', credits: 20, tagline: 'Só para conhecer', price_note: 'Crédito de boas-vindas', missing: ['a'] };
  // conta sem compra: Free à esquerda, plano atual; 4 cards; Pro com "Mais escolhido"; Pro selecionado por padrão
  let r = B.planCards({ packages, free, plan: { plan: 'free', has_purchase: false } });
  assert.deepEqual(r.cards.map((c) => c.code), ['free', 'inicial', 'pro', 'escala']);
  assert.ok(r.showFree && r.cards[0].current && r.cards[0].kind === 'free');
  assert.deepEqual(r.cards.map((c) => c.badge), [null, null, 'Mais escolhido', null]);
  assert.equal(B.defaultSelection({ packages }), 'pro');
  // conta que já comprou (Pro): Free some (3 cards), Pro é o plano atual, "Comprar de novo", sem "Mais escolhido"
  r = B.planCards({ packages, free, plan: { plan: 'pro', has_purchase: true } });
  assert.deepEqual(r.cards.map((c) => c.code), ['inicial', 'pro', 'escala']);
  assert.ok(!r.showFree && r.cards[1].current && r.cards[1].badge === null);
  assert.equal(B.buyLabel(r.cards[1], true), 'Comprar de novo');
  // plano Escala: "Mais escolhido" continua no Pro
  r = B.planCards({ packages, free, plan: { plan: 'escala', has_purchase: true } });
  assert.equal(r.cards.find((c) => c.code === 'pro').badge, 'Mais escolhido');
  assert.equal(B.buyLabel(r.cards[2], false), 'Comprar de novo');
  // só avulso comprado: sem Free, nenhum plano atual entre os pacotes
  r = B.planCards({ packages, free, plan: { plan: 'free', has_purchase: true } });
  assert.ok(!r.showFree && r.cards.every((c) => !c.current));
  // botões: selecionado = "Comprar Pro"; os outros "Comprar"
  assert.equal(B.buyLabel(packages[1], true), 'Comprar Pro');
  assert.equal(B.buyLabel(packages[0], true), 'Comprar Inicial');
  assert.equal(B.buyLabel(packages[2], false), 'Comprar');
  // teclado: setas andam e voltam pela ponta; Home/End; outras teclas não mudam
  const codes = ['inicial', 'pro', 'escala'];
  assert.equal(B.moveSelection(codes, 'pro', 'ArrowRight'), 'escala');
  assert.equal(B.moveSelection(codes, 'escala', 'ArrowRight'), 'inicial');
  assert.equal(B.moveSelection(codes, 'pro', 'ArrowLeft'), 'inicial');
  assert.equal(B.moveSelection(codes, 'inicial', 'ArrowUp'), 'escala');
  assert.equal(B.moveSelection(codes, 'pro', 'ArrowDown'), 'escala');
  assert.equal(B.moveSelection(codes, 'pro', 'Home'), 'inicial');
  assert.equal(B.moveSelection(codes, 'pro', 'End'), 'escala');
  assert.equal(B.moveSelection(codes, 'pro', 'a'), 'pro');
  // celular: Pro primeiro, Free por último
  const all = B.planCards({ packages, free, plan: { plan: 'free', has_purchase: false } }).cards;
  assert.deepEqual(B.phoneOrder(all).map((c) => c.code), ['pro', 'inicial', 'escala', 'free']);
  assert.equal(B.barSummary(packages[1]), '600 créditos · ' + B.brl(19990));
  assert.equal(B.barSummary(packages[2]), '2.000 créditos · ' + B.brl(54990));
  // a tela nova não mostra mais "1 vídeo = 20 créditos" nem "≈ N vídeos"
  const jsx = readFileSync(new URL('../src/ui/BuyCredits.jsx', import.meta.url), 'utf8');
  assert.ok(!/1 vídeo =/.test(jsx) && !/≈/.test(jsx) && !/rende até/.test(jsx));
  // movimento: 220 ms cubic-bezier(.2,.8,.2,1); só transform/sombra/cor; reduced-motion tira o movimento
  const css = readFileSync(new URL('../src/ui/buyv2.css', import.meta.url), 'utf8');
  assert.ok(/--bv-ease: cubic-bezier\(\.2, \.8, \.2, 1\); --bv-t: 220ms/.test(css));
  assert.ok(/\.bv-card\.is-sel \{ transform: translateY\(-6px\); \}/.test(css));
  assert.ok(/0 10px 28px rgba\(20, 20, 20, \.10\)/.test(css));
  const rm = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.ok(/\.bv-card\.is-sel \{ transform: none; \}/.test(rm) && /transition: none/.test(rm));
  assert.ok(!/transition:[^;]*(height|width|padding|margin)/.test(css.slice(0, css.indexOf('@media'))));   // nada de layout animado no desktop
  assert.ok(!/#FF5B2E|orange/i.test(css));                                                                     // nada de laranja
  console.log('ok: comprar créditos v2');
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
  assert.equal(W.firstVideoCopy({ P, productions: [P], wallet: low }).text,
    'Esse é o seu produto vendendo sozinho. Continue criando: no Pro, cada vídeo sai por R$ 6,66.');
  assert.equal(W.firstVideoCopy({ P, productions: [P], wallet: low }).cta, 'Ver pacotes');
  assert.equal(W.firstVideoCopy({ P, productions: [P], wallet: { balance_cc: 2000 } }), null);       // ainda dá 1 vídeo
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
