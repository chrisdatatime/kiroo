import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { inflateSync } from 'node:zlib';
import { inspectKirooSheet, KIROO_SHEET_ROWS } from '../src/game/phaser/spriteLayout.js';
import { KIROO_COLS, kirooFrame } from '../src/game/phaser/sprites.js';

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

// Folhas atuais: grade 16x48 de quadros 32x32 (sprites.js). Mapeamento de quadros: kirooFrame().
const FRAMES = KIROO_COLS * KIROO_SHEET_ROWS;
for (const name of ['nina', 'theo', 'iris', 'rui', 'lia', 'beto']) {
  const source = readRGBA(new URL(`../../assets/characters/${name}.png`, import.meta.url));
  assert.equal(source.width, 512, name); assert.equal(source.height, 1536, name);
  const frames = inspectKirooSheet(source);
  assert.equal(frames.length, FRAMES, name);
  const empty = frames.filter((f) => f.opaque === 0);
  assert.equal(empty.length, 0, `${name}: quadros vazios ${empty.map((f) => f.index).join(',')}`);
  frames.forEach((f) => assert.ok(f.top >= 0 && f.bottom <= 30, `${name}: quadro ${f.index} dentro do 32x32 (linhas ${f.top}..${f.bottom})`));
  // Todo quadro que o jogo pode pedir existe e tem desenho (espera, caminhada, prancheta).
  for (const dir of ['down', 'left', 'up', 'right']) for (const action of ['idle', 'walk', 'work']) for (let k = 0; k < 16; k++) {
    const idx = kirooFrame(dir, k / 16, action);
    assert.ok(idx >= 0 && idx < FRAMES && frames[idx].opaque > 0, `${name}: ${dir}/${action}/${k} -> quadro ${idx}`);
  }
  assert.throws(() => inspectKirooSheet({ ...source, width: 350, height: 1019 }), /esperado 512x1536/);
  console.log(`${name}: ${FRAMES} quadros 32x32, todos com desenho; quadros usados pelo jogo ok`);
}
