// Mantido na migração SPEC-VIS-001: os dois arquivos do LimeZu liberados são cenário e móveis, não personagens.
// Personagens em pixel art: feijões com olhos grandes (o centro da identidade Pivoo).
// Sprite de 20x26 px; 4 direções (down/up/left/right) e poses stand, walk (4 quadros), sit, type, wave, happy.
import { PAL, shade, sprite, cached } from './draw.js';

export const CW = 20, CH = 26;

function bodyMask(cx, cy, rx, ry) {
  const inside = (x, y) => { const dx = x + 0.5 - cx, dy = y + 0.5 - cy; return (dx * dx) / (rx * rx) + (dy * dy) / (ry * ry) <= 1; };
  return inside;
}

export function charSprite(look, dir = 'down', pose = 'stand', frame = 0, opts = {}) {
  const gx = opts.gx || 0, gy = opts.gy || 0, blink = !!opts.blink, wide = !!opts.wide;
  const key = `ch|${look.shirt}|${look.acc}|${look.cap || ''}|${dir}|${pose}|${frame}|${gx}|${gy}|${blink}|${wide}`;
  return cached(key, () => sprite(CW, CH, (g) => {
    const base = look.shirt || PAL.lime;
    const line = shade(base, -0.58), dark = shade(base, -0.16), light = shade(base, 0.32);
    const walk = pose === 'walk', sit = pose === 'sit' || pose === 'type';
    const bob = walk && frame % 2 ? -1 : pose === 'stand' && frame === 1 ? 1 : 0;
    const cx = 10, cy = 14 + bob, rx = 7, ry = sit ? 7.6 : 8;
    const inside = bodyMask(cx, cy, rx, ry);

    // sombra e pés
    if (!sit) {
      g.c.fillStyle = 'rgba(23,35,75,0.22)'; g.c.fillRect(5, 23, 10, 2); g.c.fillRect(4, 24, 12, 1);
      const lift = (k) => (walk && ((frame === 1 && k === 0) || (frame === 3 && k === 1)) ? -1 : 0);
      const feet = dir === 'left' || dir === 'right' ? [6, 11] : [5, 11];
      feet.forEach((fx, k) => { g.r(fx, 21 + lift(k), 4, 3, PAL.navy); g.r(fx + 1, 21 + lift(k), 2, 1, PAL.navy2); });
    } else if (dir === 'down') {
      g.r(6, 20, 3, 2, PAL.navy); g.r(11, 20, 3, 2, PAL.navy);
    }

    // corpo com contorno, sombra lateral e brilho
    for (let y = 0; y < CH; y++) for (let x = 0; x < CW; x++) {
      if (!inside(x, y)) continue;
      const edge = !inside(x - 1, y) || !inside(x + 1, y) || !inside(x, y - 1) || !inside(x, y + 1);
      const dx = x + 0.5 - cx, dy = y + 0.5 - cy;
      let col = base;
      const shadeSide = dir === 'left' ? dx < -rx * 0.35 : dx > rx * 0.38;
      if (shadeSide && dy > -ry * 0.6) col = dark;
      if (dy > ry * 0.62) col = dark;
      const hx = dir === 'right' ? 2.5 : dir === 'left' ? -1.5 : -3;
      if ((dx - hx) * (dx - hx) + (dy + 4.6) * (dy + 4.6) <= 2.2) col = light;
      g.p(x, y, edge ? line : col);
    }

    // olhos
    const eyeY = cy - 3;
    const eye = (ex, px, closed) => {
      const R = wide ? 3 : 2.6;
      for (let y = -3; y <= 3; y++) for (let x = -3; x <= 3; x++) {
        const d = Math.sqrt((x + 0.5) * (x + 0.5) + (y + 0.5) * (y + 0.5));
        if (d <= R) g.p(ex + x, eyeY + y, closed ? base : (d > R - 1 ? PAL.navy : PAL.white));
      }
      if (closed) { g.r(ex - 2, eyeY, 4, 1, PAL.navy); return; }
      g.r(ex - 1 + px, eyeY - 1 + gy, 2, 2, PAL.navy);
      g.p(ex + px, eyeY - 1 + gy, PAL.white);
    };
    if (dir === 'down') { eye(7, gx, blink); eye(13, gx, blink); }
    else if (dir === 'left') { eye(5, -1, blink); eye(10, -1, blink); }
    else if (dir === 'right') { eye(15, 0, blink); eye(10, 0, blink); }

    // boca
    const my = cy + 2;
    const happy = pose === 'happy' || pose === 'wave';
    if (dir === 'down') {
      if (happy) { g.r(9, my, 3, 2, PAL.navy); g.p(10, my + 1, PAL.coral); }
      else { g.p(9, my, PAL.navy); g.p(10, my + 1, PAL.navy); g.p(11, my, PAL.navy); }
    } else if (dir === 'left') { g.p(4, my, PAL.navy); g.p(5, my + 1, PAL.navy); }
    else if (dir === 'right') { g.p(16, my, PAL.navy); g.p(15, my + 1, PAL.navy); }

    // braços
    const arm = (ax, ay) => { g.oval(ax, ay, 1.6, 2.6, base, line); };
    if (dir === 'left' || dir === 'right') {
      const sw = walk ? (frame === 1 ? -1 : frame === 3 ? 1 : 0) : 0;
      if (pose === 'type' || pose === 'sit') arm(dir === 'left' ? 6 : 14, cy + 1);
      else if (pose === 'wave' || pose === 'happy') arm(dir === 'left' ? 7 : 13, cy - 7 + (frame % 2));
      else arm(10 + sw, cy + 2);
    } else if (pose === 'type' && dir === 'up') { arm(5, cy - 1 + (frame % 2)); arm(15, cy - 1 + ((frame + 1) % 2)); }
    else if (pose === 'happy') { arm(3, cy - 7); arm(17, cy - 7); }
    else if (pose === 'wave') { arm(3, cy + 2); arm(17 + (frame % 2), cy - 7); }
    else { const s = walk ? (frame === 1 ? 1 : frame === 3 ? -1 : 0) : 0; arm(3, cy + 2 + s); arm(17, cy + 2 - s); }

    // acessórios
    const top = (col, rows) => {
      for (let y = 0; y <= rows; y++) for (let x = 0; x < CW; x++) if (inside(x, y)) {
        const edge = !inside(x - 1, y) || !inside(x + 1, y) || !inside(x, y - 1);
        g.p(x, y, edge ? shade(col, -0.45) : col);
      }
    };
    const acc = look.acc || 'nenhum';
    const capRow = Math.floor(cy - 6.5);
    if (acc === 'bone') {
      const c = look.cap || PAL.navy;
      top(c, capRow);
      if (dir === 'down') { g.r(3, capRow + 1, 14, 1, shade(c, 0.25)); g.r(9, capRow - 3, 2, 2, PAL.lime); }
      else if (dir === 'left') g.r(1, capRow + 1, 9, 1, shade(c, 0.25));
      else if (dir === 'right') g.r(10, capRow + 1, 9, 1, shade(c, 0.25));
    } else if (acc === 'boina') {
      const c = look.cap || PAL.sun;
      top(c, capRow);
      g.r(4, capRow - 1, 12, 2, shade(c, 0.28)); for (let x = 5; x < 16; x += 2) g.p(x, capRow - 1, shade(c, -0.1));
      g.oval(10, cy - 9, 1.8, 1.8, shade(c, 0.35), shade(c, -0.4));
    } else if (acc === 'fones') {
      for (let x = 3; x < 17; x++) { let y = 0; while (y < CH && !inside(x, y)) y++; if (y < CH) g.p(x, y - 1, PAL.ink); }
      if (dir === 'left' || dir === 'right') { const ex = dir === 'left' ? 12 : 6; g.box(ex, cy - 4, 3, 5, PAL.dark2, PAL.ink); }
      else { g.box(1, cy - 4, 3, 5, PAL.dark2, PAL.ink); g.box(16, cy - 4, 3, 5, PAL.dark2, PAL.ink); g.p(2, cy - 3, PAL.coral); g.p(17, cy - 3, PAL.coral); }
    } else if (acc === 'oculos' && dir !== 'up') {
      const ring = (ex) => { for (let y = -4; y <= 3; y++) for (let x = -4; x <= 3; x++) if (Math.max(Math.abs(x + 0.5), Math.abs(y + 0.5)) === 3.5) g.p(ex + x, eyeY + y, PAL.ink); };
      if (dir === 'down') { ring(7); ring(13); g.r(10, eyeY - 1, 1, 1, PAL.ink); }
      else ring(dir === 'left' ? 5 : 15);
    } else if (acc === 'faixa') {
      for (let x = 0; x < CW; x++) for (let y = capRow; y <= capRow + 1; y++) if (inside(x, y)) g.p(x, y, PAL.lime);
    } else if (acc === 'broto') {
      const ty = Math.round(cy - ry);
      g.r(10, ty - 3, 1, 3, PAL.greenD); g.r(7, ty - 5, 3, 2, PAL.green); g.p(8, ty - 6, PAL.greenL); g.r(11, ty - 5, 3, 2, PAL.green); g.p(12, ty - 6, PAL.greenL);
    }
  }));
}
