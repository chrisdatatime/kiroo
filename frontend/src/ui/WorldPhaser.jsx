import React from 'react';
import { GRID, TMJ } from '../game/data.js';
import { createOffice } from '../game/phaser/OfficeScene.js';

// Tilesets LimeZu (assets/tilesets, fora do git: licença). O Interiors_32x32.png (34.048 px) fica de fora: passa do limite
// de textura WebGL. O mapa usa interiors_atlas.png, gerado por tools/build_map.py só com os tiles do Interiors usados.
const FILES = import.meta.glob(['../../../assets/tilesets/*.png', '!../../../assets/tilesets/Interiors_32x32.png'], { query: '?url', import: 'default', eager: true });
const URLS = {};
Object.entries(FILES).forEach(([path, url]) => { URLS[path.split('/').pop().replace(/\.png$/, '')] = url; });

// Sede no Phaser (SPEC-VIS-001, Fase 2): canvas do Phaser + a mesma camada HTML do renderizador antigo
// (placas, nomes, balões, cliques), que acompanha a câmera do Phaser a cada frame.
export default function WorldPhaser({ v }) {
  const host = React.useRef(null), overlay = React.useRef(null), office = React.useRef(null);
  const latest = React.useRef(v);
  latest.current = v;
  React.useEffect(() => {
    const o = createOffice({
      parent: host.current, tmj: TMJ, urls: URLS, width: latest.current.vw, height: latest.current.vh,
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

  return (
    <>
      <div ref={host} aria-hidden="true" style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }} />
      <div ref={overlay} className="px-world" onClick={v.onWorldClick} style={{ width: GRID.W, height: GRID.H }}>
        {v.hots.map((h) => (
          <button key={h.key} className="px-hot" onClick={h.click} aria-label={h.aria} style={{ left: h.x, top: h.y, width: h.w, height: h.h }}>
            <span className={'px-tag' + (h.always ? '' : ' px-tag-hover') + (h.lime ? ' px-tag-lime' : '')}>{h.label}</span>
          </button>
        ))}

        {v.rooms.filter((r) => r.placed).map((r) => (
          <button key={r.id} className={'px-sign' + (r.need ? ' px-sign-need' : '')} onClick={r.click} aria-label={`${r.name}: ${r.status}. Ir para a sala`} style={{ left: r.x, top: r.y }}>
            <strong>{r.name}</strong>
            {r.status && <span>{r.status}</span>}
          </button>
        ))}

        {v.chars.map((c) => (
          // o nome é desenhado pelo Phaser (preso ao sprite); aqui ficam só o clique e o balão (escondido enquanto anda)
          <button key={c.id} className="px-char" data-walk={c.walking ? '1' : undefined} onClick={c.click} aria-label={c.aria} style={{ left: c.l, top: c.t, zIndex: c.z, width: c.w, height: c.h }}>
            {(c.need || c.work || c.near) && c.status && <span className={'px-bubble' + (c.need ? ' px-bubble-need' : '')}>{c.status}</span>}
          </button>
        ))}

        <div aria-label="Você" className="px-char px-me" style={{ left: v.pl.l, top: v.pl.t, zIndex: v.pl.z, width: v.pl.w, height: v.pl.h }} />
      </div>

      {v.celebrate && (
        <div aria-hidden="true" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden', zIndex: 5 }}>
          {v.confetti.map((cf, k) => (
            <span key={k} className="conf" style={{ left: cf.x + '%', background: cf.c, animationDelay: cf.d + 's', animationDuration: cf.t + 's' }} />
          ))}
        </div>
      )}
    </>
  );
}
