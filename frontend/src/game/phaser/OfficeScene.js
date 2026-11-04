// Mundo da sede no Phaser 3 a partir do office.tmj (SPEC-VIS-001, Fase 2).
// - Camadas na ordem do mapa. Antes de furniture_sorted: chão/parede/móveis atrás (depth negativo).
//   furniture_sorted: um sprite por tile, depth = y do pé do móvel. Depois: furniture_above, sempre na frente.
// - Personagens: sprite de characters.js (desenhado por código, 20x26) em escala 2x, depth = y do pé.
// - Câmera segue o jogador com lerp, presa aos limites do mapa, zoom inteiro em pixels do dispositivo (sem blur).
//   A sede não encolhe para caber na tela; se o mapa for menor que a tela, ele fica centralizado.
// - O estado (posição em tiles, poses, destaques) vem do viewModel do App, como no renderizador antigo.
// Nada de tile, móvel ou parede é desenhado aqui: só o destaque de interação e o destino do clique (interface).
import Phaser from 'phaser';
import { charSprite, CW, CH } from '../pixel/characters.js';
import { usedTilesets } from '../world/tmjWorld.js';
import { pickZoom, tagScale, tagPos } from './zoom.js';

export { pickZoom };

const ABOVE = 1e6, UI = 2e6;
const LIME = 0xD5F45B, NAVY = 0x17234B;


class OfficeScene extends Phaser.Scene {
  constructor(opts) { super({ key: 'office' }); this.opts = opts; }

  preload() {
    const { tmj, urls } = this.opts;
    const max = this.renderer.getMaxTextureSize ? this.renderer.getMaxTextureSize() : 4096;
    this.sets = usedTilesets(tmj).filter((t) => {
      if (!urls[t.name]) { console.warn(`[pivoo] tileset sem arquivo: ${t.name}`); return false; }
      if (t.imageheight > max || t.imagewidth > max) { console.warn(`[pivoo] ${t.name} (${t.imagewidth}x${t.imageheight}) passa do limite de textura (${max})`); return false; }
      return true;
    });
    this.sets.forEach((t) => this.load.spritesheet(t.name, urls[t.name], { frameWidth: t.tilewidth, frameHeight: t.tileheight }));
    this.cache.tilemap.add('office', { format: Phaser.Tilemaps.Formats.TILED_JSON, data: tmj });
  }

  create() {
    const { tmj } = this.opts;
    const T = tmj.tilewidth;
    this.T = T; this.S = T / 16;
    this.mapW = tmj.width * T; this.mapH = tmj.height * T;
    const map = this.make.tilemap({ key: 'office' });
    const tilesets = this.sets.map((t) => map.addTilesetImage(t.name, t.name)).filter(Boolean);
    const setOf = (gid) => this.sets.find((t) => gid >= t.firstgid && gid < t.firstgid + t.tilecount);

    let sortedSeen = false;
    tmj.layers.forEach((l, k) => {
      if (l.type === 'tilelayer') {
        const layer = map.createLayer(l.name, tilesets, 0, 0);
        if (layer) layer.setDepth(sortedSeen ? ABOVE + k : -100 + k);
      } else if (l.name === 'furniture_sorted') {
        sortedSeen = true;
        l.objects.forEach((o) => {
          const gid = o.gid & 0x1fffffff, ts = setOf(gid); if (!ts) return;
          const foot = ((o.properties || []).find((p) => p.name === 'foot') || {}).value || o.y;
          // tile-object do Tiled: (x, y) é o canto inferior esquerdo
          this.add.image(o.x, o.y, ts.name, gid - ts.firstgid).setOrigin(0, 1).setDepth(foot);
        });
      }
    });

    this.chars = new Map();
    this.texKeys = new WeakMap(); this.texN = 0;
    this.fx = this.add.graphics().setDepth(UI);
    this.t0 = this.time.now;
    this.reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const cam = this.cameras.main;
    cam.setRoundPixels(true);
    this.applyView();
    // a fonte do nome pode chegar depois da cena: redesenha os nomes quando carregar
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => this.refreshFonts());
    if (this.opts.onReady) this.opts.onReady(this);
  }

  // Zoom inteiro em pixels do dispositivo e limites do mapa (centralizado quando o mapa é menor que a tela)
  applyView() {
    const cam = this.cameras.main; const { width, height } = this.scale;
    const z = pickZoom(width, window.devicePixelRatio || 1);
    cam.setZoom(z);
    const vw = width / z, vh = height / z;
    const bw = Math.max(this.mapW, vw), bh = Math.max(this.mapH, vh);
    cam.setBounds(-(bw - this.mapW) / 2, -(bh - this.mapH) / 2, bw, bh);
  }

  texFor(canvas) {
    let key = this.texKeys.get(canvas);
    if (!key) {
      key = 'ch' + (this.texN++);
      const tex = this.textures.addCanvas(key, canvas);
      if (tex) tex.setFilter(Phaser.Textures.FilterMode.NEAREST);
      this.texKeys.set(canvas, key);
    }
    return key;
  }

  // Nome preso ao personagem: pill + texto num container, na mesma posição arredondada do sprite.
  // O container tem escala dpr/zoom (como o --inv do CSS): tamanho constante na tela, com a pill desenhada em "px CSS".
  makeTag(e) {
    const bg = this.add.graphics();
    const txt = this.add.text(0, 0, '', { fontFamily: 'Nunito Sans, system-ui, sans-serif', fontStyle: '800', fontSize: '11px', color: '#FFFFFF' })
      .setOrigin(0.5, 0.5).setResolution(window.devicePixelRatio || 1);
    txt.texture.setFilter(Phaser.Textures.FilterMode.LINEAR);
    const box = this.add.container(0, 0, [bg, txt]).setDepth(UI + 1).setVisible(false);
    e.tag = { box, bg, txt, label: null, lime: null };
  }

  setTag(e, label, lime) {
    const g = e.tag; if (!g || (g.label === label && g.lime === lime)) return;
    g.label = label; g.lime = lime;
    g.txt.setText(label).setColor(lime ? '#17234B' : '#FFFFFF');
    const w = Math.ceil((g.txt.width + 18) / 2) * 2, h = 21;
    g.bg.clear();
    g.bg.fillStyle(NAVY, 0.35).fillRoundedRect(-w / 2, -h + 2, w, h, 6);
    g.bg.fillStyle(NAVY, 1).fillRoundedRect(-w / 2, -h, w, h, 6);
    if (lime) g.bg.fillStyle(LIME, 1).fillRoundedRect(-w / 2 + 2, -h + 2, w - 4, h - 4, 4);
    g.txt.setPosition(0, -h / 2);
  }

  refreshFonts() { if (this.chars) this.chars.forEach((e) => { if (e.tag) { const { label, lime } = e.tag; e.tag.label = null; this.setTag(e, label || '', lime); } }); }

  ensureChar(id) {
    let e = this.chars.get(id);
    if (!e) {
      e = { x: 0, y: 0, from: [0, 0], to: [0, 0], t0: -1, dur: 0.6, dir: 'down', init: false, idleSince: 0, blinkAt: 1 + Math.random() * 3, gaze: [0, 0], gazeAt: 0, alive: true };
      e.img = this.add.image(0, 0, '__DEFAULT').setOrigin(0.5, 23 / CH).setScale(this.S).setVisible(false);
      this.makeTag(e);
      this.chars.set(id, e);
    }
    return e;
  }

  // chamado a cada render do React com o viewModel
  setState(v) {
    if (!this.chars) return;
    this.v = v;
    const T = this.T, S = this.S, now = (this.time.now - this.t0) / 1000;
    const seen = new Set();
    const place = (id, c, look, dur, tag, lime) => {
      const e = this.ensureChar(id); seen.add(id);
      this.setTag(e, tag, lime);
      const tx = (c.i + 0.5) * T, ty = (c.j + 1) * T - (c.seated ? 6 : 2) * S;
      if (!e.init) { e.x = tx; e.y = ty; e.from = [tx, ty]; e.to = [tx, ty]; e.init = true; }
      else if (e.to[0] !== tx || e.to[1] !== ty) { e.from = [e.x, e.y]; e.to = [tx, ty]; e.t0 = now; e.dur = c.teleport ? 0.01 : dur; }
      Object.assign(e, { look, anim: c.anim, seated: c.seated, face: c.face, need: c.need, work: c.work, foot: (c.j + 1) * T });
    };
    // dur dos agentes = AGENT_EVERY * TICK (App.jsx): 1 tile por passo lógico, sem o sprite chegar antes
    v.chars.forEach((c) => place(c.id, c, c.look, v.agentDur || 0.65, c.tagText, !!c.near));
    place('__player', v.pl, v.look, v.pl.dur || 0.13, 'Você', true);
    this.chars.forEach((e, id) => { if (!seen.has(id)) { e.img.destroy(); e.tag.box.destroy(); this.chars.delete(id); } });
    if (!this.following) { const p = this.chars.get('__player'); this.cameras.main.startFollow(p.img, true, 0.12, 0.12); this.following = true; }
  }

  update(time) {
    if (!this.v) return;
    const t = (time - this.t0) / 1000;
    this.chars.forEach((e) => {
      if (!e.init) return;
      const f = e.t0 < 0 ? 1 : Math.min((t - e.t0) / e.dur, 1);
      const px = e.x, py = e.y;
      e.x = e.from[0] + (e.to[0] - e.from[0]) * f; e.y = e.from[1] + (e.to[1] - e.from[1]) * f;
      const dx = e.x - px, dy = e.y - py, moving = Math.abs(dx) + Math.abs(dy) > 0.01;
      e.walking = moving || f < 1 || e.anim === 'walk';
      if (moving) { e.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up'); e.idleSince = t; }
      else if (!e.walking) { if (e.seated && e.face) e.dir = e.face; else if (!e.seated && t - e.idleSince > 1.6 && e.dir === 'up') e.dir = 'down'; }
      this.drawChar(e, t);
    });
    this.drawFx(t);
  }

  drawChar(e, t) {
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
    const canvas = charSprite(e.look || {}, e.dir, pose, frame, { gx: e.gaze[0], gy: e.gaze[1], blink: t < (e.blinkEnd || 0), wide: e.need });
    const key = this.texFor(canvas);
    if (e.img.texture.key !== key) e.img.setTexture(key);
    // posição em pixels inteiros do sprite (CW x CH em escala S)
    const rx = Math.round(e.x), ry = Math.round(e.y - lift * this.S);
    e.img.setPosition(rx, ry).setVisible(true);
    // nome: mesmo frame, mesma posição arredondada; deslocamento constante acima da cabeça (topo do sprite = ry - 23 * S)
    const inv = tagScale(this.cameras.main.zoom, window.devicePixelRatio || 1);
    e.tag.box.setScale(inv).setPosition(...tagPos(rx, ry, this.S, inv)).setVisible(true);
    // y-sorting pelo pé; sentado fica na frente da própria cadeira (o pé da cadeira é a base do tile)
    e.img.setDepth(e.seated && !e.walking ? e.foot + 1 : e.y);
  }

  drawFx(t) {
    const g = this.fx; g.clear();
    const v = this.v, T = this.T, S = this.S;
    if (v.dest) {
      const X = v.dest[0] * T, Y = v.dest[1] * T, on = Math.floor(t * 4) % 2;
      g.lineStyle(S, NAVY, on ? 1 : 0.5).strokeRect(X + S / 2, Y + S / 2, T - S, T - S);
    }
    const h = v.highlight; if (!h) return;
    const a = this.reduced ? 0.9 : 0.55 + Math.sin(t * 5) * 0.35;
    g.lineStyle(S, LIME, a);
    if (h.char) {
      const e = this.chars.get(h.char); if (!e) return;
      g.strokeEllipse(Math.round(e.x), Math.round(e.y) + S, 18 * S, 5 * S);
    } else {
      g.strokeRect(h.x * T - S, h.y * T - (h.oh || 0) - S, h.w * T + 2 * S, h.h * T + (h.oh || 0) + 2 * S);
    }
  }
}

// Sobe o jogo dentro de `parent`. O canvas tem tamanho em pixels do dispositivo e CSS do tamanho da tela.
// onFrame(cam) roda depois de cada render (para a camada HTML seguir a câmera).
export function createOffice({ parent, tmj, urls, width, height, onFrame }) {
  const dpr = window.devicePixelRatio || 1;
  let scene = null;
  const game = new Phaser.Game({
    type: Phaser.AUTO, parent, banner: false, pixelArt: true, roundPixels: true, antialias: false,
    backgroundColor: '#1E2440', audio: { noAudio: true },
    input: { keyboard: false, mouse: false, touch: false, gamepad: false },
    scale: { mode: Phaser.Scale.NONE, width: Math.round(width * dpr), height: Math.round(height * dpr), zoom: 1 / dpr },
    scene: new OfficeScene({ tmj, urls, onReady: (s) => { scene = s; if (pending) s.setState(pending); } }),
  });
  let pending = null;
  game.events.on('postrender', () => { if (scene && onFrame) onFrame(scene.cameras.main, dpr); });
  const fitCanvas = (w, h) => { const c = game.canvas; if (c) { c.style.width = w + 'px'; c.style.height = h + 'px'; c.style.imageRendering = 'pixelated'; } };
  game.events.once('ready', () => fitCanvas(width, height));
  return {
    update(v) { pending = v; if (scene) scene.setState(v); },
    resize(w, h) {
      game.scale.resize(Math.round(w * dpr), Math.round(h * dpr)); fitCanvas(w, h);
      if (scene) scene.applyView();
    },
    destroy() { game.destroy(true); },
  };
}

export { CW, CH };
