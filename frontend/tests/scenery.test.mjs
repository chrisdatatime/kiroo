import assert from 'node:assert/strict';
import { pickScale, deviceScale, tileStart, layerOffset, bandRect, sampleEdges, normalizeTheme, skyline, treeLine, LAYER_H, PARALLAX } from '../src/game/scenery/scenery.js';

// escala inteira pela altura
assert.equal(pickScale(400), 2); assert.equal(pickScale(544), 2); assert.equal(pickScale(816), 3);
assert.equal(pickScale(900), 3); assert.equal(pickScale(1088), 4); assert.equal(pickScale(4000), 4); assert.equal(pickScale(0), 2);
assert.equal(deviceScale(3, 1.25), 4); assert.equal(deviceScale(2, 2), 4); assert.equal(deviceScale(2, 1), 2);
// repetição horizontal
assert.equal(tileStart(0, 100), 0); assert.equal(tileStart(30, 100), -70); assert.equal(tileStart(-30, 100), -30); assert.equal(tileStart(100, 100), 0);
// parallax discreto e desligado com movimento reduzido
assert.equal(layerOffset(500, PARALLAX.middle, true), 0);
assert.ok(Math.abs(layerOffset(500, PARALLAX.back, false)) < Math.abs(layerOffset(500, PARALLAX.middle, false)));
assert.ok(PARALLAX.middle < 0.3);
// faixa centralizada
assert.deepEqual(bandRect(1000, 3), { y: Math.round((1000 - LAYER_H * 3) / 2), h: 816 });
// bordas amostradas: ignora transparente, média da linha
const d = new Uint8ClampedArray(2 * 3 * 4);
const put = (x, y, c, a = 255) => { const i = (y * 2 + x) * 4; d.set([...c, a], i); };
put(0, 0, [0, 0, 0], 0); put(1, 0, [0, 0, 0], 0); put(0, 1, [10, 20, 30]); put(1, 1, [30, 40, 50]); put(0, 2, [100, 100, 100]); put(1, 2, [200, 100, 0]);
const e = sampleEdges(d, 2, 3);
assert.deepEqual(e.top, [20, 30, 40]); assert.deepEqual(e.bottom, [150, 100, 50]);
assert.deepEqual(sampleEdges(new Uint8ClampedArray(8), 2, 1).top.length, 3);
// tema
assert.equal(normalizeTheme('gerado'), 'gerado'); assert.equal(normalizeTheme('x'), 'floresta'); assert.equal(normalizeTheme(null), 'floresta');
// geração periódica: sem emenda
for (const [p, f] of [[160, (x) => skyline(x, 160, 150, 10, 1)], [384, (x) => skyline(x, 384, 190, 14, 2)], [384, (x) => treeLine(x, 384, 272, 3)]]) {
  assert.equal(f(0), f(p), 'periódico em ' + p);
}
console.log('scenery ok');
