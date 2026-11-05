import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { inflateSync } from 'node:zlib';
import { kirooFrameRects, normalizeKirooSheet } from '../src/game/phaser/spriteLayout.js';

// Lê os PNGs RGBA reais sem depender do DOM ou adicionar uma biblioteca ao produto.
function readRGBA(url) {
  const png = readFileSync(url), chunks = [];
  const width = png.readUInt32BE(16), height = png.readUInt32BE(20);
  assert.equal(png[24], 8); assert.equal(png[25], 6); assert.equal(png[28], 0);
  for (let at = 8; at < png.length;) {
    const length = png.readUInt32BE(at), kind = png.toString('ascii', at + 4, at + 8);
    if (kind === 'IDAT') chunks.push(png.subarray(at + 8, at + 8 + length));
    at += length + 12;
  }
  const raw = inflateSync(Buffer.concat(chunks)), stride = width * 4;
  const data = new Uint8Array(height * stride);
  const paeth = (a, b, c) => {
    const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  };
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x++) {
      const at = y * stride + x, a = x >= 4 ? data[at - 4] : 0;
      const b = y ? data[at - stride] : 0, c = y && x >= 4 ? data[at - stride - 4] : 0;
      const prediction = [0, a, b, Math.floor((a + b) / 2), paeth(a, b, c)][filter];
      assert.notEqual(prediction, undefined);
      data[at] = raw[y * (stride + 1) + x + 1] + prediction;
    }
  }
  return { width, height, data };
}

for (const name of ['nina', 'theo', 'iris', 'rui', 'lia', 'beto']) {
  const source = readRGBA(new URL(`../../assets/characters/${name}.png`, import.meta.url));
  const rects = kirooFrameRects(source);
  assert.equal(rects.length, 36, name);
  const covered = new Uint8Array(source.width * source.height);
  rects.forEach((r) => {
    assert.ok(r.width > 0 && r.width <= 32 && r.height > 0 && r.height <= 32, `${name}: quadro inteiro`);
    for (let y = r.y; y < r.y + r.height; y++) for (let x = r.x; x < r.x + r.width; x++) {
      assert.equal(covered[y * source.width + x], 0, `${name}: sem sobreposição`);
      covered[y * source.width + x] = 1;
    }
  });
  for (let pixel = 0; pixel < covered.length; pixel++) {
    if (source.data[pixel * 4 + 3] > 127) assert.equal(covered[pixel], 1, `${name}: pixel não cortado`);
  }
  // Verifica as chamadas reais de renderização: cada desenho fica no centro da
  // célula e seus pés na mesma base, sem redimensionamento ou vazamento entre quadros.
  const draws = [];
  const output = normalizeKirooSheet(source, () => ({ getContext: () => ({
    drawImage: (...args) => draws.push(args), getImageData: () => source,
  }) }));
  assert.equal(output.width, 192); assert.equal(output.height, 192);
  draws.slice(1).forEach(([, , , sw, sh, dx, dy, dw, dh], i) => {
    assert.equal(sw, dw); assert.equal(sh, dh);
    assert.ok(Math.abs((dx % 32) + dw / 2 - 16) <= 0.5, `${name}: centro fixo ${i}`);
    assert.equal(dy + dh, (Math.floor(i / 6) + 1) * 32, `${name}: base fixa ${i}`);
  });
  console.log(`${name}: 36 quadros completos e alinhados`);
}
