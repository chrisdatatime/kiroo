import React from 'react';
import { lazyChunk } from '../lib/lazyChunk.jsx';
import { GRID, TMJ } from '../game/data.js';
import { createOffice } from '../game/phaser/OfficeScene.js';
import { CHARACTER_SHEETS, STAND_DY, characterSheetSpec } from '../game/phaser/sprites.js';
import { stepLevel, wheelAccumulator, wheelPx, loadLevel, saveLevel } from '../game/phaser/zoom.js';
import ZoomControls from './world/ZoomControls.jsx';
import InfoCard from './world/InfoCard.jsx';

// Detalhe da sala só carrega no primeiro clique numa placa
const RoomDialog = lazyChunk(() => import('./world/RoomDialog.jsx'));
const typing = (t) => { const g = ((t && t.tagName) || '').toLowerCase(); return g === 'input' || g === 'textarea' || g === 'select' || !!(t && t.isContentEditable); };

// Tilesets LimeZu (assets/tilesets, fora do git: licença). O Interiors_32x32.png (34.048 px) fica de fora: passa do limite
// de textura WebGL. O mapa usa interiors_atlas.png, gerado por tools/build_map.py só com os tiles do Interiors usados.
const FILES = import.meta.glob(['../../../assets/tilesets/*.png', '!../../../assets/tilesets/Interiors_32x32.png'], { query: '?url', import: 'default', eager: true });
const URLS = {};
Object.entries(FILES).forEach(([path, url]) => { URLS[path.split('/').pop().replace(/\.png$/, '')] = url; });

// Personagens: agentes PIVOO 32x32 e jogador LimeZu 32x64. Sem os PNGs, o mundo cai no feijão de characters.js.
const CH_FILES = import.meta.glob('../../../assets/characters/*.png', { query: '?url', import: 'default', eager: true });
const CH_URLS = {};
Object.entries(CH_FILES).forEach(([path, url]) => { CH_URLS[path.split('/').pop().replace(/\.png$/, '')] = url; });
// Caixa de clique acompanha a escala visual, centralizada nos pés do personagem.
const T = TMJ.tilewidth;
const humanBox = (c, who) => {
  if (!CH_URLS[CHARACTER_SHEETS[who]]) return { left: c.l, top: c.t, width: c.w, height: c.h };
  const { head, frameWidth, scale } = characterSheetSpec(who);
  const width = frameWidth * scale, height = head * scale;
  return { left: (c.i + 0.5) * T - width / 2, top: (c.j + 1) * T - STAND_DY - height, width, height };
};

// Sede no Phaser (SPEC-VIS-001, Fase 2): canvas do Phaser + a mesma camada HTML do renderizador antigo
// (placas, nomes, balões, cliques), que acompanha a câmera do Phaser a cada frame.
// Fase 4: paleta clara (tokens --pw-*), zoom 1x-4x com tween, arrastar o mapa, hover cards e detalhe da sala em Dialog.
// O container (.pw-root) não recebe ponteiro; só os filhos (camada do mapa, controles) recebem.
export default function WorldPhaser({ v }) {
  const root = React.useRef(null), host = React.useRef(null), overlay = React.useRef(null), office = React.useRef(null);
  const latest = React.useRef(v);
  latest.current = v;
  // estado do zoom vem da cena só quando muda (onView); nada por frame
  const [view, setView] = React.useState(() => { const l = loadLevel(); return { level: l || 1, auto: l == null, free: false }; });
  const viewRef = React.useRef(view); viewRef.current = view;
  const [dlg, setDlg] = React.useState({ id: null, open: false });

  const zoomStep = React.useCallback((dir, anchor) => {
    const cur = viewRef.current, next = stepLevel(cur.level, dir);
    if (next === cur.level) return;
    saveLevel(next);
    if (office.current) office.current.zoomTo(next, anchor);
  }, []);
  const zoomAuto = React.useCallback(() => { saveLevel(null); if (office.current) office.current.zoomTo(null); }, []);
  const center = React.useCallback(() => { if (office.current) office.current.center(); }, []);

  React.useEffect(() => {
    const o = createOffice({
      parent: host.current, tmj: TMJ, urls: URLS, chars: CH_URLS, width: latest.current.vw, height: latest.current.vh,
      level: loadLevel(), onView: setView,
      // cursor do mundo sem React: só um atributo no overlay (CSS troca o cursor)
      onHover: (kind) => { if (overlay.current) overlay.current.dataset.hover = kind || ''; },
      onFrame: (cam, dpr) => {
        const el = overlay.current; if (!el) return;
        const z = cam.zoom / dpr, wv = cam.worldView;
        el.style.transform = `translate(${-Math.round(wv.x * cam.zoom) / dpr}px, ${-Math.round(wv.y * cam.zoom) / dpr}px) scale(${z})`;
        el.style.setProperty('--inv', String(1 / z));
      },
    });
    o.update(latest.current);
    office.current = o;
    return () => { o.destroy(); office.current = null; };
  }, []);
  React.useEffect(() => { if (office.current) office.current.update(v); });
  React.useEffect(() => { if (office.current) office.current.resize(v.vw, v.vh); }, [v.vw, v.vh]);

  // Roda do mouse (zoom no cursor), arrastar o mapa (botão do meio em qualquer ponto do mundo, ou esquerdo no chão) e + / -.
  React.useEffect(() => {
    const stage = root.current && root.current.parentElement; if (!stage) return undefined;
    const inWorld = (t) => t === stage || t === root.current || (overlay.current && overlay.current.contains(t));
    const acc = wheelAccumulator();
    const onWheel = (e) => {
      if (!inWorld(e.target)) return;
      e.preventDefault(); // inclui a pinça do trackpad (ctrl+wheel): zoom do mapa, não da página
      const dir = acc(wheelPx(e), performance.now()); if (!dir) return;
      const rc = host.current.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      zoomStep(dir, { x: (e.clientX - rc.left) * dpr, y: (e.clientY - rc.top) * dpr });
    };
    let drag = null, lastDrag = 0;
    const onDown = (e) => {
      const mid = e.button === 1 && inWorld(e.target), floor = e.button === 0 && e.target === overlay.current;
      if (!mid && !floor) return;
      if (mid) e.preventDefault(); // sem auto-scroll do navegador
      drag = { x: e.clientX, y: e.clientY, id: e.pointerId, on: false };
    };
    // hover do mapa: posição do ponteiro em px do canvas; placas e controles por cima escondem o destaque
    const hover = (e) => {
      if (!office.current) return;
      const t = e.target, over = inWorld(t) && !(t.closest && t.closest('.px-sign'));
      if (!over || (drag && drag.on)) { office.current.pointer(null); return; }
      const rc = host.current.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      office.current.pointer({ x: (e.clientX - rc.left) * dpr, y: (e.clientY - rc.top) * dpr });
    };
    const onLeave = () => { if (office.current) office.current.pointer(null); };
    const onMove = (e) => {
      if (e.pointerType !== 'touch') hover(e);
      if (!drag || e.pointerId !== drag.id) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.on && Math.abs(dx) + Math.abs(dy) < 5) return;
      if (!drag.on) { drag.on = true; stage.classList.add('pw-dragging'); try { stage.setPointerCapture(e.pointerId); } catch { /* ok */ } }
      drag.x = e.clientX; drag.y = e.clientY;
      if (office.current) office.current.panBy(dx, dy);
    };
    const onUp = (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      if (drag.on) { stage.classList.remove('pw-dragging'); lastDrag = performance.now(); }
      drag = null;
    };
    // o clique que fecha um arraste não manda o jogador andar até o ponto
    const onClickCap = (e) => { if (performance.now() - lastDrag < 80) { e.stopPropagation(); e.preventDefault(); } };
    const onAux = (e) => { if (e.button === 1 && inWorld(e.target)) e.preventDefault(); };
    const onKey = (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || (e.target && e.target.closest && e.target.closest('[role="dialog"]'))) return;
      const k = e.key;
      if (k === '+' || k === '=' || e.code === 'NumpadAdd') { e.preventDefault(); zoomStep(1); }
      else if (k === '-' || k === '_' || e.code === 'NumpadSubtract') { e.preventDefault(); zoomStep(-1); }
    };
    const on = [['wheel', onWheel, { passive: false }], ['pointerdown', onDown], ['pointermove', onMove], ['pointerup', onUp],
      ['pointercancel', onUp], ['pointerleave', onLeave], ['auxclick', onAux], ['click', onClickCap, true]];
    on.forEach(([n, f, o]) => stage.addEventListener(n, f, o));
    window.addEventListener('keydown', onKey);
    return () => {
      on.forEach(([n, f, o]) => stage.removeEventListener(n, f, o));
      window.removeEventListener('keydown', onKey);
      stage.classList.remove('pw-dragging');
    };
  }, [zoomStep]);

  const roomOf = (id) => v.rooms.find((r) => r.id === id);
  const dlgRoom = dlg.id ? roomOf(dlg.id) : null;

  return (
    <div ref={root} className="pw-root">
      <div ref={host} aria-hidden="true" style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }} />
      <div ref={overlay} className="px-world" onClick={v.onWorldClick} style={{ width: GRID.W, height: GRID.H }}>
        {v.hots.map((h) => (
          <button key={h.key} className="px-hot" onClick={h.click} aria-label={h.aria} style={{ left: h.x, top: h.y, width: h.w, height: h.h }}>
            <span className={'px-tag' + (h.always ? '' : ' px-tag-hover') + (h.lime ? ' px-tag-lime' : '')}>{h.label}</span>
          </button>
        ))}

        {v.rooms.filter((r) => r.placed).map((r) => (
          <InfoCard key={r.id} title={r.name} subtitle={r.who ? `${r.who}${r.role ? ' · ' + r.role : ''}` : ''} status={r.status} need={r.need}
            onGo={r.go} onOpen={r.agent ? r.work : null}>
            <button className={'px-sign' + (r.need ? ' px-sign-need' : '')} onClick={(e) => { e.stopPropagation(); setDlg({ id: r.id, open: true }); }}
              aria-label={`${r.name}: ${r.status}. Ver detalhes`} aria-haspopup="dialog" style={{ left: r.x, top: r.y }}>
              {r.need && <i className="px-sign-alert" aria-hidden="true">!</i>}
              <strong>{r.name}</strong>
              {r.status && <span>{r.status}</span>}
            </button>
          </InfoCard>
        ))}

        {v.chars.map((c) => {
          const room = c.room ? roomOf(c.room) : null;
          // o nome é desenhado pelo Phaser (preso ao sprite); aqui ficam só o clique e o balão (escondido enquanto anda)
          return (
            <InfoCard key={c.id} title={c.name || c.tagText} subtitle={[c.role, room && room.name].filter(Boolean).join(' · ')} status={c.status} need={c.need}
              onTalk={c.click} onOpen={room ? room.work : null}>
              <button className="px-char" data-walk={c.walking ? '1' : undefined} onClick={c.click} aria-label={c.aria} style={{ ...humanBox(c, c.id), zIndex: c.z }}>
                {(c.need || c.work || c.near) && c.status && <span className={'px-bubble' + (c.need ? ' px-bubble-need' : '')}>{c.status}</span>}
              </button>
            </InfoCard>
          );
        })}

        <div aria-label="Você" className="px-char px-me" style={{ ...humanBox(v.pl, '__player'), zIndex: v.pl.z }} />
      </div>

      {v.celebrate && (
        <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 5 }}>
          {v.confetti.map((cf, k) => (
            <span key={k} className="conf" style={{ left: cf.x + '%', background: cf.c, animationDelay: cf.d + 's', animationDuration: cf.t + 's' }} />
          ))}
        </div>
      )}

      <ZoomControls view={view} onIn={() => zoomStep(1)} onOut={() => zoomStep(-1)} onCenter={center} onAuto={zoomAuto} />

      {dlg.id && (
        <React.Suspense fallback={null}>
          <RoomDialog room={dlgRoom} open={dlg.open} onOpenChange={(open) => setDlg((d) => ({ ...d, open }))} />
        </React.Suspense>
      )}
    </div>
  );
}
