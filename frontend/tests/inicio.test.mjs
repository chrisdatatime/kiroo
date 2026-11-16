// Início: lógica pura (status, nome, datas, saudação, resumo, saldo, primeiro acesso). Sem navegador.
import assert from 'node:assert/strict';
import {
  STATUS_VIEW, statusOf, productName, relativeDate, agoLabel, greeting, summaryLine, needsYou, filterProductions, filterCounts, videosLeft, videosLine,
  balanceRatio, estimateLabel, firstSteps, stepsVisible, showHowItWorks, showWelcome, teamSummary, thumbOf, countsOf,
} from '../src/shell/inicio.js';

const P = (status, extra = {}) => ({ id: 'prod_c67de26276', status, engine: 'fal', created_at: '2026-11-16T10:00:00', ...extra });

// mapeamento de status reais → rótulos novos
assert.equal(statusOf(P('awaiting_final_review')).label, 'Aguardando aprovação');
assert.equal(statusOf(P('producing')).label, 'Gerando');
assert.equal(statusOf(P('editing')).label, 'Gerando');
assert.equal(statusOf(P('completed')).label, 'Pronto');
assert.equal(statusOf(P('completed', { downloaded: true })).label, 'Baixado');
assert.equal(statusOf(P('cancelled')).label, 'Cancelado');
assert.equal(statusOf(P('failed')).label, 'Erro');
assert.equal(statusOf(P('failed')).action, 'Ver detalhes');
assert.equal(statusOf(P('paused')).needsYou, true);
assert.equal(statusOf(P('received')).key, 'decisao');                         // fal parado antes do /run espera o usuário
assert.equal(statusOf(P('received', { running: true })).key, 'gerando');
assert.equal(statusOf({ id: 'x', status: 'received', engine: 'gemini' }).key, 'gerando');
assert.equal(statusOf(P('producing', { ended: 'cancelled' })).key, 'cancelado');
['aprovacao', 'gerando', 'pronto', 'baixado', 'cancelado', 'erro'].forEach((k) => assert.ok(STATUS_VIEW[k].tone));

// nome nunca é o id cru
assert.equal(productName(P('producing', { name: 'Skate Completo' })), 'Skate Completo');
assert.equal(productName(P('producing', { name: 'prod_c67de26276' })), 'Produção de 16/11, 10:00');
assert.equal(productName(P('producing', { name: '' })), 'Produção de 16/11, 10:00');
assert.equal(productName(P('producing', { name: '' }), 'Tênis Run Leve'), 'Tênis Run Leve');
assert.equal(productName(P('producing', { name: 'prod_c67de26276' }), 'prod_aaaaaa1111'), 'Produção de 16/11, 10:00');
assert.ok(!/prod_/.test(productName({ id: 'prod_1234567890', name: 'prod_1234567890' })));

// datas
const now = new Date('2026-11-16T12:00:00');
assert.equal(relativeDate('2026-11-16T00:04:00', now), 'Hoje, 00:04');
assert.equal(relativeDate('2026-11-15T23:10:00', now), 'Ontem, 23:10');
assert.equal(relativeDate('2026-11-10T14:05:00', now), '10/11, 14:05');
assert.equal(agoLabel('2026-11-16T11:48:00', now), 'há 12 min');

// saudação por horário (madrugada = Boa noite)
const at = (h) => greeting(new Date(2026, 10, 16, h, 30));
assert.deepEqual([at(2), at(4), at(5), at(11), at(12), at(17), at(18), at(23)], ['Boa noite', 'Boa noite', 'Bom dia', 'Bom dia', 'Boa tarde', 'Boa tarde', 'Boa noite', 'Boa noite']);

// resumo
assert.equal(summaryLine([]), null);
assert.equal(summaryLine([P('awaiting_final_review'), P('producing')]), '1 vídeo espera sua aprovação e 1 está sendo produzido.');
assert.equal(summaryLine([P('awaiting_final_review'), P('awaiting_final_review')]), '2 vídeos esperam sua aprovação.');
assert.equal(summaryLine([P('producing'), P('producing')]), '2 estão sendo produzidos.');
assert.equal(summaryLine([P('completed'), P('cancelled')]), 'Tudo em dia.');

// "+N aguardando": a mais antiga primeiro
const a = P('awaiting_final_review', { id: 'a', created_at: '2026-11-14T10:00:00' }), b = P('awaiting_final_review', { id: 'b', created_at: '2026-11-15T10:00:00' }), c = P('awaiting_final_review', { id: 'c', created_at: '2026-11-16T10:00:00' });
let n = needsYou([c, b, a, P('producing')]);
assert.equal(n.first.id, 'a'); assert.equal(n.extra, 2);
n = needsYou([P('producing'), P('completed')]);
assert.equal(n.first, null); assert.equal(n.extra, 0);

// filtros e contagens
const list = [a, b, P('producing', { id: 'g' }), P('completed', { id: 'd' }), P('failed', { id: 'e' })];
assert.deepEqual(filterCounts(list), { todas: 5, andamento: 1, prontas: 3, baixadas: 0 });
assert.equal(filterProductions(list, 'andamento')[0].id, 'g');
assert.equal(countsOf(list).erro, 1);

// saldo: custo vem da oferta (nunca fixo); ≈ N vídeos = floor(saldo / custo)
assert.equal(videosLeft({ balance_cc: 8000 }, { cc: 2000 }), 4);
assert.equal(videosLeft({ balance_cc: 7999 }, { cc: 2000 }), 3);
assert.equal(videosLeft({ balance_cc: 1999 }, { cc: 2000 }), 0);
assert.equal(videosLeft({ balance_cc: 8000 }, { cc: 4000 }), 2);                  // outro custo, outro resultado
assert.equal(videosLeft({ balance_cc: 8000 }, { cc: 0 }), null);                  // DEMO: sem custo real, sem conta
assert.equal(videosLeft({ balance_cc: 8000, exempt: true }, { cc: 2000 }), null);
assert.equal(videosLeft(null, { cc: 2000 }), null);
assert.equal(videosLine(4), 'Dá para ≈ 4 vídeos'); assert.equal(videosLine(1), 'Dá para ≈ 1 vídeo'); assert.equal(videosLine(null), '');
assert.equal(balanceRatio({ balance_cc: 8000 }, { credits: 100 }), 0.8);
assert.equal(balanceRatio({ balance_cc: 8000 }, null), null);
assert.equal(estimateLabel(180), 'cerca de 3 min'); assert.equal(estimateLabel(0), 'poucos minutos');

// primeiro acesso e "Como funciona"
const acc = (v) => ({ user: { email_verified: v } });
let fs = firstSteps({ account: acc(false), productions: [] });
assert.deepEqual([fs.done, fs.total, fs.all], [0, 3, false]);
assert.equal(showWelcome([]), true); assert.equal(showWelcome([P('producing')]), false);
assert.equal(stepsVisible(fs, []), true);
assert.equal(showHowItWorks([], stepsVisible(fs, [])), false);                     // Primeiros passos visível: some o "Como funciona"
fs = firstSteps({ account: acc(true), productions: [P('producing')] });
assert.equal(fs.done, 2);
fs = firstSteps({ account: acc(true), productions: [P('completed')] });
assert.equal(fs.all, true);
assert.equal(showHowItWorks([P('completed')], stepsVisible(fs, [P('completed')])), true);
const three = [P('completed'), P('completed'), P('completed')];
assert.equal(showHowItWorks(three, false), false);                                 // some depois de 2 produções
assert.equal(showHowItWorks(three.slice(0, 2), false), true);

// equipe e miniatura
const team = [{ id: 'nina', name: 'Nina' }, { id: 'beto', name: 'Beto' }];
assert.equal(teamSummary(team, { beto: 'need' }).line, 'Beto espera você');
assert.equal(teamSummary(team, {}).status, 'Livre para produzir');
const th = (s) => `/t/${s}.jpg`;
assert.equal(thumbOf({ current: true, scene: 'studio' }, '/foto.jpg', th), '/foto.jpg');
assert.equal(thumbOf({ current: false, scene: 'studio' }, '/foto.jpg', th), '/t/studio.jpg');
assert.equal(thumbOf({}, null, th), null);
console.log('inicio.test ok');
