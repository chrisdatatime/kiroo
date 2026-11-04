// DEPRECATED (SPEC-VIS-001): o mundo vai migrar para tileset LimeZu + Tiled + Phaser 3. Não acrescente móveis
// nem paredes desenhados por código aqui; veja docs/SPEC-VIS-001.md. Mantido até a Fase 2 ser validada.
// Renderizador da sede em pixel art (Canvas 2D). Camadas: base estática (chão, tapetes, paredes, quadros),
// janelas animadas, sprites ordenados pela base (móveis, cadeiras, personagens) e efeitos (destaque, destino, telas).
// A câmera também move a camada HTML (placas, nomes e cliques), que fica em pixels de mundo.
import { GRID, BUILD, OUTSIDE, ROOMS, WALLS, DOORS, FURNITURE, CHAIRS, RUGS, WALL_DECOR, LOGO_WALL, MY_DESK, MY_SEAT } from '../map.js';
import { PAL, shade, sprite, Px, rng } from './draw.js';
import { deskSprite, chairSprites, furnitureSprite, paintWallDecor, paintWindowFrame, paintWindowBars, paintScreen, deskItem } from './furniture.js';
import { charSprite } from './characters.js';
import logoUrl from '../../assets/logo-game.png';
import photoUrl from '../../assets/paisagem.jpg';

const { T, W, H } = GRID;
const RUG = { lav: [PAL.lavL, PAL.lav], lime: ['#E9F7AE', PAL.limeD], sky: [PAL.skyL, PAL.skyD], cream: [PAL.cream, PAL.woodD], blue: ['#9DB4F2', '#5B79D6'] };
// Carpete de cada sala: cor e detalhe (o corredor comum fica com o piso de tábuas)
const CARPET = { lav: ['#CBC6EA', '#B6B0DC'], blue: ['#B6C8EC', '#9FB4DF'], gray: ['#CBD0DA', '#B6BDCA'], lime: ['#DCEFA8', '#C6DE8C'], slate: ['#B4BCCE', '#9EA7BC'], sky: ['#BEDEF2', '#A4CBE6'] };

function paintCarpet(g, r) {
  const [c, d] = CARPET[r.floor] || CARPET.gray;
  const X = r.x0 * T, Y = r.y0 * T, RW = (r.x1 - r.x0 + 1) * T, RH = (r.y1 - r.y0 + 1) * T;
  g.r(X, Y, RW, RH, c);
  for (let y = Y; y < Y + RH; y += 2) for (let x = X + ((y / 2) % 2 ? 1 : 0); x < X + RW; x += 2) g.p(x, y, d);
  g.r(X, Y, RW, 1, d); g.r(X, Y + RH - 1, RW, 1, d); g.r(X, Y, 1, RH, d); g.r(X + RW - 1, Y, 1, RH, d);
}

function paintRug(g, x, y, w, h, [fill, edge], seed) {
  const X = x * T + 2, Y = y * T + 2, RW = w * T - 4, RH = h * T - 4;
  g.r(X + 1, Y, RW - 2, RH, edge); g.r(X, Y + 1, RW, RH - 2, edge);
  g.r(X + 2, Y + 2, RW - 4, RH - 4, fill);
  g.r(X + 4, Y + 4, RW - 8, 1, edge); g.r(X + 4, Y + RH - 5, RW - 8, 1, edge);
  const r = rng(seed);
  for (let k = 0; k < (w * h) / 2; k++) g.p(X + 6 + Math.floor(r() * (RW - 12)), Y + 7 + Math.floor(r() * (RH - 14)), shade(fill, -0.06));
}

// Jardim, chão de tábuas, tapetes, paredes e decoração: desenhado uma vez
function paintTree(g, X, Y, big) {
  const r = rng('tree' + X + Y);
  g.r(X + 7, Y + (big ? 16 : 12), 3, big ? 10 : 7, '#8A6238');
  g.r(X + 7, Y + (big ? 16 : 12), 1, big ? 10 : 7, '#A2784A');
  const blobs = big ? [[8, 10, 8, 7], [4, 13, 5, 4], [12, 13, 5, 4], [8, 6, 6, 5]] : [[8, 9, 6, 5], [5, 12, 4, 3], [11, 12, 4, 3]];
  blobs.forEach(([cx, cy, rx, ry], k) => g.oval(X + cx, Y + cy, rx, ry, k === 3 ? '#6FC46B' : k % 2 ? '#3F9B5C' : '#54B56F', '#2F7D4A'));
  for (let k = 0; k < (big ? 7 : 4); k++) g.p(X + 4 + Math.floor(r() * 10), Y + 6 + Math.floor(r() * 9), '#8FD68F');
}

function buildBase(windows) {
  return sprite(W, H, (g) => {
    // jardim: grama com tufos, e calçada na frente do prédio
    const rg = rng('grass');
    for (let j = 0; j < GRID.R; j++) for (let i = 0; i < GRID.C; i++) {
      const y = j * T, x = i * T;
      g.r(x, y, T, T, (i + j) % 2 ? '#7FC36A' : '#88CB72');
      for (let k = 0; k < 3; k++) { const gx = x + Math.floor(rg() * 14), gy = y + Math.floor(rg() * 14); g.r(gx, gy, 2, 1, '#6FB45C'); g.p(gx + 1, gy - 1, '#9AD886'); }
    }
    for (let j = BUILD.y0 + 2; j < BUILD.y1; j++) for (let i = BUILD.x0 + 1; i < BUILD.x1; i++) {
      for (let row = 0; row < 4; row++) {
        const y = j * T + row * 4, alt = (i * 3 + j + row * 2) % 5 === 0;
        g.r(i * T, y, T, 4, alt ? '#F0D29F' : '#F4DAAC');
        g.r(i * T, y + 3, T, 1, '#E6C595');
        g.p(i * T + ((row * 5 + i * 7 + j * 3) % 16), y, '#E1BE8B');
      }
    }
    ROOMS.forEach((r) => paintCarpet(g, r));
    RUGS.forEach((r, k) => paintRug(g, r.x, r.y, r.w, r.h, RUG[r.color], 'rug' + k));
    // capachos nas portas
    DOORS.forEach(([x, y]) => { if (y === 13 || y === 27) g.r(x * T + 1, y * T + 5, T - 2, 6, '#C9B38C'); else g.r(x * T + 5, y * T + 1, 6, T - 2, '#C9B38C'); });

    const face = '#FBEFDC', faceD = '#EED9B8', base = '#D9BC92';
    // parede de cima (2 tiles): topo, face com janelas e quadros, rodapé
    const BX = BUILD.x0 * T, BW = (BUILD.x1 - BUILD.x0 + 1) * T, BY = BUILD.y0 * T;
    g.r(BX, BY, BW, 6, PAL.navy); g.r(BX, BY + 5, BW, 1, PAL.navy2); g.r(BX, BY + 6, BW, 24, face); g.r(BX, BY + 28, BW, 2, faceD); g.r(BX, BY + 30, BW, 2, base);
    WALLS.forEach(({ x, y, kind }) => {
      const X = x * T, Y = y * T;
      if (kind === 'h') { g.r(X, Y, T, 6, PAL.navy); g.r(X, Y + 5, T, 1, PAL.navy2); g.r(X, Y + 6, T, 8, face); g.r(X, Y + 12, T, 2, faceD); g.r(X, Y + 14, T, 2, base); }
      else if (kind === 'v') { g.r(X + 4, Y, 8, T, PAL.navy); g.r(X + 4, Y, 1, T, PAL.navy2); g.r(X + 12, Y, 1, T, 'rgba(23,35,75,0.25)'); }
      else if (kind === 'side') { g.r(X, Y, T, T, PAL.navy); g.r(x === BUILD.x0 ? X + T - 2 : X + 1, Y, 1, T, PAL.navy2); }
      else if (kind === 'outerBottom') { g.r(X, Y, T, 5, PAL.navy); g.r(X, Y + 5, T, 11, faceD); g.r(X, Y + 5, T, 1, PAL.navy2); }
    });
    // janelas e floreiras na face externa de baixo
    for (let x = BUILD.x0 + 2; x < BUILD.x1 - 3; x += 7) { const X = x * T, Y = BUILD.y1 * T; g.box(X, Y + 7, 3 * T, 7, PAL.skyL, PAL.ink); g.r(X + T, Y + 8, 1, 5, PAL.cream); g.r(X + 2 * T, Y + 8, 1, 5, PAL.cream);
      g.box(X + 3 * T + 8, Y + 9, 28, 6, PAL.woodD); for (let k = 0; k < 6; k++) g.oval(X + 3 * T + 11 + k * 4, Y + 8, 2, 2, k % 2 ? PAL.green : PAL.greenD, PAL.ink); }
    // árvores e arbustos do jardim
    OUTSIDE.forEach(([kind, x, y]) => paintTree(g, x * T, y * T - (kind === 'tree' ? 10 : 2), kind === 'tree'));
    // decoração das paredes
    WALL_DECOR.forEach((d) => {
      if (d.kind === 'window') {
        const X = d.x * T + 2, Y = BY + 8, ww = d.w * T - 4, wh = 19;
        const glass = paintWindowFrame(g, X, Y, ww, wh);
        windows.push({ ...glass, frame: { X, Y, ww, wh }, seed: d.x });
      } else if (d.y === undefined) paintWallDecor(g, d.kind, d.x * T, BY + 6, d.w * T, 24);
      else paintWallDecor(g, d.kind, d.x * T, d.y * T + 6, d.w * T, 8);
    });
    // placa do logo presa na parede, com dois spots iluminando de baixo
    const lx = LOGO_WALL.x * T + 4, ly = LOGO_WALL.y * T - 3, lw = LOGO_WALL.w * T - 8;
    g.box(lx, ly, lw, 19, PAL.cream, PAL.navy); g.r(lx + 1, ly + 1, lw - 2, 1, PAL.white); g.r(lx + 1, ly + 17, lw - 2, 1, PAL.cream2);
    [lx + 8, lx + lw - 10].forEach((sx) => {
      for (let k = 0; k < 6; k++) { g.c.fillStyle = `rgba(255,214,120,${0.05 + k * 0.03})`; g.c.fillRect(sx - 6 + k, ly + 4 + k * 2, 14 - 2 * k, 14 - k * 2); }
      g.r(sx - 1, ly + 18, 4, 2, PAL.ink); g.r(sx, ly + 17, 2, 1, '#FFE9A8');
    });
  });
}

export default class PixelOffice {
  constructor(canvas, overlay) {
    this.canvas = canvas; this.overlay = overlay;
    this.ctx = canvas.getContext('2d');
    this.windows = [];
    this.base = buildBase(this.windows);
    this.view = { x: W / 2, y: H / 2, zoom: 1 }; this.target = { ...this.view }; this.size = { w: 1, h: 1 };
    this.chars = new Map(); this.state = null; this.mine = null; this.mineKey = '';
    this.t0 = performance.now(); this.last = this.t0;
    this.reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.buildStatic();
    this.logo = new Image(); this.logo.src = logoUrl;
    this.photo = new Image(); this.photo.onload = () => this.preparePhotos(); this.photo.src = photoUrl;
    this.loop = this.loop.bind(this);
    this.raf = requestAnimationFrame(this.loop);
  }

  // Móveis, mesas e cadeiras: posição e base (para ordenar com os personagens)
  buildStatic() {
    const items = [];
    const put = (img, x, bottom, base, extra = {}) => items.push({ img, x, y: bottom - img.height, base, ...extra });
    FURNITURE.forEach((f) => { const img = furnitureSprite(f); put(img, f.x * T, (f.y + f.h) * T, (f.y + f.h) * T - 1); });
    this.desks = {};
    ROOMS.filter((r) => r.agent).forEach((r) => {
      const d = r.desk; const img = deskSprite(d.w, d.h, d.screens, { mug: shade(PAL.coral, 0) });
      const it = { img, x: d.x * T, y: (d.y + d.h) * T - img.height, base: (d.y + d.h) * T - 1, room: r.id };
      items.push(it); this.desks[r.agent] = it;
    });
    CHAIRS.forEach((c) => {
      if (c.kind === 'sofa' || c.kind === 'mine') return;
      const s = chairSprites(c.face, c.kind, c.color);
      const bottom = (c.y + 1) * T;
      put(s.seat, c.x * T, bottom, bottom - 8);
      if (s.back) put(s.back, c.x * T, bottom, bottom + 1);
    });
    this.items = items;
  }

  preparePhotos() {
    const img = this.photo;
    this.windows.forEach((w) => {
      // a foto é reduzida ao tamanho do vidro: vira pixel art ao ser ampliada pela câmera
      const c = document.createElement('canvas'); c.width = w.gw; c.height = w.gh;
      const x = c.getContext('2d');
      const ratio = w.gw / w.gh, sh = img.height * 0.32, sw = Math.min(img.width, sh * ratio);
      const sx = ((w.seed * 37) % Math.max(1, img.width - sw)), sy = img.height * 0.2;
      x.drawImage(img, sx, sy, sw, sh, 0, 0, w.gw, w.gh);
      w.photo = c;
      w.bars = sprite(w.frame.ww, w.frame.wh, (g) => paintWindowBars(g, 0, 0, w.frame.ww, w.frame.wh));
    });
  }

  resize(w, h) {
    this.size = { w, h };
    this.dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(w * this.dpr); this.canvas.height = Math.round(h * this.dpr);
  }

  setTarget(x, y, zoom) { this.target = { x, y, zoom }; }

  ensureChar(id) {
    let e = this.chars.get(id);
    if (!e) { e = { x: 0, y: 0, from: [0, 0], to: [0, 0], t0: -1, dur: 0.6, dir: 'down', init: false, idleSince: 0, blinkAt: 1 + Math.random() * 3, gaze: [0, 0], gazeAt: 0 }; this.chars.set(id, e); }
    return e;
  }

  // chamado a cada render do React com o viewModel
  update(v) {
    this.state = v;
    const now = (performance.now() - this.t0) / 1000;
    const place = (id, c, look, dur) => {
      const e = this.ensureChar(id);
      const tx = (c.i + 0.5) * T, ty = (c.j + 1) * T - (c.seated ? 6 : 2);
      if (!e.init) { e.x = tx; e.y = ty; e.from = [tx, ty]; e.to = [tx, ty]; e.init = true; }
      else if (e.to[0] !== tx || e.to[1] !== ty) { e.from = [e.x, e.y]; e.to = [tx, ty]; e.t0 = now; e.dur = c.teleport ? 0.01 : dur; }
      Object.assign(e, { look, anim: c.anim, seated: c.seated, face: c.face, need: c.need, work: c.work });
    };
    v.chars.forEach((c) => place(c.id, c, c.look, v.agentDur || 0.65));
    place('__player', v.pl, v.look, v.pl.dur || 0.13);
    const key = JSON.stringify(v.setup);
    if (key !== this.mineKey) { this.mineKey = key; this.mine = this.buildMine(v.setup || {}); }
  }

  // Meu escritório: mesa, cadeira e itens conforme a personalização
  buildMine(su) {
    const items = [];
    const desk = ROOMS.find((r) => r.id === 'meu').desk;
    const top = { madeira: PAL.woodL, branca: '#F4F5F8', gamer: '#2B2F45' }[su.desk] || PAL.woodL;
    const edge = { madeira: PAL.woodD, branca: '#CDD2DC', gamer: '#1C1D2B' }[su.desk] || PAL.woodD;
    const screens = su.pc === 'duplo' ? ['overview', 'story'] : su.pc === 'retro' ? ['retro'] : ['notebook'];
    const img = deskSprite(desk.w, desk.h, screens, { top, edge, leg: shade(edge, -0.3), led: su.desk === 'gamer' ? PAL.lime : null, mug: su.caneca ? PAL.coral : null, bare: true });
    const dx = desk.x * T, base = (desk.y + desk.h) * T - 1;
    items.push({ img, x: dx, y: base + 1 - img.height, base, room: 'meu' });
    const topY = base + 1 - img.height + 18;
    if (su.luminaria) { const s = deskItem.lamp(); items.push({ img: s, x: dx + 4, y: topY - 12, base: base + 0.2 }); }
    if (su.planta) { const s = deskItem.plant(); items.push({ img: s, x: dx + desk.w * T - 13, y: topY - 9, base: base + 0.2 }); }
    if (su.gato) items.push({ cat: true, x: dx + 14, y: topY + 6, base: base + 0.3 });
    const chairKind = su.chair === 'bola' ? 'ball' : 'mine';
    const chairColor = su.chair === 'gamer' ? '#2A2C38' : su.chair === 'bola' ? PAL.lime : '#3A4A8C';
    const s = chairSprites('up', chairKind, chairColor);
    const bottom = (MY_SEAT[1] + 1) * T;
    items.push({ img: s.seat, x: MY_SEAT[0] * T, y: bottom - s.seat.height, base: bottom - 8 });
    if (s.back) items.push({ img: s.back, x: MY_SEAT[0] * T, y: bottom - s.back.height, base: bottom + 1, gamer: su.chair === 'gamer' });
    this.mineRug = su.tapete ? { x: 3, y: 18, w: 6, h: 4 } : null;
    return items;
  }

  // A sede inteira fica na tela: a escala costuma ser quebrada (ex.: 1,2x). Para a pixel art não ficar irregular, o mundo é
  // desenhado numa escala inteira acima (buffer) e reduzido com suavização; em escala inteira, desenha direto.
  loop() {
    this.raf = requestAnimationFrame(this.loop);
    const nowMs = performance.now(); this.last = nowMs;
    const t = (nowMs - this.t0) / 1000;
    this.view = { ...this.target };
    const { x, y, zoom } = this.view, { w, h } = this.size, dpr = this.dpr || 1;
    const s = zoom * dpr;
    const tx = Math.round(w / 2 * dpr - x * s), ty = Math.round(h / 2 * dpr - y * s);
    if (this.overlay) {
      this.overlay.style.transform = `translate(${tx / dpr}px, ${ty / dpr}px) scale(${zoom})`;
      this.overlay.style.setProperty('--inv', String(1 / zoom));
    }
    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (Math.abs(s - Math.round(s)) < 0.02 && Math.round(s) >= 1) {
      ctx.setTransform(Math.round(s), 0, 0, Math.round(s), tx, ty);
      ctx.imageSmoothingEnabled = false;
      this.drawWorld(ctx, t);
      return;
    }
    const k = Math.min(4, Math.max(1, Math.ceil(s)));
    if (!this.buf || this.bufK !== k) { this.buf = document.createElement('canvas'); this.buf.width = W * k; this.buf.height = H * k; this.bufK = k; }
    const b = this.buf.getContext('2d');
    b.setTransform(1, 0, 0, 1, 0, 0); b.clearRect(0, 0, this.buf.width, this.buf.height);
    b.setTransform(k, 0, 0, k, 0, 0); b.imageSmoothingEnabled = false;
    this.drawWorld(b, t);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(this.buf, tx, ty, Math.round(W * s), Math.round(H * s));
  }

  drawWorld(ctx, t) {
    const g = new Px(ctx);
    ctx.drawImage(this.base, 0, 0);
    if (this.mineRug) paintRug(g, this.mineRug.x, this.mineRug.y, this.mineRug.w, this.mineRug.h, RUG.blue, 'mine');
    this.drawWindows(ctx, t);
    if (this.logo.complete && this.logo.naturalWidth) {
      ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
      const lw = LOGO_WALL.w * T - 22, lh = lw * (this.logo.naturalHeight / this.logo.naturalWidth);
      ctx.drawImage(this.logo, LOGO_WALL.x * T + 11, LOGO_WALL.y * T - 3 + (19 - lh) / 2, lw, lh);
      ctx.imageSmoothingEnabled = false;
    }
    this.drawDest(g, t);

    // sprites ordenados pela base
    const list = this.items.concat(this.mine || []);
    const chars = [];
    this.chars.forEach((e, id) => {
      if (!e.init) return;
      const f = e.t0 < 0 ? 1 : Math.min((t - e.t0) / e.dur, 1);
      const px = e.x, py = e.y;
      e.x = e.from[0] + (e.to[0] - e.from[0]) * f; e.y = e.from[1] + (e.to[1] - e.from[1]) * f;
      const dx = e.x - px, dy = e.y - py, moving = Math.abs(dx) + Math.abs(dy) > 0.01;
      // entre um passo e outro o alvo para por instantes: a animação de andar segue o estado do jogo, não só o deslocamento
      e.walking = moving || f < 1 || e.anim === 'walk';
      if (moving) { e.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up'); e.idleSince = t; }
      else if (!e.walking) { if (e.seated && e.face) e.dir = e.face; else if (!e.seated && t - e.idleSince > 1.6 && e.dir === 'up') e.dir = 'down'; }
      chars.push({ char: e, id, base: e.y });
    });
    list.concat(chars).sort((a, b) => a.base - b.base).forEach((it) => {
      if (it.char) this.drawChar(ctx, it.char, t);
      else if (it.cat) ctx.drawImage(deskItem.cat(Math.floor(t * 1.2) % 2), it.x, it.y);
      else ctx.drawImage(it.img, Math.round(it.x), Math.round(it.y));
    });
    this.drawDeskActivity(g, t);
    this.drawHighlight(g, t);
  }

  drawWindows(ctx, t) {
    this.windows.forEach((w) => {
      if (!w.photo) return;
      ctx.drawImage(w.photo, w.gx, w.gy);
      if (!this.reduced) {
        ctx.save(); ctx.beginPath(); ctx.rect(w.gx, w.gy, w.gw, w.gh); ctx.clip();
        ctx.fillStyle = 'rgba(255,255,255,0.85)';
        [0, 1].forEach((k) => {
          const span = w.gw + 30, cx = w.gx - 15 + ((t * (2.2 + k) + w.seed * 13 + k * 40) % span), cy = w.gy + 2 + k * 3;
          ctx.fillRect(Math.round(cx), cy, 9, 2); ctx.fillRect(Math.round(cx) + 2, cy - 1, 5, 1); ctx.fillRect(Math.round(cx) + 1, cy + 2, 6, 1);
        });
        ctx.restore();
      }
      if (w.bars) ctx.drawImage(w.bars, w.frame.X, w.frame.Y);
    });
  }

  drawChar(ctx, e, t) {
    const anim = e.anim || 'idle';
    let pose = 'stand', frame = 0, lift = 0;
    if (e.walking) { pose = 'walk'; frame = Math.floor(t * 8) % 4; }
    else if (e.seated) { pose = anim === 'type' ? 'type' : 'sit'; frame = Math.floor(t * 6) % 2; }
    else if (anim === 'wave') { pose = 'wave'; frame = Math.floor(t * 4) % 2; }
    else if (anim === 'happy') { pose = 'happy'; lift = Math.round(Math.abs(Math.sin(t * 6)) * 4); }
    else frame = Math.floor(t * 1.6) % 2;
    if (this.reduced) { frame = 0; lift = 0; }
    if (t > e.blinkAt) { e.blinkEnd = t + 0.13; e.blinkAt = t + 2 + Math.random() * 3.5; }
    if (t > e.gazeAt) { e.gaze = pose === 'type' ? [0, 1] : [Math.floor(Math.random() * 3) - 1, Math.random() < 0.3 ? 1 : 0]; e.gazeAt = t + 0.8 + Math.random() * 2.2; }
    const img = charSprite(e.look || {}, e.dir, pose, frame, { gx: e.gaze[0], gy: e.gaze[1], blink: t < (e.blinkEnd || 0), wide: e.need });
    ctx.drawImage(img, Math.round(e.x - 10), Math.round(e.y - 23 - lift));
  }

  drawDeskActivity(g, t) {
    const v = this.state; if (!v) return;
    (v.desks || []).forEach((d) => {
      const it = this.desks[d.id]; if (!it) return;
      if (d.work && !this.reduced) it.img.meta.screens.forEach((s) => paintScreen(g, it.x + s.x, it.y + s.y, s.w, s.h, s.type, t * 3));
      const blink = Math.floor(t * 2.5) % 2 === 0;
      if (d.need && blink) g.r(it.x + it.img.width - 6, it.y + it.img.height - 6, 3, 2, PAL.lime);
      if (d.work) g.r(it.x + it.img.width - 6, it.y + it.img.height - 6, 3, 2, PAL.sky);
    });
  }

  drawDest(g, t) {
    const d = this.state && this.state.dest; if (!d) return;
    const X = d[0] * T, Y = d[1] * T, on = Math.floor(t * 4) % 2;
    for (let k = 0; k < T; k += 4) { g.r(X + k, Y, 2, 1, PAL.navy); g.r(X + k + (on ? 2 : 0), Y + T - 1, 2, 1, PAL.navy); g.r(X, Y + k, 1, 2, PAL.navy); g.r(X + T - 1, Y + k, 1, 2, PAL.navy); }
  }

  drawHighlight(g, t) {
    const h = this.state && this.state.highlight; if (!h) return;
    const a = 0.55 + Math.sin(t * 5) * 0.35;
    g.c.globalAlpha = a;
    if (h.char) {
      const e = this.chars.get(h.char); if (!e) { g.c.globalAlpha = 1; return; }
      const X = Math.round(e.x), Y = Math.round(e.y);
      g.r(X - 8, Y + 1, 16, 1, PAL.lime); g.r(X - 10, Y, 2, 1, PAL.lime); g.r(X + 8, Y, 2, 1, PAL.lime); g.r(X - 8, Y - 1, 1, 1, PAL.lime); g.r(X + 7, Y - 1, 1, 1, PAL.lime);
    } else {
      const X = h.x * T - 2, Y = h.y * T - (h.oh || 0) - 2, Wd = h.w * T + 4, Hd = h.h * T + (h.oh || 0) + 4;
      g.r(X, Y, Wd, 1, PAL.lime); g.r(X, Y + Hd - 1, Wd, 1, PAL.lime); g.r(X, Y, 1, Hd, PAL.lime); g.r(X + Wd - 1, Y, 1, Hd, PAL.lime);
      g.r(X - 1, Y - 1, 3, 3, PAL.lime); g.r(X + Wd - 2, Y - 1, 3, 3, PAL.lime); g.r(X - 1, Y + Hd - 2, 3, 3, PAL.lime); g.r(X + Wd - 2, Y + Hd - 2, 3, 3, PAL.lime);
    }
    g.c.globalAlpha = 1;
  }

  dispose() { cancelAnimationFrame(this.raf); }
}
