// Home pública (src/landing/stage.js): câmera da sede, timecode e formato lido do arquivo de vídeo.
import assert from 'node:assert/strict';
import { IMG, ACTS, ROOMS, WIDE, fitCamera, mixCam, pan, ease, mixRect, fmtTC, fmtFormat } from '../src/landing/stage.js';

const inside = ([x, y, w, h]) => x >= 0 && y >= 0 && w > 0 && h > 0 && x + w <= IMG.w && y + h <= IMG.h;
assert.equal(ACTS.length, 3, 'três atos: o percurso é curto');
for (const a of ACTS) assert.ok(inside(a.rect), `enquadramento de ${a.id} dentro da sede`);
for (const [id, r] of Object.entries(ROOMS)) assert.ok(inside(r), `sala ${id} dentro da sede`);
assert.deepEqual(ACTS.flatMap((a) => a.crew).sort(), ['beto', 'iris', 'lia', 'nina', 'rui', 'theo'], 'cada agente aparece em um ato só');

// a câmera em modo contain mostra o recorte inteiro e nunca mostra além da imagem
for (const [fw, fh] of [[780, 620], [350, 300], [1440, 900]]) {
  for (const a of ACTS) {
    const c = fitCamera(a.rect, fw, fh);
    const p = pan(c, fw, fh);
    assert.ok(p.x <= 0.001 && p.y <= 0.001, 'sem fundo à esquerda/em cima');
    assert.ok(p.x + IMG.w * c.s >= fw - 0.001 && p.y + IMG.h * c.s >= fh - 0.001, 'sem fundo à direita/embaixo');
    const [x, y, w, h] = a.rect;
    if (c.s <= Math.min(fw / w, fh / h) + 1e-9) {
      assert.ok(p.x + x * c.s >= -0.5 && p.x + (x + w) * c.s <= fw + 0.5, `${a.id} cabe na largura (${fw}x${fh})`);
      assert.ok(p.y + y * c.s >= -0.5 && p.y + (y + h) * c.s <= fh + 0.5, `${a.id} cabe na altura (${fw}x${fh})`);
    }
  }
  const w = fitCamera(WIDE, fw, fh, 'cover');
  assert.ok(Math.abs(w.s - Math.max(fw / IMG.w, fh / IMG.h)) < 1e-9, 'plano geral preenche o quadro');
}
const m = mixCam({ s: 1, cx: 0, cy: 0 }, { s: 4, cx: 100, cy: 50 }, 0.5);
assert.ok(Math.abs(m.s - 2) < 1e-9 && m.cx === 50 && m.cy === 25, 'zoom em log, centro linear');
assert.equal(ease(0), 0); assert.equal(ease(1), 1); assert.equal(ease(0.5), 0.5);
assert.deepEqual(mixRect({ x: 0, y: 0, w: 10, h: 10 }, { x: 10, y: 20, w: 30, h: 40 }, 0.5), { x: 5, y: 10, w: 20, h: 25 });

assert.equal(fmtTC(0), '00:00');
assert.equal(fmtTC(14.9), '00:14');
assert.equal(fmtTC(75), '01:15');
assert.equal(fmtTC(NaN), '--:--');
assert.equal(fmtTC(-1), '--:--');
assert.equal(fmtFormat(1080, 1920), 'Vertical 9:16');
assert.equal(fmtFormat(1080, 1080), 'Quadrado 1:1');
assert.equal(fmtFormat(1080, 1350), 'Vertical 4:5');
assert.equal(fmtFormat(1920, 1080), 'Horizontal 16:9');
assert.equal(fmtFormat(1000, 700), 'Horizontal 1000×700');
assert.equal(fmtFormat(0, 100), null);

console.log('landing: ok');
