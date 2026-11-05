// Base da pixel art: paleta da Kiroo, um "pincel" de pixels e cache de sprites desenhados em canvas pequenos.
// Todo sprite é desenhado em pixels de mundo (1 tile = 16 px) e ampliado pela câmera sem suavização.

export const PAL = {
  navy: '#17234B', navy2: '#26335F', ink: '#2B2F45', cream: '#FFF8EC', cream2: '#F3E6CF', lime: '#D5F45B', limeD: '#A9C83A', limeL: '#E9FA9E',
  sky: '#8ED8F8', skyD: '#5FB2DA', skyL: '#C8EEFC', lav: '#B8B4DE', lavD: '#958FC6', lavL: '#D9D6EE',
  wood: '#E2B37C', woodL: '#F0CB98', woodD: '#C08B55', woodDD: '#8E6238', white: '#FFFFFF', gray: '#CDD2DC', grayD: '#8A90A3', grayDD: '#5A6070',
  dark: '#2A2C38', dark2: '#1C1D2B', coral: '#FF7A8A', coralD: '#D9566A', pink: '#FF8FC0', sun: '#F5C542', sunD: '#D9A520', orange: '#FF9A3D',
  green: '#58B368', greenD: '#2F7D4A', greenL: '#8FD68F', pot: '#E0835A', potD: '#B5603D', teal: '#4FD0BF',
};

const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
export function shade(hex, amt) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  if (amt < 0) { r *= 1 + amt; g *= 1 + amt; b *= 1 + amt; } else { r += (255 - r) * amt; g += (255 - g) * amt; b += (255 - b) * amt; }
  return '#' + ((1 << 24) | (clamp(r) << 16) | (clamp(g) << 8) | clamp(b)).toString(16).slice(1);
}

// Pseudoaleatório estável: o mesmo móvel sempre sai igual
export function rng(seed) {
  let s = 0; for (const ch of String(seed)) s = (s * 31 + ch.charCodeAt(0)) >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

export class Px {
  constructor(ctx) { this.c = ctx; }
  r(x, y, w, h, col) { if (w <= 0 || h <= 0 || !col) return; this.c.fillStyle = col; this.c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); }
  p(x, y, col) { this.r(x, y, 1, 1, col); }
  // retângulo com contorno de 1 px (o contorno escuro deixa tudo legível no estilo do kit)
  box(x, y, w, h, fill, line = PAL.ink) { this.r(x, y, w, h, line); this.r(x + 1, y + 1, w - 2, h - 2, fill); }
  ell(cx, cy, rx, ry, col) {
    for (let y = -Math.ceil(ry); y <= Math.ceil(ry); y++) for (let x = -Math.ceil(rx); x <= Math.ceil(rx); x++) {
      if ((x * x) / (rx * rx) + (y * y) / (ry * ry) <= 1.0001) this.p(cx + x, cy + y, col);
    }
  }
  // elipse com contorno
  oval(cx, cy, rx, ry, fill, line = PAL.ink) { this.ell(cx, cy, rx, ry, line); if (rx > 1 && ry > 1) this.ell(cx, cy, rx - 1, ry - 1, fill); }
}

export function sprite(w, h, paint) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, w); c.height = Math.max(1, h);
  const meta = paint(new Px(c.getContext('2d')), w, h) || {};
  c.meta = meta;
  return c;
}

const cache = new Map();
export function cached(key, make) {
  if (!cache.has(key)) cache.set(key, make());
  return cache.get(key);
}
