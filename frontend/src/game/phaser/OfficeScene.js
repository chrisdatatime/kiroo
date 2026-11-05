// Mundo da sede no Phaser 3 a partir do office.tmj (SPEC-VIS-001, Fase 2).
// - Camadas na ordem do mapa. Antes de furniture_sorted: chão/parede/móveis atrás (depth negativo).
//   furniture_sorted: um sprite por tile, depth = y do pé do móvel. Depois: furniture_above, sempre na frente.
// - Personagens: agentes Kiroo em folhas 6x6 de quadros 32x32 e jogador LimeZu em quadros 32x64;
//   sem a folha (arte fora do git), cai no sprite de characters.js. Depth = y do pé.
// - Câmera segue o jogador com lerp, presa aos limites do mapa, zoom inteiro em pixels do dispositivo (sem blur).
//   A sede não encolhe para caber na tela; se o mapa for menor que a tela, ele fica centralizado.
// - O estado (posição em tiles, poses, destaques) vem do viewModel do App, como no renderizador antigo.
// Nada de tile, móvel ou parede é desenhado aqui: só o destaque de interação e o destino do clique (interface).
import Phaser from 'phaser';
import { charSprite, CW, CH } from '../pixel/characters.js';
import { usedTilesets } from '../world/tmjWorld.js';
import { pickZoom, pickLevel, deviceZoom, clampLevel, anchorScroll, snapScroll, tagScale, tagPos, tagPosTop } from './zoom.js';
import { PW } from './theme.js';
import { CHARACTER_SHEETS, FW, FH, HEAD, KIROO_HEAD, KIROO_FOOT, KIROO_SCALE, STAND_DY, SIT_DY, characterSheetSpec, kirooFrame, idleFrame, walkFrame, sitFrame, sitSide, phoneFrame, walkPhase, SEAT, seatMode } from './sprites.js';

export { pickZoom };

const ABOVE = 1e6, UI = 2e6;
const LIME = 0xD5F45B;

class OfficeScene extends Phaser.Scene {
  constructor(opts) { super({ key: 'office' }); this.opts = opts; }

  preload() {
    const { tmj, urls } = this.opts;
    const max = this.renderer.getMaxTextureSize ? this.renderer.getMaxTextureSize() : 4096;
    this.sets = usedTilesets(tmj).filter((t) => {
      if (!urls[t.name]) { console.warn(`[kiroo] tileset sem arquivo: ${t.name}`); return false; }
      if (t.imageheight > max || t.imagewidth > max) { console.warn(`[kiroo] ${t.name} (${t.imagewidth}x${t.imageheight}) passa do limite de textura (${max})`); return false; }
      return true;
    });
    this.sets.forEach((t) => this.load.spritesheet(t.name, urls[t.name], { frameWidth: t.tilewidth, frameHeight: t.tileheight }));
    // folhas dos personagens (assets/characters, fora do git): se faltar, o personagem usa o feijão
    this.sheets = {}; this.sheetKinds = {};
    Object.entries(CHARACTER_SHEETS).forEach(([id, file]) => {
      const url = (this.opts.chars || {})[file]; if (!url) return;
      const spec = characterSheetSpec(id);
      this.load.spritesheet('hc_' + file, url, { frameWidth: spec.frameWidth, frameHeight: spec.frameHeight });
      this.sheets[id] = 'hc_' + file;
      this.sheetKinds[id] = spec.kind;
    });
    this.cache.tilemap.add('office', { format: Phaser.Tilemaps.Formats.TILED_JSON, data: tmj });
  }

  create() {
    Object.keys(this.sheets).forEach((id) => { if (this.textures.exists(this.sheets[id])) this.textures.get(this.sheets[id]).setFilter(Phaser.Textures.FilterMode.NEAREST); });
    const { tmj } = this.opts;
    const T = tmj.tilewidth;
    this.T = T; this.S = T / 16;
    this.mapW = tmj.width * T; this.mapH = tmj.height * T;
    const map = this.make.tilemap({ key: 'office' });
    const tilesets = this.sets.map((t) => map.addTilesetImage(t.name, t.name)).filter(Boolean);
    const setOf = (gid) => this.sets.find((t) => gid >= t.firstgid && gid < t.firstgid + t.tilecount);

    let sortedSeen = false;
    this.furnTile = new Map(); // tile do móvel por "i,j+1" (canto inferior esquerdo): o assento redesenha o próprio tile sobre o personagem
    this.seatInfo = new Map(); // "i,j" → { kind, face } dos assentos do mapa (agent/visitor = cadeira de mesa)
    ((tmj.layers.find((l) => l.name === 'objects') || { objects: [] }).objects).filter((o) => o.type === 'seat').forEach((o) => {
      const p = {}; (o.properties || []).forEach((q) => { p[q.name] = q.value; });
      this.seatInfo.set(Math.floor(o.x / T) + ',' + Math.floor(o.y / T), { kind: p.kind || 'free', face: p.face || 'down' });
    });
    this.T = T;
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
          this.furnTile.set(Math.round(o.x / T) + ',' + Math.round(o.y / T), { ts: ts.name, f: gid - ts.firstgid });
        });
      }
    });

    this.chars = new Map();
    this.texKeys = new WeakMap(); this.texN = 0;
    this.fx = this.add.graphics().setDepth(UI);
    // hover do mapa: cantos no chão (abaixo dos móveis) e destaque + rótulo em cadeiras/objetos (acima)
    this.hoverFloor = this.add.graphics().setDepth(1);
    this.hoverHi = this.add.graphics().setDepth(UI - 1);
    this.hoverE = {}; this.makeTag(this.hoverE);
    this.pointer = null; this.hoverKey = null; this.hoverInfo = null;
    this.t0 = this.time.now;
    this.reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const cam = this.cameras.main;
    cam.setRoundPixels(true);
    cam.setBackgroundColor(PW.bg);
    this.level = this.opts.level ?? null; // nível escolhido (null = automático, pickLevel)
    this.free = false;                    // câmera solta (arrastada ou zoom no cursor) até "centralizar"
    this.applyView();
    // a fonte do nome pode chegar depois da cena: redesenha os nomes quando carregar
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => this.refreshFonts());
    if (this.opts.onReady) this.opts.onReady(this);
  }

  // Zoom inteiro em pixels do dispositivo e limites do mapa (centralizado quando o mapa é menor que a tela)
  targetZoom() {
    const dpr = window.devicePixelRatio || 1;
    return this.level == null ? pickZoom(this.scale.width, dpr) : deviceZoom(this.level, dpr);
  }
  boundsFor(z) {
    const { width, height } = this.scale;
    const vw = width / z, vh = height / z;
    const bw = Math.max(this.mapW, vw), bh = Math.max(this.mapH, vh);
    this.cameras.main.setBounds(-(bw - this.mapW) / 2, -(bh - this.mapH) / 2, bw, bh);
  }
  applyView() {
    if (this.zoomTween) return; // o tween termina no zoom certo
    const z = this.targetZoom();
    this.cameras.main.setZoom(z);
    this.boundsFor(z);
    this.emitView();
  }
  // Estado do zoom para o React, só quando muda (nada por frame)
  emitView() {
    const dpr = window.devicePixelRatio || 1;
    const level = this.level ?? pickLevel(this.scale.width / dpr);
    const key = level + '|' + (this.level == null) + '|' + this.free;
    if (key === this.viewKey) return;
    this.viewKey = key;
    if (this.opts.onView) this.opts.onView({ level, auto: this.level == null, free: this.free });
  }

  // Muda o nível (null = automático). anchor = ponto do canvas em px do dispositivo que fica parado (cursor);
  // sem âncora, o zoom é no centro e a câmera continua seguindo. Anima ~150 ms com zoom fracionário e trava no inteiro.
  zoomTo(level, anchor) {
    const cam = this.cameras.main;
    this.level = level == null ? null : clampLevel(level);
    const z0 = cam.zoom, z1 = this.targetZoom();
    if (anchor) this.release();
    if (this.zoomTween) { this.zoomTween.stop(); this.zoomTween = null; }
    const { width, height } = this.scale;
    const step = (z) => {
      if (anchor) {
        const zPrev = cam.zoom;
        cam.scrollX = anchorScroll(cam.scrollX, anchor.x, width, zPrev, z);
        cam.scrollY = anchorScroll(cam.scrollY, anchor.y, height, zPrev, z);
      }
      cam.setZoom(z); this.boundsFor(z);
    };
    const done = () => {
      this.zoomTween = null; step(z1);
      if (!cam._follow) { cam.scrollX = snapScroll(cam.scrollX, z1); cam.scrollY = snapScroll(cam.scrollY, z1); }
      this.emitView();
    };
    if (z0 === z1 || this.reduced) { done(); return; }
    this.zoomTween = this.tweens.addCounter({ from: 0, to: 1, duration: 150, ease: 'Sine.easeOut',
      onUpdate: (tw) => step(z0 + (z1 - z0) * tw.getValue()), onComplete: done });
    this.emitView();
  }
  // Solta a câmera do jogador (arrastar / zoom no cursor)
  release() {
    if (this.free) return;
    this.cameras.main.stopFollow(); this.free = true; this.emitView();
  }
  // Arrasta o mapa: dx, dy em px CSS da tela
  panBy(dx, dy) {
    const cam = this.cameras.main, dpr = window.devicePixelRatio || 1;
    this.release();
    cam.scrollX -= dx * dpr / cam.zoom; cam.scrollY -= dy * dpr / cam.zoom;
  }
  // Volta a seguir o jogador
  centerOnPlayer() {
    const p = this.chars && this.chars.get('__player'); if (!p) return;
    const cam = this.cameras.main;
    this.free = false;
    if (this.reduced) cam.centerOn(p.img.x, p.img.y);
    cam.startFollow(p.img, true, 0.12, 0.12);
    this.emitView();
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
    const txt = this.add.text(0, 0, '', { fontFamily: 'Nunito Sans, system-ui, sans-serif', fontStyle: '800', fontSize: '11px', color: PW.text })
      .setOrigin(0.5, 0.5).setResolution(window.devicePixelRatio || 1);
    txt.texture.setFilter(Phaser.Textures.FilterMode.LINEAR);
    const box = this.add.container(0, 0, [bg, txt]).setDepth(UI + 1).setVisible(false);
    e.tag = { box, bg, txt, label: null, lime: null };
  }

  setTag(e, label, lime) {
    const g = e.tag; if (!g || (g.label === label && g.lime === lime)) return;
    g.label = label; g.lime = lime;
    // pill clara: branca, texto escuro, borda sutil; destaque (você / perto) em índigo com texto branco
    g.txt.setText(label).setColor(lime ? PW.primaryText : PW.text);
    const w = Math.ceil((g.txt.width + 18) / 2) * 2, h = 20, r = h / 2;
    g.bg.clear();
    g.bg.fillStyle(PW.shadow, 0.12).fillRoundedRect(-w / 2, -h + 1.5, w, h, r);
    if (lime) g.bg.fillStyle(PW.primary, 1).fillRoundedRect(-w / 2, -h, w, h, r);
    else {
      g.bg.fillStyle(PW.border, 1).fillRoundedRect(-w / 2, -h, w, h, r);
      g.bg.fillStyle(PW.surface, 0.96).fillRoundedRect(-w / 2 + 1, -h + 1, w - 2, h - 2, r - 1);
    }
    g.txt.setPosition(0, -h / 2);
  }

  refreshFonts() { if (this.chars) this.chars.forEach((e) => { if (e.tag) { const { label, lime } = e.tag; e.tag.label = null; this.setTag(e, label || '', lime); } }); }

  ensureChar(id) {
    let e = this.chars.get(id);
    if (!e) {
      e = { id, x: 0, y: 0, from: [0, 0], to: [0, 0], t0: -1, dur: 0.6, dir: 'down', init: false, idleSince: 0, blinkAt: 1 + Math.random() * 3, gaze: [0, 0], gazeAt: 0, alive: true };
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
      const compact = this.sheetKinds[id] === 'kiroo';
      const tx = (c.i + 0.5) * T, ty = (c.j + 1) * T - (c.seated && !compact ? 6 : 2) * S;
      // A direção vem do passo lógico, não de resíduos de interpolação ou da altura ao sentar.
      const di = c.i - (e.tileI ?? c.i), dj = c.j - (e.tileJ ?? c.j);
      if (di || dj) e.moveDir = Math.abs(di) > Math.abs(dj) ? (di > 0 ? 'right' : 'left') : (dj > 0 ? 'down' : 'up');
      e.tileI = c.i; e.tileJ = c.j;
      if (!e.init) { e.x = tx; e.y = ty; e.from = [tx, ty]; e.to = [tx, ty]; e.init = true; }
      else if (e.to[0] !== tx || e.to[1] !== ty) { e.from = [e.x, e.y]; e.to = [tx, ty]; e.t0 = now; e.dur = c.teleport ? 0.01 : dur; }
      Object.assign(e, { sheet: this.sheets[id] && this.textures.exists(this.sheets[id]) ? this.sheets[id] : null, sheetKind: this.sheetKinds[id], dyOld: c.seated ? 6 * S : 2 * S, look, anim: c.anim, seated: c.seated, face: c.face, need: c.need, work: c.work, foot: (c.j + 1) * T });
    };
    // dur dos agentes = AGENT_EVERY * TICK (App.jsx): 1 tile por passo lógico, sem o sprite chegar antes
    v.chars.forEach((c) => place(c.id, c, c.look, v.agentDur || 0.65, c.tagText, !!c.near));
    place('__player', v.pl, v.look, v.pl.dur || 0.13, 'Você', true);
    this.chars.forEach((e, id) => { if (!seen.has(id)) { e.img.destroy(); e.tag.box.destroy(); if (e.cover) e.cover.destroy(); this.chars.delete(id); } });
    if (!this.following) { const p = this.chars.get('__player'); this.cameras.main.startFollow(p.img, true, 0.12, 0.12); this.following = true; }
    // câmera solta e o jogador começou a andar fora da vista: volta a seguir
    if (this.free && v.pl.anim === 'walk') {
      const p = this.chars.get('__player'), wv = this.cameras.main.worldView;
      if (p && !wv.contains(p.img.x, p.img.y)) this.centerOnPlayer();
    }
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
      e.dist = (e.dist || 0) + Math.abs(dx) + Math.abs(dy);
      e.walking = moving || f < 1;
      if (moving) { e.dir = e.moveDir || e.dir; e.idleSince = t; }
      else if (!e.walking) { if (e.seated && e.face) e.dir = e.face; else if (!e.seated && t - e.idleSince > 1.6 && e.dir === 'up') e.dir = 'down'; }
      this.drawChar(e, t);
    });
    this.drawFx(t);
    this.updateHover();
  }

  // Ponteiro em px do dispositivo relativos ao canvas (null = fora do mundo). O tile é recalculado por frame só com
  // contas da câmera; o App (hoverAt) é consultado e o desenho refeito só quando o tile, o resultado ou o zoom mudam.
  setPointer(p) { this.pointer = p; }
  updateHover() {
    if (!this.hoverFloor) return; // cena sem create() (testes)
    const cam = this.cameras.main, T = this.T;
    let info = null;
    if (this.pointer && this.v && this.v.hoverAt) {
      const w = cam.getWorldPoint(this.pointer.x, this.pointer.y);
      const i = Math.floor(w.x / T), j = Math.floor(w.y / T);
      // o mesmo tile só é reconsultado quando o viewModel muda (cadeira ocupada, agente andou...)
      if (i + ',' + j === this.hoverTile && this.hoverV === this.v) info = this.hoverInfo;
      else { info = this.v.hoverAt(i, j); this.hoverTile = i + ',' + j; this.hoverV = this.v; }
    } else { this.hoverTile = null; }
    this.hoverInfo = info;
    const key = info ? `${info.kind}|${info.x}|${info.y}|${info.w}|${info.h}|${info.label || ''}|${cam.zoom}` : '';
    if (key !== this.hoverKey) { this.hoverKey = key; this.drawHover(info); }
    const tag = this.hoverE.tag;
    if (info && info.kind === 'target') {
      const inv = tagScale(cam.zoom, window.devicePixelRatio || 1);
      tag.box.setScale(inv).setPosition(Math.round((info.x + info.w / 2) * T), Math.round(info.y * T - (info.oh || 0) - 6 * inv)).setVisible(true);
    } else tag.box.setVisible(false);
  }
  drawHover(info) {
    const g = this.hoverFloor.clear(), hi = this.hoverHi.clear(), T = this.T;
    if (this.opts.onHover) this.opts.onHover(info ? info.kind : null);
    if (!info) return;
    const X = info.x * T, Y = info.y * T - (info.oh || 0), W = info.w * T, H = info.h * T + (info.oh || 0);
    if (info.kind === 'floor') {
      // quatro cantos em L, discretos, na escala do mapa
      const L = Math.round(T / 4), th = 2, m = 2;
      g.fillStyle(PW.shadow, 0.32);
      [[X + m, Y + m, 1, 1], [X + W - m, Y + m, -1, 1], [X + m, Y + H - m, 1, -1], [X + W - m, Y + H - m, -1, -1]].forEach(([x, y, sx, sy]) => {
        g.fillRect(sx > 0 ? x : x - L, sy > 0 ? y : y - th, L, th);
        g.fillRect(sx > 0 ? x : x - th, sy > 0 ? y : y - L, th, L);
      });
      return;
    }
    // alvo: preenchimento branco translúcido + contorno de 2 px na tela
    const lw = Math.max(1, 2 * (window.devicePixelRatio || 1) / this.cameras.main.zoom);
    hi.fillStyle(PW.surface, 0.28).fillRect(X, Y, W, H);
    hi.lineStyle(lw, PW.surface, 0.95).strokeRect(X + lw / 2, Y + lw / 2, W - lw, H - lw);
    this.setTag(this.hoverE, info.label || '', false);
  }

  // Última linha opaca (de cima, em px) da coluna central do tile do assento; cacheada. Alinha o corpo rebaixado com a borda do móvel.
  rimOf(ft) {
    if (ft.rim != null) return ft.rim;
    let r = 0;
    for (let y = this.T - 1; y >= 0; y--) if (this.textures.getPixelAlpha(16, y, ft.ts, ft.f) > 0) { r = y + 1; break; }
    return (ft.rim = r);
  }

  // Agentes Kiroo: folha 16x48 de quadros 32x32 (ver sprites.js). Não tem as faixas da folha LimeZu.
  drawKiroo(e, t) {
    const inv = tagScale(this.cameras.main.zoom, window.devicePixelRatio || 1);
    const action = e.walking ? 'walk' : (e.work || e.anim === 'type' ? 'work' : 'idle');
    // caminhada: 16 quadros = 2 passos = 2 tiles; espera 8 quadros a ~5 fps; trabalho 16 quadros a ~8 fps
    const phase = this.reduced ? 0 : (e.walking
      ? walkPhase(e.dist || 0, this.T, 2)
      : action === 'work' ? (t * 8 / 16) % 1 : (t * 5 / 8) % 1);
    const frame = kirooFrame(e.dir, phase, action);
    const lift = e.anim === 'happy' && !this.reduced ? Math.round(Math.abs(Math.sin(t * 6)) * 3) : 0;
    if (e.img.texture.key !== e.sheet) e.img.setTexture(e.sheet);
    e.img.setCrop().setFrame(frame).setOrigin(0.5, KIROO_FOOT / 32).setScale(KIROO_SCALE);
    const rx = Math.round(e.x);
    const ry = Math.round(e.y - lift);
    e.img.setPosition(rx, ry).setVisible(true);
    if (e.cover) e.cover.setVisible(false);
    e.tag.box.setScale(inv).setPosition(...tagPosTop(rx, ry, KIROO_HEAD * KIROO_SCALE, inv)).setVisible(true);
    e.img.setDepth(e.seated && !e.walking ? e.foot + 1 : e.y);
  }

  // Humano LimeZu: quadro escolhido por pose; andar é função da distância percorrida (sem deslizar nem andar no lugar)
  drawHuman(e, t) {
    const anim = e.anim || 'idle', inv = tagScale(this.cameras.main.zoom, window.devicePixelRatio || 1);
    // sentado continua no sit mesmo pedindo atenção (need) ou acenando: o aviso é o "!" do balão; a pose phone é só para quem está em pé
    const sitting = e.seated && !e.walking;
    let frame, lift = 0, pose;
    if (e.walking) { pose = 'walk'; frame = walkFrame(e.dir, walkPhase(e.dist || 0, this.T, e.id === '__player' ? 2 : 1)); }
    else if (sitting) {
      // A (frente) / B (costas) só se o mapa tem o tile do assento; senão sit de lado
      const si = Math.floor(e.x / this.T), sj = Math.round(e.foot / this.T);
      const m = this.furnTile.has(si + ',' + sj) ? seatMode((this.seatInfo.get(si + ',' + (sj - 1)) || {}).kind, e.face) : 'C';
      if (m === 'A') { pose = 'sitA'; frame = idleFrame('down', 0); }
      else if (m === 'B') { pose = 'sitB'; frame = idleFrame('up', 0); }
      else { pose = 'sit'; frame = sitFrame(sitSide(e.face), anim === 'type' && !this.reduced ? Math.floor(t * 8) : 0); }
    }
    else if (e.need || anim === 'wave') { pose = 'phone'; if (e.pose !== 'phone') e.poseT = t; frame = phoneFrame(this.reduced ? 1 : t - e.poseT); }
    else if (anim === 'happy') { pose = 'happy'; frame = idleFrame('down', 0); lift = this.reduced ? 0 : Math.round(Math.abs(Math.sin(t * 6)) * 3); }
    else { pose = 'idle'; frame = idleFrame(e.dir, this.reduced ? 0 : Math.floor(t * 4)); }
    e.pose = pose;
    if (e.img.texture.key !== e.sheet) e.img.setTexture(e.sheet);
    e.img.setFrame(frame).setOrigin(0.5, 1).setScale(1);
    // Rebaixado (sitA/sitB): o corpo desce até a borda do assento (rim), `cut` px de perna ficam escondidos e a faixa de baixo do tile do
    // assento é redesenhada por cima do personagem (cover), cobrindo as pernas. O sofá tem ~8 px vazios no tile; a cadeira não.
    const lowered = pose === 'sitA' || pose === 'sitB';
    const si = Math.floor(e.x / this.T), sj = Math.round(e.foot / this.T), ft = lowered && this.furnTile.get(si + ',' + sj);
    const rim = ft ? this.rimOf(ft) : 0;
    e.img.setCrop();
    let ry = Math.round(e.y + (e.dyOld - (pose === 'sit' ? SIT_DY : STAND_DY)) - lift);
    if (lowered) { e.img.setCrop(0, 0, FW, FH - SEAT.cut); ry = (sj - 1) * this.T + rim - SEAT.rimUp + SEAT.cut; }
    const rx = Math.round(e.x);
    e.img.setPosition(rx, ry).setVisible(true);
    if (lowered) {
      if (!e.cover) e.cover = this.add.image(0, 0, ft.ts, ft.f).setOrigin(0, 1);
      if (e.cover.texture.key !== ft.ts || e.cover.frame.name !== ft.f) e.cover.setTexture(ft.ts, ft.f);
      e.cover.setCrop(0, Math.max(0, rim - SEAT.cover), this.T, Math.min(rim, SEAT.cover)).setPosition(si * this.T, sj * this.T).setDepth(e.foot + 2).setVisible(true);
    } else if (e.cover) e.cover.setVisible(false);
    e.tag.box.setScale(inv).setPosition(...tagPosTop(rx, ry, HEAD, inv)).setVisible(true);
    // y-sorting pelo pé; sentado (ou pedindo atenção no lugar) fica na frente da própria cadeira
    e.img.setDepth(e.seated && !e.walking ? e.foot + 1 : e.y);
  }

  drawChar(e, t) {
    if (e.sheet) return e.sheetKind === 'kiroo' ? this.drawKiroo(e, t) : this.drawHuman(e, t);
    if (e.img.originY !== 23 / CH) e.img.setOrigin(0.5, 23 / CH).setScale(this.S);
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
      g.lineStyle(S, PW.primary, on ? 1 : 0.5).strokeRect(X + S / 2, Y + S / 2, T - S, T - S);
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
export function createOffice({ parent, tmj, urls, chars, width, height, onFrame, onView, onHover, level }) {
  const dpr = window.devicePixelRatio || 1;
  let scene = null;
  const game = new Phaser.Game({
    type: Phaser.AUTO, parent, banner: false, pixelArt: true, roundPixels: true, antialias: false,
    backgroundColor: PW.bg, audio: { noAudio: true },
    input: { keyboard: false, mouse: false, touch: false, gamepad: false },
    scale: { mode: Phaser.Scale.NONE, width: Math.round(width * dpr), height: Math.round(height * dpr), zoom: 1 / dpr },
    scene: new OfficeScene({ tmj, urls, chars, onView, onHover, level, onReady: (s) => { scene = s; if (pending) s.setState(pending); } }),
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
    zoomTo(level, anchor) { if (scene) scene.zoomTo(level, anchor); },
    panBy(dx, dy) { if (scene) scene.panBy(dx, dy); },
    center() { if (scene) scene.centerOnPlayer(); },
    pointer(p) { if (scene) scene.setPointer(p); },
    destroy() { game.destroy(true); },
  };
}

export { CW, CH };
