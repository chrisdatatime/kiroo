import React from 'react';
import { GRID, ROOMS, WALLS, FURNITURE, tilesOf } from '../game/data.js';

// Minimapa: salas, paredes, móveis, você (lima) e a equipe. A moldura mostra o que a câmera enxerga; clicar leva até o ponto.
const S = 3; // px por tile
const COL = { planejamento: '#D9D6EE', direcao: '#D9D6EE', imagens: '#D9D6EE', meu: '#E9F7AE', videos: '#D9D6EE', edicao: '#C8EEFC', revisao: '#D9D6EE' };

function paintBase(c) {
  const x = c.getContext('2d');
  x.fillStyle = '#F3D7A6'; x.fillRect(0, 0, GRID.C * S, GRID.R * S);
  ROOMS.forEach((r) => { x.fillStyle = COL[r.id]; x.fillRect(r.x0 * S, r.y0 * S, (r.x1 - r.x0 + 1) * S, (r.y1 - r.y0 + 1) * S); });
  x.fillStyle = '#C9A877'; FURNITURE.forEach((f) => tilesOf(f).forEach(([i, j]) => x.fillRect(i * S, j * S, S, S)));
  ROOMS.forEach((r) => tilesOf(r.desk).forEach(([i, j]) => { x.fillStyle = '#8E6238'; x.fillRect(i * S, j * S, S, S); }));
  x.fillStyle = '#17234B'; WALLS.forEach(({ x: i, y: j }) => x.fillRect(i * S, j * S, S, S));
}

export default function Minimap({ v }) {
  const base = React.useRef(null), top = React.useRef(null);
  React.useEffect(() => { paintBase(base.current); }, []);
  React.useEffect(() => {
    const c = top.current; if (!c) return;
    const x = c.getContext('2d'); x.clearRect(0, 0, c.width, c.height);
    const m = v.minimap;
    m.agents.forEach((a) => { x.fillStyle = '#17234B'; x.fillRect(a.i * S - 1, a.j * S - 1, S + 2, S + 2); x.fillStyle = a.need ? '#D5F45B' : a.color; x.fillRect(a.i * S, a.j * S, S, S); });
    x.fillStyle = '#17234B'; x.fillRect(m.player[0] * S - 2, m.player[1] * S - 2, S + 4, S + 4);
    x.fillStyle = '#D5F45B'; x.fillRect(m.player[0] * S - 1, m.player[1] * S - 1, S + 2, S + 2);
    const vw = (v.vw / v.zoom / GRID.T) * S, vh = (v.vh / v.zoom / GRID.T) * S;
    const cx = (v.camX / GRID.T) * S, cy = (v.camY / GRID.T) * S;
    x.strokeStyle = '#17234B'; x.lineWidth = 1.5; x.strokeRect(Math.round(cx - vw / 2) + 0.5, Math.round(cy - vh / 2) + 0.5, Math.round(vw), Math.round(vh));
  });
  const click = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    v.walkTo(Math.floor(((e.clientX - r.left) / r.width) * GRID.C), Math.floor(((e.clientY - r.top) / r.height) * GRID.R));
  };
  return (
    <div className="g-hud" style={{ position: 'absolute', right: 14, top: 128, zIndex: 10, padding: 6, display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ font: '800 11px/1 Instrument Sans,sans-serif', color: '#545C78' }}>Mapa · clique para ir</span>
      <div style={{ position: 'relative', width: GRID.C * S, height: GRID.R * S, cursor: 'pointer' }} onClick={click} role="img" aria-label="Minimapa da sede">
        <canvas ref={base} width={GRID.C * S} height={GRID.R * S} style={{ position: 'absolute', inset: 0, imageRendering: 'pixelated' }} />
        <canvas ref={top} width={GRID.C * S} height={GRID.R * S} style={{ position: 'absolute', inset: 0 }} />
      </div>
    </div>
  );
}
