// DEPRECATED (SPEC-VIS-001): o mundo vai migrar para tileset LimeZu + Tiled + Phaser 3. Não acrescente móveis
// nem paredes desenhados por código aqui; veja docs/SPEC-VIS-001.md. Mantido até a Fase 2 ser validada.
// Sprites de móveis, cadeiras e telas, em pixel art. Cada sprite ocupa a pegada do móvel (w x h tiles) e pode
// subir acima dela (meta.oh = altura extra em px), como no RPG visto de cima em 3/4.
import { PAL, shade, rng, sprite, cached } from './draw.js';

const T = 16;

// ---------------------------------------------------------------- telas dos monitores
export function paintScreen(g, x, y, w, h, type, t = 0) {
  const R = (a, b, c, d, col) => g.r(x + a, y + b, c, d, col);
  switch (type) {
    case 'planning': R(0, 0, w, h, PAL.cream); [PAL.lime, PAL.sky, PAL.pink].forEach((c, k) => { for (let n = 0; n < 3 - k; n++) R(1 + k * Math.floor(w / 3), 1 + n * 4, Math.floor(w / 3) - 2, 3, c); }); break;
    case 'sheet': R(0, 0, w, h, PAL.white); R(1, 1, 6, 5, PAL.skyL); R(2, 3, 4, 3, PAL.sky); for (let k = 0; k < 4; k++) R(8, 1 + k * 3, w - 10, 1, PAL.grayD); break;
    case 'story': R(0, 0, w, h, PAL.navy); for (let k = 0; k < 6; k++) R(1 + (k % 3) * Math.floor(w / 3), 1 + Math.floor(k / 3) * Math.floor(h / 2), Math.floor(w / 3) - 2, Math.floor(h / 2) - 2, k % 2 ? PAL.cream : PAL.sky); break;
    case 'script': R(0, 0, w, h, PAL.white); R(1, 1, 8, 2, PAL.navy); for (let k = 0; k < 4; k++) R(1, 4 + k * 2, w - 3 - (k % 2) * 4, 1, PAL.grayD); break;
    case 'image': R(0, 0, w, h, PAL.skyL); R(0, Math.floor(h * 0.55), w, h, PAL.greenL); g.p(x + w - 5, y + 2, PAL.sun); R(w - 6, 2, 3, 2, PAL.sun);
      for (let k = 0; k < w; k++) { const m = Math.floor(h * 0.55) - Math.max(0, 5 - Math.abs(k - Math.floor(w / 3)) * 0.8); R(k, m, 1, h, PAL.green); } R(0, h - 2, w, 2, PAL.greenD); break;
    case 'palette': R(0, 0, w, h, PAL.dark); [PAL.pink, PAL.sun, PAL.lime, PAL.sky, PAL.lav, PAL.coral].forEach((c, k) => R(1 + (k % 3) * 6, 1 + Math.floor(k / 3) * 6, 5, 5, c)); break;
    case 'video': R(0, 0, w, h, PAL.dark2); R(1, 1, w - 2, h - 4, PAL.sky); R(Math.floor(w / 2) - 1, Math.floor(h / 2) - 3, 1, 5, PAL.cream); R(Math.floor(w / 2), Math.floor(h / 2) - 2, 1, 3, PAL.cream); R(Math.floor(w / 2) + 1, Math.floor(h / 2) - 1, 1, 1, PAL.cream);
      R(1, h - 2, Math.floor((w - 2) * ((t % 8) / 8 + 0.1)), 1, PAL.coral); g.p(x + w - 3, y + 2, PAL.coral); break;
    case 'wave': R(0, 0, w, h, PAL.dark); for (let k = 0; k < w - 2; k++) { const a = Math.round(Math.abs(Math.sin(k * 0.9 + t)) * (h / 2 - 2)) + 1; R(1 + k, Math.floor(h / 2) - a, 1, a * 2, k % 4 ? PAL.sun : PAL.lime); } break;
    case 'timeline': case 'timelineWide': R(0, 0, w, h, PAL.dark2); R(1, 1, Math.floor(w * 0.45), Math.floor(h * 0.45), PAL.sky);
      [[PAL.sky, 0.0, 0.35], [PAL.lime, 0.36, 0.3], [PAL.pink, 0.67, 0.3]].forEach(([c, a, b], k) => R(1 + Math.floor((w - 2) * a), Math.floor(h * 0.55) + (k % 2), Math.floor((w - 2) * b), 2, c));
      R(1, h - 3, w - 2, 2, PAL.sunD); R(1 + Math.floor((w - 3) * ((t % 6) / 6)), Math.floor(h * 0.5), 1, Math.ceil(h * 0.5) - 1, PAL.coral); break;
    case 'review': R(0, 0, w, h, PAL.cream); R(1, 1, Math.floor(w / 2) - 2, h - 2, PAL.sky); R(Math.floor(w / 2) + 1, 1, Math.floor(w / 2) - 2, h - 2, PAL.limeL);
      [[0, 2], [1, 3], [2, 2], [3, 1], [4, 0]].forEach(([a, b]) => g.p(x + Math.floor(w * 0.66) + a, y + Math.floor(h / 2) - 1 + b, PAL.greenD)); break;
    case 'checklist': R(0, 0, w, h, PAL.white); for (let k = 0; k < 4; k++) { R(1, 1 + k * 3, 2, 2, k < 2 ? PAL.green : PAL.gray); R(4, 2 + k * 3, w - 6, 1, PAL.grayD); } break;
    case 'overview': R(0, 0, w, h, PAL.navy); [0.8, 0.5, 0.65, 0.3].forEach((v, k) => R(2 + k * 4, h - 2 - Math.round((h - 4) * v), 3, Math.round((h - 4) * v), k % 2 ? PAL.sky : PAL.lime)); break;
    default: R(0, 0, w, h, PAL.skyD);
  }
}

// ---------------------------------------------------------------- mesa com monitores
export function deskSprite(w, h, screens = [], opts = {}) {
  const key = `desk|${w}|${h}|${screens.join(',')}|${JSON.stringify(opts)}`;
  return cached(key, () => {
    const W = w * T, oh = 16, H = h * T + oh;
    return sprite(W, H, (g) => {
      const top = opts.top || PAL.woodL, edge = opts.edge || PAL.woodD, leg = opts.leg || PAL.woodDD;
      const ty = oh + 2, th = h * T - 9;
      g.box(0, ty, W, th, top);
      for (let y = ty + 5; y < ty + th - 2; y += 6) g.r(1, y, W - 2, 1, shade(top, -0.05));
      g.box(0, ty + th - 1, W, 6, edge);
      g.r(3, ty + th + 1, W - 6, 1, shade(edge, -0.15));
      g.r(2, ty + th + 5, 2, 2, leg); g.r(W - 4, ty + th + 5, 2, 2, leg);
      if (opts.led) g.r(2, ty + th + 3, W - 4, 1, opts.led);
      const ws = screens.map((s) => (s === 'timelineWide' ? 40 : s === 'notebook' ? 18 : s === 'retro' ? 20 : 24));
      const total = ws.reduce((a, b) => a + b, 0) + Math.max(0, ws.length - 1) * 3;
      let sx = Math.round((W - total) / 2);
      const meta = [];
      screens.forEach((type, k) => {
        const sw = ws[k], sh = type === 'notebook' ? 11 : 15, sy = ty + 3 - sh;
        if (type === 'notebook') {
          g.box(sx, ty + 2, sw, 5, PAL.gray, PAL.grayDD);
          g.box(sx + 1, sy + 3, sw - 2, sh - 2, PAL.dark2);
          meta.push({ x: sx + 2, y: sy + 4, w: sw - 4, h: sh - 4, type: opts.screen || 'overview' });
        } else if (type === 'retro') {
          g.box(sx, sy - 2, sw, sh + 5, '#E9DFC8', PAL.grayDD); g.r(sx + 2, sy + sh, sw - 4, 2, '#D3C6A8');
          g.box(sx + 3, sy + 1, sw - 6, sh - 4, PAL.dark2);
          meta.push({ x: sx + 4, y: sy + 2, w: sw - 8, h: sh - 6, type: 'overview' });
          g.p(sx + sw - 4, sy + sh + 1, PAL.coral);
        } else {
          g.r(sx + sw / 2 - 1, ty + 1, 3, 4, PAL.grayDD); g.r(sx + sw / 2 - 4, ty + 4, 9, 2, PAL.grayDD);
          g.box(sx, sy, sw, sh, PAL.dark2);
          meta.push({ x: sx + 1, y: sy + 1, w: sw - 2, h: sh - 2, type });
        }
        sx += sw + 3;
      });
      meta.forEach((m) => paintScreen(g, m.x, m.y, m.w, m.h, m.type));
      const fy = ty + th - 8;
      if (!opts.noKeyboard) {
        g.box(Math.round(W / 2) - 9, fy, 18, 5, PAL.gray, PAL.grayDD);
        for (let k = 0; k < 7; k++) g.p(Math.round(W / 2) - 7 + k * 2, fy + 2, PAL.grayDD);
        g.box(Math.round(W / 2) + 12, fy, 4, 5, PAL.white, PAL.grayDD);
      }
      if (opts.mug) { g.box(4, fy - 2, 5, 6, opts.mug); g.p(9, fy, PAL.ink); }
      if (!opts.bare) { g.box(W - 18, fy - 3, 11, 8, PAL.white, PAL.grayD); g.r(W - 16, fy - 1, 7, 1, PAL.gray); g.r(W - 16, fy + 1, 5, 1, PAL.gray); }
      return { oh, screens: meta };
    });
  });
}

// ---------------------------------------------------------------- cadeiras
// Devolve o assento (desenhado antes do personagem) e o encosto, quando ele fica na frente de quem senta.
export function chairSprites(face, kind, color) {
  return cached(`chair|${face}|${kind}|${color}`, () => {
    const oh = 8, W = 16, H = T + oh;
    const c = color || { agent: '#3A4A8C', visitor: PAL.coral, meeting: PAL.green, cafe: PAL.woodD, mine: '#3A4A8C', stool: PAL.woodD }[kind] || PAL.navy2;
    const hi = shade(c, 0.22), lo = shade(c, -0.22);
    if (kind === 'beanbag') {
      return { seat: sprite(W, H, (g) => { g.oval(8, oh + 9, 7, 6, c); g.ell(7, oh + 7, 4, 2, hi); g.ell(9, oh + 11, 4, 2, lo); return { oh }; }), back: null };
    }
    if (kind === 'ball') {
      return { seat: sprite(W, H, (g) => { g.oval(8, oh + 8, 6, 6, c); g.ell(6, oh + 6, 2, 2, hi); return { oh }; }), back: null };
    }
    if (kind === 'stool') {
      return { seat: sprite(W, H, (g) => { g.r(4, oh + 10, 1, 5, PAL.woodDD); g.r(11, oh + 10, 1, 5, PAL.woodDD); g.oval(8, oh + 9, 5, 3, PAL.woodL); return { oh }; }), back: null };
    }
    const office = kind === 'agent' || kind === 'visitor' || kind === 'mine';
    const base = (g) => {
      if (office) { g.r(7, oh + 11, 2, 3, PAL.grayDD); g.r(3, oh + 13, 10, 1, PAL.grayDD); g.p(3, oh + 14, PAL.ink); g.p(12, oh + 14, PAL.ink); g.p(7, oh + 14, PAL.ink); }
      else { g.r(4, oh + 11, 1, 4, PAL.woodDD); g.r(11, oh + 11, 1, 4, PAL.woodDD); }
    };
    const seatBox = (g) => { g.box(3, oh + 4, 10, 8, c); g.r(4, oh + 5, 8, 1, hi); };
    const backH = office ? 11 : 8;
    if (face === 'up') {
      return {
        seat: sprite(W, H, (g) => { base(g); seatBox(g); return { oh }; }),
        back: sprite(W, H, (g) => { g.box(3, oh + 8 - backH + 7, 10, backH, c); g.r(4, oh + 9 - backH + 7, 8, 1, hi); g.r(4, oh + 7 + backH - 2, 8, 1, lo); return { oh }; }),
      };
    }
    return {
      seat: sprite(W, H, (g) => {
        base(g);
        if (face === 'down') { g.box(3, oh + 5 - backH, 10, backH + 1, c); g.r(4, oh + 6 - backH, 8, 1, hi); seatBox(g); }
        else { seatBox(g); const bx = face === 'left' ? 11 : 1; g.box(bx, oh + 4 - backH + 6, 4, backH + 2, c); g.r(bx + 1, oh + 5 - backH + 6, 2, 1, hi); }
        return { oh };
      }),
      back: null,
    };
  });
}

// ---------------------------------------------------------------- móveis
function bookRow(g, x, y, w, h, r, palette) {
  let bx = x;
  while (bx < x + w - 2) {
    const bw = 2 + Math.floor(r() * 2), bh = h - Math.floor(r() * 3);
    g.r(bx, y + (h - bh), bw, bh, palette[Math.floor(r() * palette.length)]);
    g.r(bx, y + (h - bh), bw, 1, PAL.ink);
    bx += bw + (r() < 0.15 ? 2 : 0);
  }
}

function shelfFrame(g, W, H, wood = PAL.woodD) {
  g.box(0, 2, W, H - 3, wood);
  g.r(2, 4, W - 4, H - 8, PAL.woodDD);
  [13, 23].forEach((y) => g.r(1, y, W - 2, 2, wood));
  g.r(1, H - 3, W - 2, 1, PAL.ink);
}

function table(g, W, H, oh, top = PAL.woodL) {
  g.box(1, oh + 2, W - 2, H - oh - 8, top);
  g.r(2, oh + 3, W - 4, 1, shade(top, 0.25));
  g.box(1, H - 7, W - 2, 4, PAL.woodD);
  g.r(3, H - 3, 2, 3, PAL.woodDD); g.r(W - 5, H - 3, 2, 3, PAL.woodDD);
}

const notes = (g, x, y, cols, r) => cols.forEach((c, k) => { const nx = x + (k % 4) * 7 + Math.floor(r() * 2), ny = y + Math.floor(k / 4) * 6; g.r(nx, ny, 5, 4, c); g.p(nx + 2, ny, PAL.coralD); });

const PAINTERS = {
  plant: (w, h, o) => sprite(T, T + 14, (g) => {
    const oh = 14, v = o.v || 0;
    if (v === 1) {
      [[5, 6, PAL.green], [8, 2, PAL.greenD], [11, 8, PAL.green]].forEach(([x, y, c]) => { g.box(x - 1, y, 4, 24 - y, c, PAL.greenD); g.r(x, y + 2, 1, 18 - y, PAL.greenL); });
    } else if (v === 2) {
      g.oval(8, 14, 7, 7, PAL.greenD, PAL.ink); g.ell(7, 13, 5, 5, PAL.green); [[5, 10], [9, 9], [11, 13], [6, 15]].forEach(([x, y]) => g.r(x, y, 2, 1, PAL.greenL));
    } else {
      [[8, 15, 6, 5], [4, 18, 4, 3], [12, 18, 4, 3], [8, 9, 4, 5]].forEach(([x, y, rx, ry], k) => g.oval(x, y, rx, ry, k === 3 ? PAL.greenL : k % 2 ? PAL.greenD : PAL.green, PAL.ink));
      [[6, 13], [10, 12], [8, 7]].forEach(([x, y]) => g.p(x, y, PAL.limeL));
    }
    g.box(3, oh + 8, 10, 3, PAL.pot); g.box(4, oh + 10, 8, 6, PAL.potD); g.r(5, oh + 11, 6, 1, PAL.pot);
    return { oh };
  }),
  bookshelf: (w) => sprite(w * T, T + 20, (g, W, H) => { shelfFrame(g, W, H); const r = rng('books' + w);
    const cols = [PAL.coral, PAL.sky, PAL.lime, PAL.sun, PAL.lav, PAL.cream, PAL.pink, PAL.navy2];
    bookRow(g, 3, 5, W - 6, 8, r, cols); bookRow(g, 3, 15, W - 6, 8, r, cols); bookRow(g, 3, 25, W - 9, 6, r, cols);
    g.oval(W - 6, 27, 2, 2, PAL.green); return { oh: 20 }; }),
  artShelf: (w) => sprite(w * T, T + 20, (g, W, H) => { shelfFrame(g, W, H); const r = rng('art');
    for (let k = 0; k < w * 3; k++) { const x = 4 + k * 5; g.box(x, 7, 4, 6, [PAL.skyL, PAL.limeL, PAL.lavL][k % 3], PAL.grayD); g.r(x + 1, 4 + Math.floor(r() * 2), 1, 4, [PAL.coral, PAL.sun, PAL.navy2][k % 3]); }
    for (let k = 0; k < w * 2; k++) g.box(4 + k * 7, 17, 5, 6, k % 2 ? PAL.cream : PAL.white, PAL.grayD);
    bookRow(g, 3, 25, W - 6, 6, r, [PAL.lav, PAL.sky, PAL.coral]); return { oh: 20 }; }),
  paintShelf: (w) => sprite(w * T, T + 20, (g, W, H) => { shelfFrame(g, W, H);
    const cols = [PAL.pink, PAL.sun, PAL.lime, PAL.sky, PAL.lav, PAL.coral, PAL.orange, PAL.teal];
    for (let k = 0; k < w * 3; k++) { g.box(3 + k * 5, 7, 5, 6, PAL.gray, PAL.grayDD); g.r(4 + k * 5, 8, 3, 2, cols[k % cols.length]); }
    for (let k = 0; k < w * 2; k++) { g.box(4 + k * 7, 16, 6, 7, PAL.white, PAL.grayD); g.r(5 + k * 7, 18, 4, 3, cols[(k + 3) % cols.length]); }
    bookRow(g, 3, 25, W - 6, 6, rng('pt'), cols); return { oh: 20 }; }),
  cabinet: () => sprite(T, T + 10, (g) => { g.box(2, 3, 12, 22, PAL.gray, PAL.grayDD); [9, 16].forEach((y) => g.r(3, y, 10, 1, PAL.grayD)); [5, 12, 19].forEach((y) => g.r(6, y, 4, 1, PAL.grayDD)); return { oh: 10 }; }),
  boxes: () => sprite(2 * T, T + 8, (g) => { const c = '#D9A766'; g.box(1, 10, 15, 13, c); g.box(16, 12, 14, 11, shade(c, -0.08)); g.box(5, 2, 13, 10, shade(c, 0.1));
    [[1, 10, 15], [16, 12, 14], [5, 2, 13]].forEach(([x, y, w]) => g.r(x + Math.floor(w / 2) - 1, y + 1, 2, 3, '#B9874A')); g.r(8, 6, 6, 3, PAL.lime); g.r(19, 16, 6, 3, PAL.sky); return { oh: 8 }; }),
  meetingTable: (w, h, o) => sprite(w * T, h * T + 6, (g, W, H) => { const oh = 6; table(g, W, H, oh, o.review ? PAL.woodL : '#E9C795'); const r = rng('meet' + w + h);
    for (let k = 0; k < w; k++) { const x = 6 + k * 15, y = oh + 5 + (k % 2) * Math.max(4, h * 6); g.box(x, y, 9, 7, PAL.white, PAL.grayD);
      if (o.review) { g.r(x + 2, y + 2, 2, 1, k % 2 ? PAL.coral : PAL.green); g.r(x + 5, y + 2, 2, 1, PAL.grayD); g.r(x + 2, y + 4, 5, 1, PAL.grayD); } else { g.r(x + 2, y + 2, 5, 1, PAL.grayD); g.r(x + 2, y + 4, 4, 1, PAL.grayD); } }
    g.box(Math.round(W / 2) - 6, oh + 4, 12, 8, PAL.gray, PAL.grayDD); g.r(Math.round(W / 2) - 5, oh + 5, 10, 5, PAL.skyD);
    g.box(W - 9, H - 13, 4, 4, PAL.coral); g.box(5, H - 13, 4, 4, [PAL.sky, PAL.lime][Math.floor(r() * 2)]); return { oh }; }),
  refTable: (w, h) => sprite(w * T, h * T + 6, (g, W, H) => { const oh = 6; table(g, W, H, oh); const r = rng('ref');
    [PAL.sky, PAL.coral, PAL.lime, PAL.sun, PAL.lav, PAL.pink].forEach((c, k) => { const x = 5 + k * 9 + Math.floor(r() * 3), y = oh + 4 + (k % 2) * 7; g.box(x, y, 9, 7, PAL.white, PAL.grayD); g.r(x + 1, y + 1, 7, 4, c); g.p(x + 4, y, PAL.coralD); }); return { oh }; }),
  flipchart: () => sprite(T, T + 18, (g) => { g.r(3, 20, 1, 13, PAL.grayDD); g.r(12, 20, 1, 13, PAL.grayDD); g.r(7, 22, 2, 10, PAL.grayDD); g.box(1, 2, 14, 19, PAL.white, PAL.grayDD);
    g.r(3, 5, 9, 2, PAL.navy); [[3, 9, 8, PAL.coral], [3, 12, 6, PAL.sky], [3, 15, 9, PAL.lime]].forEach(([x, y, w, c]) => g.r(x, y, w, 1, c)); g.r(1, 1, 14, 2, PAL.grayDD); return { oh: 18 }; }),
  easel: () => sprite(T, T + 20, (g) => { for (let k = 0; k < 14; k++) { g.p(3 + Math.floor(k / 3), 34 - k, PAL.woodDD); g.p(12 - Math.floor(k / 3), 34 - k, PAL.woodDD); } g.r(7, 20, 2, 15, PAL.woodD);
    g.box(1, 3, 14, 15, PAL.cream, PAL.woodDD); [[3, 5, PAL.sky], [9, 5, PAL.coral], [3, 11, PAL.lime], [9, 11, PAL.lav]].forEach(([x, y, c]) => g.box(x, y, 5, 5, c, PAL.grayDD)); g.r(1, 17, 14, 2, PAL.woodD); return { oh: 20 }; }),
  printer: () => sprite(2 * T, T + 10, (g) => { g.box(1, 9, 30, 15, PAL.gray, PAL.grayDD); g.r(2, 10, 28, 3, PAL.white); g.box(5, 4, 22, 7, PAL.white, PAL.grayD); g.r(7, 5, 18, 4, PAL.pink); g.r(9, 6, 6, 2, PAL.sun);
    g.r(4, 16, 24, 1, PAL.grayDD); g.r(26, 19, 2, 2, PAL.lime); g.r(22, 19, 2, 2, PAL.grayDD); return { oh: 10 }; }),
  tabletDesk: (w, h) => sprite(w * T, h * T + 10, (g, W, H) => { const oh = 10; table(g, W, H, oh, PAL.lavL); g.box(6, oh + 6, 18, 12, PAL.dark2); g.r(8, oh + 8, 14, 8, PAL.skyL); g.r(10, oh + 12, 9, 1, PAL.coral);
    g.r(25, oh + 8, 1, 9, PAL.coral); g.r(26, oh + 2, 1, 6, PAL.grayDD); g.box(24, oh - 3, 6, 5, PAL.sun); return { oh }; }),
  sideTable: () => sprite(T, T + 8, (g) => { g.r(7, 16, 2, 8, PAL.woodDD); g.oval(8, 14, 7, 4, PAL.woodL); g.box(4, 9, 6, 4, PAL.coral); g.box(10, 8, 3, 4, PAL.white, PAL.grayD); return { oh: 8 }; }),
  prodBoard: (w) => sprite(w * T, T + 22, (g, W, H) => { g.r(4, 26, 2, 12, PAL.woodDD); g.r(W - 6, 26, 2, 12, PAL.woodDD); g.box(1, 2, W - 2, 26, PAL.woodD); g.r(3, 4, W - 6, 22, '#D9A866');
    g.r(3, 4, W - 6, 4, PAL.navy); g.r(5, 5, 8, 2, PAL.lime); notes(g, 5, 10, [PAL.lime, PAL.pink, PAL.white, PAL.sky, PAL.sun, PAL.white, PAL.lime, PAL.coral], rng('board')); return { oh: 22 }; }),
  coffeeBar: (w) => sprite(w * T, T + 16, (g, W, H) => { const oh = 16;
    g.box(0, oh + 6, W, 10, PAL.woodD); for (let x = 8; x < W; x += 16) g.r(x, oh + 8, 1, 7, PAL.woodDD);
    g.box(0, oh + 1, W, 7, PAL.cream2); g.r(1, oh + 2, W - 2, 1, PAL.white);
    g.box(4, 1, 18, 18, PAL.dark); g.r(6, 3, 14, 4, PAL.grayDD); g.r(17, 4, 2, 2, PAL.lime); g.r(8, 10, 3, 5, PAL.gray); g.r(15, 10, 3, 5, PAL.gray); g.box(8, 15, 4, 3, PAL.white, PAL.grayD);
    [[28, PAL.woodDD], [35, '#7A4E2A'], [42, PAL.woodD]].forEach(([x, c]) => { g.box(x, oh - 8, 6, 9, PAL.skyL, PAL.grayD); g.r(x + 1, oh - 4, 4, 4, c); g.r(x + 1, oh - 9, 4, 2, PAL.grayDD); });
    g.oval(56, oh - 2, 6, 3, PAL.white); g.box(52, oh - 7, 8, 4, PAL.pink); g.r(53, oh - 8, 6, 1, PAL.coral);
    [66, 71].forEach((x, k) => { g.box(x, oh - 5, 4, 6, k ? PAL.lime : PAL.sky); }); return { oh }; }),
  roundTable: () => sprite(2 * T, 2 * T + 6, (g, W) => { const oh = 6; g.r(14, 24, 4, 12, PAL.woodDD); g.oval(16, oh + 12, 14, 10, PAL.woodD); g.ell(16, oh + 11, 12, 8, PAL.woodL);
    g.box(9, oh + 7, 5, 5, PAL.white, PAL.grayD); g.r(10, oh + 8, 3, 2, '#7A4E2A'); g.box(19, oh + 12, 5, 5, PAL.white, PAL.grayD); g.oval(17, oh + 6, 3, 2, PAL.sun); return { oh }; }),
  lowTable: (w) => sprite(w * T, T + 4, (g, W) => { g.box(2, 6, W - 4, 10, PAL.woodL); g.box(2, 14, W - 4, 4, PAL.woodD); g.box(8, 8, 10, 6, PAL.sky); g.box(14, 9, 9, 6, PAL.coral); g.box(W - 14, 8, 5, 5, PAL.white, PAL.grayD); return { oh: 4 }; }),
  floorLamp: () => sprite(T, T + 22, (g) => { g.oval(8, 34, 5, 2, PAL.ink); g.r(7, 10, 2, 24, PAL.grayDD); g.r(3, 2, 10, 8, PAL.ink); g.r(4, 3, 8, 6, PAL.sun); g.r(5, 4, 6, 2, '#FFE9A8'); return { oh: 22 }; }),
  gamesTable: () => sprite(T, T + 4, (g) => { g.box(1, 5, 14, 12, PAL.woodL); g.box(1, 15, 14, 3, PAL.woodD); for (let k = 0; k < 16; k++) if ((k + Math.floor(k / 4)) % 2) g.r(4 + (k % 4) * 2, 7 + Math.floor(k / 4) * 2, 2, 2, PAL.navy);
    g.r(4, 7, 8, 8, 'rgba(0,0,0,0)'); g.p(5, 8, PAL.coral); g.p(10, 13, PAL.cream); return { oh: 4 }; }),
  waterCooler: () => sprite(T, T + 14, (g) => { g.box(3, 14, 10, 15, PAL.white, PAL.grayD); g.r(5, 18, 6, 1, PAL.grayD); g.r(7, 20, 2, 2, PAL.sky); g.box(4, 2, 8, 13, PAL.skyL, PAL.skyD); g.r(5, 4, 2, 9, PAL.white); g.r(5, 1, 6, 2, PAL.skyD); return { oh: 14 }; }),
  sofa: (w) => sprite(w * T, T + 8, (g, W) => { const body = PAL.cream2, dark = shade(body, -0.12);
    g.box(0, 1, W, 11, dark); g.box(2, 9, W - 4, 13, body); g.box(0, 6, 5, 17, dark); g.box(W - 5, 6, 5, 17, dark);
    for (let k = 0; k < w; k++) { g.box(5 + k * ((W - 10) / w), 10, (W - 10) / w - 1, 8, k % 2 ? PAL.skyL : PAL.limeL, shade(body, -0.25)); }
    g.box(6, 3, 8, 6, PAL.sky); g.box(W - 14, 3, 8, 6, PAL.lime); return { oh: 8 }; }),
  greenScreen: (w) => sprite(w * T, T + 30, (g, W, H) => { const cloth = '#6CCB4F';
    g.r(1, 0, 2, H - 2, PAL.grayDD); g.r(W - 3, 0, 2, H - 2, PAL.grayDD); g.r(1, 1, W - 2, 2, PAL.grayDD);
    g.r(4, 3, W - 8, 30, cloth); for (let x = 8; x < W - 6; x += 9) g.r(x, 3, 1, 30, shade(cloth, -0.12));
    g.r(4, 33, W - 8, H - 36, shade(cloth, 0.15)); g.r(4, 33, W - 8, 1, shade(cloth, -0.18)); return { oh: 30 }; }),
  pedestal: () => sprite(T, T + 10, (g) => { g.box(3, 12, 10, 13, PAL.cream2); g.oval(8, 12, 5, 2, PAL.cream); g.box(5, 4, 6, 8, PAL.coral); g.r(6, 5, 4, 1, shade(PAL.coral, 0.3)); return { oh: 10 }; }),
  softbox: (w, h, o) => sprite(T, T + 22, (g) => { [[8, 26], [4, 36], [12, 36]].forEach(([x, y], k) => { if (k) for (let s = 0; s < 10; s++) g.p(8 + (x - 8) * s / 10, 26 + s, PAL.grayDD); }); g.r(7, 12, 2, 15, PAL.grayDD);
    const right = o.face !== 'left'; g.box(1, 2, 14, 11, PAL.dark2); g.r(right ? 9 : 2, 3, 5, 9, '#FFF6D8'); g.r(right ? 10 : 3, 4, 3, 7, PAL.white); return { oh: 22 }; }),
  camera: () => sprite(T, T + 14, (g) => { for (let s = 0; s < 11; s++) { g.p(8 - s * 0.4, 18 + s, PAL.grayDD); g.p(8 + s * 0.4, 18 + s, PAL.grayDD); g.p(8, 18 + s, PAL.grayDD); }
    g.box(3, 9, 10, 9, PAL.dark2); g.box(6, 2, 4, 8, PAL.grayDD); g.r(7, 2, 2, 2, PAL.skyD); g.r(11, 10, 1, 1, PAL.coral); g.r(4, 14, 4, 2, PAL.skyD); return { oh: 14 }; }),
  musicShelf: (w) => sprite(w * T, T + 20, (g, W, H) => { shelfFrame(g, W, H, PAL.navy2);
    const cols = [PAL.lime, PAL.pink, PAL.sky, PAL.sun, PAL.lav, PAL.coral];
    for (let k = 0; k < w * 3; k++) { g.box(3 + k * 5, 5, 5, 8, cols[k % cols.length], PAL.ink); g.p(5 + k * 5, 8, PAL.ink); }
    for (let k = 0; k < w * 2; k++) { g.oval(7 + k * 8, 19, 3, 3, PAL.dark2, PAL.ink); g.p(7 + k * 8, 19, cols[(k + 2) % cols.length]); }
    g.r(6, 25, 1, 5, PAL.lime); g.r(4, 29, 3, 2, PAL.lime); g.r(7, 25, 3, 1, PAL.lime);
    g.r(14, 26, 1, 4, PAL.sky); g.r(12, 29, 3, 2, PAL.sky);
    g.r(W - 14, 25, 9, 1, PAL.ink); g.r(W - 14, 25, 1, 5, PAL.ink); g.r(W - 6, 25, 1, 5, PAL.ink); g.box(W - 16, 28, 4, 4, PAL.coral); g.box(W - 7, 28, 4, 4, PAL.coral); return { oh: 20 }; }),
  speaker: () => sprite(T, T + 10, (g) => { g.box(3, 3, 10, 22, PAL.dark2); g.oval(8, 9, 3, 3, PAL.grayDD); g.oval(8, 18, 4, 4, PAL.grayDD); g.p(8, 18, PAL.ink); g.p(8, 9, PAL.ink); return { oh: 10 }; }),
  mixer: (w) => sprite(w * T, T + 6, (g, W) => { g.box(1, 5, W - 2, 15, PAL.dark); g.r(2, 6, W - 4, 2, PAL.grayDD);
    for (let k = 0; k < w * 3; k++) { const x = 5 + k * 5; g.r(x, 9, 1, 8, PAL.ink); g.box(x - 1, 11 + (k * 7) % 5, 3, 2, [PAL.lime, PAL.sky, PAL.coral][k % 3]); g.p(x, 7, PAL.sun); } return { oh: 6 }; }),
  rack: (w) => sprite(w * T, T + 16, (g, W, H) => { g.box(1, 2, W - 2, H - 3, PAL.dark2); for (let y = 5; y < H - 4; y += 5) { g.r(3, y, W - 6, 3, PAL.dark); g.p(W - 6, y + 1, PAL.lime); g.p(W - 9, y + 1, PAL.sky); } return { oh: 16 }; }),
  compareScreen: (w) => sprite(w * T, T + 24, (g, W) => { g.r(6, 28, 2, 10, PAL.grayDD); g.r(W - 8, 28, 2, 10, PAL.grayDD); g.r(3, 37, 8, 2, PAL.grayDD); g.r(W - 11, 37, 8, 2, PAL.grayDD);
    const sw = Math.floor((W - 6) / 2); [0, 1].forEach((k) => { g.box(2 + k * (sw + 2), 4, sw, 24, PAL.dark2); paintScreen(g, 3 + k * (sw + 2), 5, sw - 2, 22, k ? 'review' : 'video'); }); return { oh: 24 }; }),
  checklistBoard: (w) => sprite(w * T, T + 22, (g, W) => { g.r(5, 26, 2, 12, PAL.grayDD); g.r(W - 7, 26, 2, 12, PAL.grayDD); g.box(1, 2, W - 2, 25, PAL.white, PAL.grayDD);
    for (let k = 0; k < 4; k++) { g.box(4, 5 + k * 5, 4, 4, PAL.white, PAL.grayD); if (k < 3) { g.p(5, 7 + k * 5, PAL.green); g.p(6, 8 + k * 5, PAL.green); g.p(7, 6 + k * 5, PAL.green); } g.r(10, 7 + k * 5, W - 16 - (k % 2) * 6, 1, PAL.grayD); }
    g.r(1, 26, W - 2, 2, PAL.grayDD); return { oh: 22 }; }),
};

// Itens pequenos sobre a mesa do Meu escritório
export const deskItem = {
  cat: (frame) => cached('cat' + frame, () => sprite(14, 10, (g) => { const o = '#F5A04A', d = '#D07A2A';
    g.oval(8, 6 - (frame ? 0 : 0), 5, 3 + (frame ? 0.4 : 0), o, PAL.ink); g.oval(3, 5, 2.6, 2.6, o, PAL.ink); g.p(1, 2, PAL.ink); g.p(4, 2, PAL.ink); g.p(2, 5, PAL.ink); g.p(4, 5, PAL.ink);
    g.r(12, 7, 2, 1, d); g.r(7, 4, 4, 1, d); })),
  lamp: () => cached('dlamp', () => sprite(10, 18, (g) => { g.oval(3, 16, 3, 1, PAL.ink); g.r(3, 6, 1, 10, PAL.ink); g.r(3, 6, 5, 1, PAL.ink); g.box(5, 5, 5, 4, PAL.sun); g.r(6, 9, 3, 1, '#FFE9A8'); })),
  plant: () => cached('dplant', () => sprite(10, 14, (g) => { g.oval(5, 5, 4, 4, PAL.green, PAL.greenD); g.p(4, 3, PAL.greenL); g.box(2, 8, 6, 5, PAL.pot); })),
};

export function furnitureSprite(f) {
  return cached(`f|${f.kind}|${f.w}|${f.h}|${JSON.stringify(f.opts || {})}`, () => PAINTERS[f.kind](f.w, f.h, f.opts || {}, f));
}

// ---------------------------------------------------------------- decoração de parede (na face visível)
// x, y em px de mundo do canto superior esquerdo da face; w em px; fh = altura da face.
export function paintWallDecor(g, kind, x, y, w, fh) {
  const r = rng(kind + x);
  if (kind === 'kanban') {
    g.box(x + 2, y + 2, w - 4, fh - 4, PAL.white, PAL.grayDD); g.r(x + 2, y + 2, w - 4, 3, PAL.navy);
    const cols = 3, cw = Math.floor((w - 8) / cols);
    for (let c = 0; c < cols; c++) { g.r(x + 4 + c * cw + cw - 1, y + 6, 1, fh - 10, PAL.gray); for (let n = 0; n < 3 - c % 2; n++) g.r(x + 5 + c * cw, y + 7 + n * 5, cw - 4, 4, [PAL.lime, PAL.sky, PAL.pink, PAL.sun][(c + n) % 4]); }
  } else if (kind === 'storyboard') {
    g.box(x + 2, y + 2, w - 4, fh - 4, PAL.dark, PAL.ink);
    const n = Math.floor((w - 6) / 13);
    for (let k = 0; k < n * 2; k++) { const fx = x + 5 + (k % n) * 13, fy = y + 5 + Math.floor(k / n) * 9; g.box(fx, fy, 11, 7, k % 2 ? PAL.cream : PAL.skyL, PAL.grayDD); g.r(fx + 2, fy + 2, 4, 3, [PAL.coral, PAL.lime, PAL.sky, PAL.sun][k % 4]); g.p(fx + 5, fy - 1, PAL.coral); }
  } else if (kind === 'gallery') {
    [[4, 3, 18, 14, PAL.pink], [26, 5, 12, 10, PAL.sky], [42, 2, 16, 18, PAL.lime], [62, 6, 14, 11, PAL.sun], [80, 4, 12, 14, PAL.lav]].forEach(([fx, fy, fw, fhh, c]) => {
      if (fx + fw > w) return; g.box(x + fx, y + fy, fw, fhh, PAL.woodDD, PAL.ink); g.r(x + fx + 2, y + fy + 2, fw - 4, fhh - 4, c); g.r(x + fx + 2, y + fy + fhh - 5, fw - 4, 3, shade(c, -0.25)); });
  } else if (kind === 'tv') {
    g.box(x + 6, y, w - 12, fh, PAL.dark2); paintScreen(g, x + 7, y + 1, w - 14, fh - 2, 'overview');
  } else if (kind === 'frames') {
    for (let k = 0; k * 14 + 12 <= w; k++) { const c = [PAL.lav, PAL.sky, PAL.lime, PAL.pink][Math.floor(r() * 4)]; g.box(x + 3 + k * 14, y + 1, 10, fh - 2, PAL.woodDD, PAL.ink); g.r(x + 5 + k * 14, y + 3, 6, fh - 6, c); }
  } else if (kind === 'panels') {
    for (let k = 0; k * 9 + 8 <= w; k++) g.box(x + 2 + k * 9, y + 1, 8, fh - 2, k % 2 ? PAL.lav : PAL.navy2, PAL.ink);
  }
}

// Janela: a foto (já pixelada no tamanho da janela) entra no vão; nuvens passam por cima no renderizador.
export function paintWindowFrame(g, x, y, w, h) {
  g.r(x, y, w, h, PAL.ink);
  g.r(x + 1, y + 1, w - 2, h - 2, PAL.skyL);
  return { gx: x + 2, gy: y + 2, gw: w - 4, gh: h - 5 };
}
export function paintWindowBars(g, x, y, w, h) {
  for (let bx = x + 16; bx < x + w - 4; bx += 16) g.r(bx, y + 1, 2, h - 2, PAL.cream);
  g.r(x, y + h - 3, w, 3, PAL.cream); g.r(x, y + h - 1, w, 1, PAL.cream2);
}
