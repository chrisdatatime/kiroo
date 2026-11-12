// Revisão com fidelidade ao produto: lado a lado, âncora, gravidade da conferência e aviso de formato.
import assert from 'node:assert/strict';
import { sideBySide, anchorInfo, reviewCheck, formatAdvice } from '../src/ui/fidelity.js';

const rev = (decision, extra = {}) => ({ reviewer: 'auto:gemini-api:x', decision, issues: [], critical_issues: [], warnings: [], ...extra });
const att = (id, no, reviews) => ({ id, no, url: `/media/p/${id}.png`, status: 'succeeded', reviews });

// lado a lado: só com 2+ versões e decisão pendente
const blocked = { status: 'blocked', candidates: { image: [att('a1', 1, [rev('rejected', { critical_issues: ['botões espelhados'] })]), att('a2', 2, [rev('approved', { warnings: ['dedo extra'] })])], video: [] } };
const sb = sideBySide(blocked, 'img');
assert.equal(sb.stage, 'image');
assert.equal(sb.blocked, true);
assert.deepEqual(sb.items.map((i) => i.verdict), ['produto com problema', 'certo, com aviso']);
assert.deepEqual(sb.items[0].critical, ['botões espelhados']);
assert.equal(sb.items[1].canChoose, true);
assert.equal(sideBySide(blocked, 'img', true).items[0].canChoose, false);        // em execução: não escolhe
assert.equal(sideBySide({ ...blocked, status: 'image_approved' }, 'img'), null);  // nada a decidir
assert.equal(sideBySide({ status: 'blocked', candidates: { image: [att('a1', 1, [])] } }, 'img'), null);
assert.equal(sideBySide({ status: 'blocked' }, 'img'), null);                      // servidor antigo
assert.equal(sideBySide(blocked, 'vid'), null);

// âncora
const sc = { image: att('a2', 2, []) };
assert.deepEqual(anchorInfo({ anchor: null }, sc, 'img'), { attemptId: 'a2', isAnchor: false, hasAnchor: false, anchorScene: null });
assert.equal(anchorInfo({ anchor: { attempt_id: 'a2', scene: 1 } }, sc, 'img').isAnchor, true);
assert.equal(anchorInfo({ anchor: null }, sc, 'vid'), null);
assert.equal(anchorInfo({ anchor: null }, { image: { ...sc.image, status: 'failed' } }, 'img'), null);

// conferência com gravidade
assert.equal(reviewCheck(att('x', 1, [rev('approved', { warnings: ['polegar torto'] })])).title, 'Produto certo, com um aviso');
assert.match(reviewCheck(att('x', 1, [rev('approved', { warnings: ['polegar torto'] })])).text, /não bloqueia/);
assert.equal(reviewCheck(att('x', 1, [rev('approved')])).title, 'Parece certo');
assert.equal(reviewCheck(att('x', 1, [rev('rejected', { critical_issues: ['cabo saindo do lado'] })])).text, 'cabo saindo do lado');
assert.match(reviewCheck(att('x', 1, [rev('inconclusive')]), 'simulated').text, /DEMO/);
assert.equal(reviewCheck(att('x', 1, [{ reviewer: 'human', decision: 'approved' }])), null);
assert.equal(reviewCheck(null), null);

// aviso de formato
assert.equal(formatAdvice({ preview: null, production: null, presentation: 'hands_only' }), null);
const fa = formatAdvice({ preview: { format_advice: { text: 'Use Produto em destaque' } }, presentation: 'hands_only' });
assert.deepEqual(fa, { text: 'Use Produto em destaque', canSwitch: true, suggested: 'product_only' });
assert.equal(formatAdvice({ production: { format_advice: 'x' }, presentation: 'product_only' }).canSwitch, false);

console.log('fidelity ok');
