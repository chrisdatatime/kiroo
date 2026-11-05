// Gera os ícones e imagens da marca Kiroo a partir dos vetores oficiais em ../src/img/svg (não redesenha nada).
// Rodar: npm run brand:assets   (reproduzível; sobrescreve public/ e src/assets/brand/)
//
// Saídas em public/ (copiadas para a raiz do dist pelo Vite e servidas pelo servidor Python):
//   favicon.svg            cabeça do agente; tinta no tema claro, off-white no escuro (prefers-color-scheme)
//   favicon.ico            16 + 32 px (PNG dentro do ICO), do ícone de app tinta
//   apple-touch-icon.png   180 px, quadrado tinta sem cantos (o iOS arredonda)
//   icon-192.png, icon-512.png       ícone de app tinta, raio 25%, cabeça laranja (arquivo como está)
//   icon-maskable-512.png  mesmo ícone em quadrado cheio (a plataforma recorta; cabeça dentro da zona segura)
//   og-image.png           1200x630, wordmark sobre #FAFAF8
// Saídas em src/assets/brand/: cópias dos SVG usados pela interface (sem alteração).
import { Resvg } from '@resvg/resvg-js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const front = path.resolve(here, '..');
const SRC = path.resolve(front, '../src/img/svg');
const PUB = path.join(front, 'public');
const BRAND = path.join(front, 'src/assets/brand');
const PAPER = '#FAFAF8';

const read = (name) => fs.readFileSync(path.join(SRC, name), 'utf8');
const stripMeta = (svg) => svg.replace(/<metadata>[\s\S]*?<\/metadata>/g, '');
const png = (svg, width, background) =>
  new Resvg(stripMeta(svg), { fitTo: { mode: 'width', value: width }, background }).render().asPng();

// Caminho da cabeça, lido do símbolo oficial (o mesmo do wordmark e do ícone).
const symbol = stripMeta(read('simbolo-preto.svg'));
const HEAD = symbol.match(/ d="([^"]+)"/)[1];
const SYMBOL_VIEWBOX = symbol.match(/viewBox="([^"]+)"/)[1];
const SYMBOL_TRANSFORM = (symbol.match(/<path[^>]*transform="([^"]+)"/) || [])[1] || '';

function faviconSvg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${SYMBOL_VIEWBOX}"><style>path{fill:#0E0E10}@media (prefers-color-scheme: dark){path{fill:#FAFAF8}}</style><path fill-rule="evenodd" transform="${SYMBOL_TRANSFORM}" d="${HEAD}"/></svg>\n`;
}

function ico(images) { // [{size, data: Buffer PNG}]
  const head = Buffer.alloc(6 + 16 * images.length);
  head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(images.length, 4);
  let offset = head.length;
  images.forEach(({ size, data }, i) => {
    const e = 6 + 16 * i;
    head.writeUInt8(size >= 256 ? 0 : size, e); head.writeUInt8(size >= 256 ? 0 : size, e + 1);
    head.writeUInt8(0, e + 2); head.writeUInt8(0, e + 3);
    head.writeUInt16LE(1, e + 4); head.writeUInt16LE(32, e + 6);
    head.writeUInt32LE(data.length, e + 8); head.writeUInt32LE(offset, e + 12);
    offset += data.length;
  });
  return Buffer.concat([head, ...images.map((x) => x.data)]);
}

function ogImage() {
  const w = stripMeta(read('wordmark-preto-laranja.svg'));
  const vb = w.match(/viewBox="([^"]+)"/)[1];
  const inner = w.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '');
  const W = 1200, H = 630, ww = 520, wh = ww * (Number(vb.split(/\s+/)[3]) / Number(vb.split(/\s+/)[2]));
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><rect width="${W}" height="${H}" fill="${PAPER}"/><svg x="${(W - ww) / 2}" y="${(H - wh) / 2}" width="${ww}" height="${wh}" viewBox="${vb}">${inner}</svg></svg>`;
}

fs.mkdirSync(PUB, { recursive: true });
fs.mkdirSync(BRAND, { recursive: true });

const appIcon = read('icone-app-preto.svg');
const fullBleed = appIcon.replace(/rx="25"/, 'rx="0"');
const out = {
  'favicon.svg': faviconSvg(),
  'favicon.ico': ico([16, 32].map((size) => ({ size, data: png(appIcon, size) }))),
  'apple-touch-icon.png': png(fullBleed, 180),
  'icon-192.png': png(appIcon, 192),
  'icon-512.png': png(appIcon, 512),
  'icon-maskable-512.png': png(fullBleed, 512),
  'og-image.png': new Resvg(ogImage()).render().asPng(),
};
for (const [name, data] of Object.entries(out)) fs.writeFileSync(path.join(PUB, name), data);

for (const name of ['wordmark-preto-laranja.svg', 'wordmark-branco-laranja.svg', 'simbolo-laranja.svg', 'icone-app-preto.svg']) {
  fs.copyFileSync(path.join(SRC, name), path.join(BRAND, name));
}
console.log(`marca: ${Object.keys(out).length} arquivos em public/ e 4 SVG em src/assets/brand/`);
