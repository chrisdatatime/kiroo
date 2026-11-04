import React from 'react';
import { GRID } from '../game/data.js';
import PixelOffice from '../game/pixel/renderer.js';

// Sede: canvas em pixel art do tamanho da tela + camada HTML (placas, nomes, cliques) em pixels de mundo.
// O renderizador move as duas com a mesma câmera; textos usam --inv para manter o tamanho na tela em qualquer zoom.
export default function World({ v }) {
  const canvas = React.useRef(null), overlay = React.useRef(null), office = React.useRef(null);
  const latest = React.useRef(v);
  latest.current = v;
  React.useEffect(() => {
    office.current = new PixelOffice(canvas.current, overlay.current);
    office.current.resize(latest.current.vw, latest.current.vh);
    office.current.update(latest.current);
    office.current.setTarget(latest.current.camX, latest.current.camY, latest.current.zoom);
    return () => { office.current.dispose(); office.current = null; };
  }, []);
  React.useEffect(() => { if (office.current) { office.current.update(v); office.current.setTarget(v.camX, v.camY, v.zoom); } });
  React.useEffect(() => { if (office.current) office.current.resize(v.vw, v.vh); }, [v.vw, v.vh]);

  return (
    <>
      <canvas ref={canvas} aria-hidden="true" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block', imageRendering: 'pixelated' }} />
      <div ref={overlay} className="px-world" onClick={v.onWorldClick} style={{ width: GRID.W, height: GRID.H }}>
        {v.hots.map((h) => (
          <button key={h.key} className="px-hot" onClick={h.click} aria-label={h.aria} style={{ left: h.x, top: h.y, width: h.w, height: h.h }}>
            <span className={'px-tag' + (h.always ? '' : ' px-tag-hover') + (h.lime ? ' px-tag-lime' : '')}>{h.label}</span>
          </button>
        ))}

        {v.rooms.map((r) => (
          <button key={r.id} className={'px-sign' + (r.need ? ' px-sign-need' : '')} onClick={r.click} aria-label={`${r.name}: ${r.status}. Ir para a sala`} style={{ left: r.x, top: r.y }}>
            <strong>{r.name}</strong>
            {r.status && <span>{r.status}</span>}
          </button>
        ))}

        {v.chars.map((c) => (
          <button key={c.id} className="px-char" onClick={c.click} aria-label={c.aria} style={{ left: c.l, top: c.t, zIndex: c.z }}>
            {(c.need || c.work || c.near) && c.status && <span className={'px-bubble' + (c.need ? ' px-bubble-need' : '')}>{c.status}</span>}
            <span className={'px-tag' + (c.near ? ' px-tag-lime' : '')}>{c.tagText}</span>
          </button>
        ))}

        <div aria-label="Você" className="px-char px-me" style={{ left: v.pl.l, top: v.pl.t, zIndex: v.pl.z }}>
          <span className="px-tag px-tag-lime">Você</span>
        </div>
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
