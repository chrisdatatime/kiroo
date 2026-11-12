// Zoom do mundo Phaser (game/phaser/zoom.js): níveis inteiros, clamp, âncora no cursor, roda acumulada e preferência salva.
import assert from 'node:assert/strict';
import { LEVELS, clampLevel, stepLevel, fitZoom, fmtLevel, pickLevel, deviceZoom, pickZoom, anchorScroll, snapScroll, wheelAccumulator, wheelPx, loadLevel, saveLevel } from '../src/game/phaser/zoom.js';

// níveis e clamp
assert.deepEqual(LEVELS, [1, 2, 3, 4]);
assert.equal(clampLevel(0), 1); assert.equal(clampLevel(9), 4); assert.equal(clampLevel(2.4), 2); assert.equal(clampLevel('x'), 1);
assert.equal(stepLevel(1, -1), 1, 'não passa do mínimo');
assert.equal(stepLevel(4, 1), 4, 'não passa do máximo');
assert.equal(stepLevel(2, 1), 3); assert.equal(stepLevel(2, -5), 1, 'um passo por vez, sem pular níveis');

// passo a partir de um zoom de ajuste fracionário: sobe ao próximo nível inteiro, não pula e não "sobe" ao afastar
assert.equal(stepLevel(0.75, 1), 1, 'ajuste 75% + aproximar = 1x');
assert.equal(stepLevel(0.75, -1), 0.75, 'ajuste 75% + afastar = fica');
assert.equal(stepLevel(1.5, 1), 2); assert.equal(stepLevel(1.5, -1), 1);
assert.equal(fmtLevel(2), '2x'); assert.equal(fmtLevel(0.75), '75%'); assert.equal(fmtLevel(1.5), '150%');

// ajuste à tela: a sede inteira (1216x1024) sempre cabe, centralizada, sem blur
const MW = 1216, MH = 1024;
for (const [w, h, dpr] of [[1920, 1080, 1], [1366, 768, 1], [1280, 650, 1], [2560, 1440, 1], [390, 700, 3], [1920, 1080, 1.5], [800, 1280, 2], [3840, 2160, 2], [300, 300, 1]]) {
  const wd = w * dpr, hd = h * dpr, z = fitZoom(wd, hd, MW, MH, dpr);
  assert.ok(MW * z <= wd + 1e-9 && MH * z <= hd + 1e-9, `cabe em ${w}x${h}@${dpr}: z=${z}`);
  if (z < 1) assert.ok(Number.isInteger(32 * z), `tile em px inteiros (z=${z})`);
  else assert.ok(Number.isInteger(z * 2), `múltiplo de 0,5 (z=${z})`);
  // altura decide quando a tela é larga e baixa: nunca fica maior que o necessário (perde no máximo um degrau)
  assert.ok(z >= Math.min(wd / MW, hd / MH) - (z < 1 ? 1 / 32 : 0.5) - 1e-9, `não encolhe demais (z=${z})`);
}
assert.equal(fitZoom(1920, 1080, MW, MH), 1, '1080p: altura limita, 1,05 → 1x');
assert.equal(fitZoom(1366, 650, MW, MH), 0.625, 'baixa e larga: pela altura, 20/32');
assert.equal(fitZoom(3840, 2160, MW, MH), 2, '4K: 2,1 → 2x');
assert.ok(fitZoom(1e9, 1e9, MW, MH, 1) <= 4, 'não passa de 4x');
assert.equal(fitZoom(0, 0, MW, MH), 1, 'área vazia não quebra');

// zoom final sempre inteiro em px do dispositivo e crescente com o nível, em 100%/125%/150%/200% do Windows
for (const dpr of [1, 1.25, 1.5, 2]) {
  const zs = LEVELS.map((l) => deviceZoom(l, dpr));
  zs.forEach((z) => assert.ok(Number.isInteger(z) && z >= 1, `inteiro (dpr ${dpr})`));
  for (let k = 1; k < zs.length; k++) assert.ok(zs[k] > zs[k - 1], `níveis distintos (dpr ${dpr}): ${zs}`);
}
// automático igual ao pickZoom de antes
assert.equal(pickLevel(1280), 1); assert.equal(pickLevel(1024), 2);
for (const [w, dpr] of [[1280, 1], [1920, 1], [1024, 1], [1920, 1.5], [1366, 1.25]]) assert.equal(pickZoom(w * dpr, dpr), deviceZoom(pickLevel(w), dpr));

// âncora: o ponto do mundo sob o cursor não muda com o zoom (câmera com origem no centro)
const world = (scroll, sx, w, z) => scroll + w / 2 + (sx - w / 2) / z;
for (const [scroll, sx, w, z0, z1] of [[100, 300, 1000, 1, 2], [40, 0, 800, 3, 2], [0, 799, 800, 2, 4]]) {
  const s1 = anchorScroll(scroll, sx, w, z0, z1);
  assert.ok(Math.abs(world(scroll, sx, w, z0) - world(s1, sx, w, z1)) < 1e-9);
}
assert.equal(anchorScroll(50, 500, 1000, 1, 3), 50, 'cursor no centro: scroll não muda');
assert.equal(snapScroll(10.3, 2), 10.5); assert.equal(snapScroll(10.3, 1), 10);

// roda: um notch de mouse = 1 passo; rajada de trackpad = 1 passo; direção certa
let acc = wheelAccumulator();
assert.equal(acc(-100, 0), 1, 'roda para cima aproxima');
assert.equal(acc(-100, 50), 0, 'mesmo gesto, ainda travado');
assert.equal(acc(100, 400), -1, 'roda para baixo afasta');
acc = wheelAccumulator();
const burst = Array.from({ length: 30 }, (_, k) => acc(-4, k * 8)); // 240 ms de trackpad
assert.equal(burst.filter((d) => d !== 0).length, 1, 'trackpad não pula vários níveis');
acc = wheelAccumulator();
assert.equal(acc(-10, 0), 0); assert.equal(acc(-10, 1000), 0, 'resto parado há muito tempo é descartado');
assert.equal(wheelPx({ deltaY: 3, deltaMode: 1 }), 48); assert.equal(wheelPx({ deltaY: -120, deltaMode: 0 }), -120);

// preferência salva (null = automático) e armazenamento que falha
const mem = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };
const st = mem();
assert.equal(loadLevel(st), null);
saveLevel(3, st); assert.equal(loadLevel(st), 3);
saveLevel(9, st); assert.equal(loadLevel(st), 4, 'salva já no limite');
saveLevel(null, st); assert.equal(loadLevel(st), null);
st.setItem('bc.zoom', 'abc'); assert.equal(loadLevel(st), null, 'valor inválido = automático');
const broken = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); }, removeItem() { throw new Error('x'); } };
assert.equal(loadLevel(broken), null); assert.doesNotThrow(() => saveLevel(2, broken));

console.log('zoom ok');
