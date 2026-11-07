import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { inflateSync } from 'node:zlib';
import { inspectKirooSheet, KIROO_SHEET_ROWS, KIROO_SHEET_SIZE } from '../src/game/phaser/spriteLayout.js';
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

// Folhas atuais dos agentes: 512x1536, grade exata 16x48 de quadros 32x32 (sprites.js). Mapeamento: kirooFrame().
const FRAMES = KIROO_COLS * KIROO_SHEET_ROWS;
assert.deepEqual(KIROO_SHEET_SIZE, { width: 512, height: 1536 });
assert.equal(FRAMES, 768);

// Parte sintética (sempre roda, inclusive na CI sem os assets licenciados): folha fabricada com um corpo em y 3..29 em
// todo quadro, exceto um quadro vazio. Confere índice/linha/coluna, contagem e os limites verticais de cada quadro.
{
  const { width, height } = KIROO_SHEET_SIZE, data = new Uint8Array(width * height * 4);
  const EMPTY = 5 * KIROO_COLS + 7;
  for (let i = 0; i < FRAMES; i++) {
    if (i === EMPTY) continue;
    const x0 = (i % KIROO_COLS) * 32, y0 = Math.floor(i / KIROO_COLS) * 32;
    for (let y = 3; y <= 29; y++) for (let x = 10; x < 22; x++) data[((y0 + y) * width + x0 + x) * 4 + 3] = 255;
  }
  const frames = inspectKirooSheet({ data, width, height });
  assert.equal(frames.length, FRAMES);
  assert.deepEqual(frames[EMPTY], { index: EMPTY, row: 5, col: 7, opaque: 0, top: null, bottom: null });
  assert.deepEqual(frames[FRAMES - 1], { index: FRAMES - 1, row: 47, col: 15, opaque: 27 * 12, top: 3, bottom: 29 });
  // O formato antigo (folha 6x6 de espaçamento irregular, 350x1019) e qualquer outra medida são recusados.
  assert.throws(() => inspectKirooSheet({ data, width: 350, height: 1019 }), /esperado 512x1536, recebido 350x1019/);
  assert.throws(() => inspectKirooSheet({ data, width: 512, height: 1504 }), /esperado 512x1536/);
  // Todo quadro que o jogo pede cai dentro da grade.
  for (const dir of ['down', 'left', 'up', 'right']) for (const action of ['idle', 'walk', 'work']) for (let k = 0; k < 16; k++) {
    const idx = kirooFrame(dir, k / 16, action);
    assert.ok(Number.isInteger(idx) && idx >= 0 && idx < FRAMES, `${dir}/${action}/${k} -> quadro ${idx}`);
  }
  console.log('sprite-layout sintético ok (grade 16x48, 350x1019 recusado)');
}

// Parte com os PNGs reais (arte licenciada, fora do Git). Sem eles: pula com aviso. KIROO_REQUIRE_ASSETS=1 faz falhar.
const NAMES = ['nina', 'theo', 'iris', 'rui', 'lia', 'beto'];
const sheet = (name) => new URL(`../../assets/characters/${name}.png`, import.meta.url);
const missing = NAMES.filter((n) => !existsSync(sheet(n)));
if (missing.length) {
  assert.notEqual(process.env.KIROO_REQUIRE_ASSETS, '1', `assets licenciados ausentes: ${missing.join(', ')}`);
  console.log(`sprite-layout real: PULADO (sem assets/characters/: ${missing.join(', ')}). Extraia o pacote licenciado para conferir.`);
} else for (const name of NAMES) {
  const source = readRGBA(sheet(name));
  assert.equal(source.width, 512, name); assert.equal(source.height, 1536, name);
  const frames = inspectKirooSheet(source);
  assert.equal(frames.length, FRAMES, name);
  const empty = frames.filter((f) => f.opaque === 0);
  assert.equal(empty.length, 0, `${name}: quadros vazios ${empty.map((f) => f.index).join(',')}`);
  frames.forEach((f) => assert.ok(f.top >= 0 && f.bottom <= 30, `${name}: quadro ${f.index} dentro do 32x32 (linhas ${f.top}..${f.bottom})`));
  // Todo quadro que o jogo pode pedir existe e tem desenho (espera, caminhada, prancheta).
  for (const dir of ['down', 'left', 'up', 'right']) for (const action of ['idle', 'walk', 'work']) for (let k = 0; k < 16; k++) {
    const idx = kirooFrame(dir, k / 16, action);
    assert.ok(frames[idx].opaque > 0, `${name}: ${dir}/${action}/${k} -> quadro ${idx}`);
  }
  console.log(`${name}: ${FRAMES} quadros 32x32, todos com desenho; quadros usados pelo jogo ok`);
}
