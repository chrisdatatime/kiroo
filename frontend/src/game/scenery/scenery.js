// Cenário de fundo atrás do mapa (parallax). Lógica pura, testada em tests/scenery.test.mjs.
// Arte: "Forest of Illusion", Luis Zuno (ansimuz), licença do autor. Só back.png (160x272) e middle.png (384x272).
// Os PNGs ficam em assets/cenarios/floresta/ (fora do git; ver docs/ASSETS.md). Sem eles, o cenário é gerado por código.
export const LAYER_H = 272;
export const SCENERY_DIR = 'floresta'; // pasta em assets/cenarios/ com back.png e middle.png
export const SCENERY_FILES = { back: 'back.png', middle: 'middle.png' };
export const SCENERY_THEMES = ['floresta', 'gerado'];
export const DEFAULT_THEME = 'floresta';
export const THEME_KEY = 'bc.cenario';
export const THEME_LABELS = { floresta: 'Floresta', gerado: 'Gerado por código' };
// Crédito exibido em Sobre e créditos. Informe a página de origem em `url` (vazio = sem link).
export const SCENERY_CREDIT = { text: 'Forest of Illusion, Luis Zuno (ansimuz), licença do autor', url: '' };
// Parallax discreto: fração do deslocamento da câmera (a camada de trás anda menos).
export const PARALLAX = { back: 0.06, middle: 0.14 };
// Escurecimento leve e pouco contraste: o mapa é visto de cima e o fundo não pode competir com ele.
export const BACKDROP_FILTER = 'brightness(.78) saturate(.8) contrast(.9)';

export function normalizeTheme(t) { return SCENERY_THEMES.includes(t) ? t : DEFAULT_THEME; }

// Escala INTEIRA (x2, x3, x4) das camadas pela altura da viewport: a maior em que a faixa de 272 px ainda cabe.
export function pickScale(viewH) {
  const h = Number(viewH) || 0;
  const s = Math.floor(h / LAYER_H);
  return Math.min(4, Math.max(2, s));
}
// Escala em pixels do dispositivo: inteira também no dispositivo (sem blur com DPR fracionário).
export function deviceScale(scale, dpr = 1) { return Math.max(1, Math.round(scale * (dpr > 0 ? dpr : 1))); }

// Primeiro x (em px de tela, <= 0 ... < tileW) para repetir a camada na horizontal, com o deslocamento de parallax.
export function tileStart(offset, tileW) {
  if (!(tileW > 0)) return 0;
  const m = ((offset % tileW) + tileW) % tileW;
  return m === 0 ? 0 : m - tileW;
}
// Deslocamento de uma camada: posição da câmera (px) x fator. Movimento reduzido = parado.
export function layerOffset(camX, factor, reduced) { return reduced ? 0 : Math.round(-camX * factor); }
// Faixa vertical centralizada: { y, h } em px.
export function bandRect(viewH, scale) { const h = LAYER_H * scale; return { y: Math.round((viewH - h) / 2), h }; }

// Cor média (rgb) da linha de cima e da de baixo de uma imagem RGBA (ImageData.data), ignorando pixels transparentes.
export function sampleEdges(data, w, h) {
  const row = (y) => {
    let r = 0, g = 0, b = 0, n = 0;
    for (let x = 0; x < w; x += 1) { const i = (y * w + x) * 4; if (data[i + 3] > 8) { r += data[i]; g += data[i + 1]; b += data[i + 2]; n += 1; } }
    return n ? [Math.round(r / n), Math.round(g / n), Math.round(b / n)] : null;
  };
  let top = null, bottom = null;
  for (let y = 0; y < h && !top; y += 1) top = row(y);
  for (let y = h - 1; y >= 0 && !bottom; y -= 1) bottom = row(y);
  return { top: top || [233, 232, 228], bottom: bottom || top || [233, 232, 228] };
}
export const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

// Cenário gerado por código (fallback): devolve camadas como funções de desenho em canvas 2D, no tamanho nativo
// (160x272 e 384x272), com tokens da marca: papel/areia (#E9E8E4), tinta (#0E0E10) e um toque do laranja (#FF5B2E).
// Tudo periódico no eixo x, então repete sem emenda.
const hash = (n) => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };
export const GEN = {
  skyTop: [233, 232, 228], skyBottom: [247, 214, 196], hillFar: [196, 200, 190], hillNear: [160, 170, 158], tree: [74, 88, 78], ground: [54, 66, 58],
};
// Altura (px nativos) da colina/floresta em cada x, periódica em `period`.
export function skyline(x, period, base, amp, seed) {
  const t = (x / period) * Math.PI * 2;
  return Math.round(base + Math.sin(t * 2 + seed) * amp + Math.sin(t * 5 + seed * 2) * amp * 0.4);
}
export function treeLine(x, period, base, seed) {
  // silhueta de copas: degraus de 4 px com altura pseudoaleatória que fecha o período
  const cell = Math.floor(x / 4) % (period / 4);
  const wrap = (c) => hash(((c % (period / 4)) + period / 4) % (period / 4) + seed);
  return Math.round(base - 14 - wrap(cell) * 26 - wrap(cell + 1) * 8);
}
