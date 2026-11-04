import assert from 'node:assert/strict';
import { STEPS, createTour, resumeIndex, layoutFor, placeCard, progress, activeSteps } from '../src/onboarding/tour.js';

const idx = (id) => STEPS.findIndex((s) => s.id === id);
const ctx = { world: true };

// 8 passos + conclusão; começa no diálogo e termina no diálogo final
assert.equal(STEPS[0].kind, 'dialog');
assert.ok(STEPS[STEPS.length - 1].final);
assert.equal(progress(0, ctx).total, 8);
assert.deepEqual(progress(idx('overview'), ctx), { n: 4, total: 8 });

// conta nova (done_at nulo) começa no passo 1; concluído não abre sozinho
assert.equal(resumeIndex({ done_at: null, step: 0 }, ctx), 0);
assert.equal(resumeIndex({ done_at: '2026-11-04T10:00:00', step: 5 }, ctx), null);

// passo persistido e retomado: fechou no passo 4, volta no passo 4
let saved = [];
let t = createTour({ start: 0, ctx, save: (p) => saved.push(p) });
t.next(); t.next(); t.next();
assert.equal(t.step.id, 'overview');
t.close();
assert.deepEqual(saved.at(-1), { step: idx('overview') });
const server = { done_at: null, step: saved.at(-1).step };
assert.equal(STEPS[resumeIndex(server, ctx)].id, 'overview');
t = createTour({ start: resumeIndex(server, ctx), ctx, save: () => {} });
assert.equal(t.step.id, 'overview');
t.prev();
assert.equal(t.step.id, 'new-mission');

// pular marca como concluído
saved = [];
t = createTour({ start: 2, ctx, save: (p) => saved.push(p) });
t.skip();
assert.equal(saved.at(-1).done, true);
// concluir também (e o "Rever tutorial" recomeça do 1)
t.finish();
assert.deepEqual(saved.at(-1), { step: 0, done: true });

// mundo desligado: passo do escritório some e o progresso conta 7
const off = { world: false };
assert.ok(!activeSteps(off).includes(idx('office')));
assert.equal(progress(0, off).total, 7);
t = createTour({ start: idx('modes'), ctx: off, save: () => {} });
t.next();
assert.equal(t.step.id, 'account');
assert.equal(STEPS[resumeIndex({ done_at: null, step: idx('office') }, off)].id, 'account');
// passo salvo fora da faixa não quebra
assert.equal(resumeIndex({ done_at: null, step: 99 }, ctx), STEPS.length - 1);

// alvo ausente cai para card centralizado; alvo presente vira spotlight
const vp = { w: 1280, h: 800 };
const el = (x, y, w, h) => ({ getBoundingClientRect: () => ({ left: x, top: y, width: w, height: h, right: x + w, bottom: y + h }) });
const team = STEPS[idx('team')];
assert.deepEqual(layoutFor(team, () => null, vp), { mode: 'center' });
assert.equal(layoutFor(team, (id) => (id === 'team' ? el(0, 0, 0, 0) : null), vp).mode, 'center'); // escondido (área zero)
assert.equal(layoutFor(team, (id) => (id === 'team' ? el(-500, 10, 100, 50) : null), vp).mode, 'center'); // fora da tela
const spot = layoutFor(team, (id) => (id === 'team-head' ? el(80, 200, 260, 30) : null), vp); // fallback de alvo
assert.equal(spot.mode, 'spot');
assert.equal(spot.target, 'team-head');
assert.equal(layoutFor(STEPS[0], () => null, vp).mode, 'dialog');

// card ao lado do alvo, dentro da tela; alvo enorme (o mundo) põe o card por dentro
let p = placeCard({ x: 80, y: 200, w: 260, h: 300 }, { w: 360, h: 200 }, vp, 'right');
assert.equal(p.side, 'right');
assert.ok(p.x >= 340 && p.y >= 12 && p.y + 200 <= vp.h - 12);
p = placeCard({ x: 1100, y: 10, w: 140, h: 40 }, { w: 360, h: 200 }, vp, 'bottom');
assert.equal(p.side, 'bottom');
assert.ok(p.x + 360 <= vp.w - 12 && p.arrow > 180);
p = placeCard({ x: 80, y: 60, w: 1190, h: 730 }, { w: 360, h: 200 }, vp, 'inside');
assert.equal(p.side, 'inside');
assert.equal(p.arrow, null);

console.log('onboarding ok');
