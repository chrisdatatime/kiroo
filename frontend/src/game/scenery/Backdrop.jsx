import React from 'react';
import { PARALLAX, BACKDROP_FILTER, LAYER_H, pickScale, deviceScale, tileStart, layerOffset, bandRect, rgb } from './scenery.js';
import { loadLayers } from './layers.js';

// Cenário parallax atrás do mapa e das placas: um canvas 2D que cobre a viewport, sem capturar cliques.
// Pixel art sem blur (escala inteira, imageSmoothing desligado); acima e abaixo da faixa de 272 px, cor sólida das bordas do back.
// `api.current.setCam(x)` recebe a posição horizontal da câmera (px de tela) a cada frame; só redesenha quando muda.
export default function Backdrop({ theme, width, height, api }) {
  const ref = React.useRef(null);
  const st = React.useRef({ layers: null, cam: 0, raf: 0 });
  const reduced = React.useRef(false);

  const draw = React.useCallback(() => {
    const s = st.current, cv = ref.current; st.current.raf = 0;
    if (!cv || !s.layers) return;
    const dpr = window.devicePixelRatio || 1, W = cv.width, H = cv.height;
    const k = deviceScale(pickScale(H / dpr), dpr);
    const ctx = cv.getContext('2d'); ctx.imageSmoothingEnabled = false;
    const { y, h } = bandRect(H, k);
    ctx.fillStyle = rgb(s.layers.top); ctx.fillRect(0, 0, W, Math.max(0, y));
    ctx.fillStyle = rgb(s.layers.bottom); ctx.fillRect(0, y + h, W, Math.max(0, H - y - h));
    for (const [name, f] of [['back', PARALLAX.back], ['middle', PARALLAX.middle]]) {
      const img = s.layers[name], tw = img.width * k, off = layerOffset(s.cam * dpr, f, reduced.current);
      for (let x = tileStart(off, tw); x < W; x += tw) ctx.drawImage(img, 0, 0, img.width, LAYER_H, Math.round(x), y, tw, h);
    }
    // costura suave: a faixa termina na cor sólida de cima/baixo, sem degrau perceptível
    const e = Math.min(8 * k, h / 4);
    for (const [c, y0, y1] of [[s.layers.top, y, y + e], [s.layers.bottom, y + h, y + h - e]]) {
      const g = ctx.createLinearGradient(0, y0, 0, y1); g.addColorStop(0, rgb(c, 1)); g.addColorStop(1, rgb(c, 0));
      ctx.fillStyle = g; ctx.fillRect(0, Math.min(y0, y1), W, e);
    }
  }, []);
  const schedule = React.useCallback(() => { if (!st.current.raf) st.current.raf = requestAnimationFrame(draw); }, [draw]);

  React.useEffect(() => {
    const mq = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
    reduced.current = !!(mq && mq.matches);
    const on = () => { reduced.current = !!mq.matches; schedule(); };
    if (mq && mq.addEventListener) mq.addEventListener('change', on);
    return () => { if (mq && mq.removeEventListener) mq.removeEventListener('change', on); };
  }, [schedule]);

  React.useEffect(() => {
    let dead = false;
    loadLayers(theme).then((l) => { if (!dead) { st.current.layers = l; schedule(); } });
    return () => { dead = true; };
  }, [theme, schedule]);

  React.useEffect(() => {
    if (api) api.current = { setCam: (x) => { if (st.current.cam !== x) { st.current.cam = x; schedule(); } } };
    return () => { if (api) api.current = null; if (st.current.raf) cancelAnimationFrame(st.current.raf); };
  }, [api, schedule]);

  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(width * dpr)), h = Math.max(1, Math.round(height * dpr));
  React.useLayoutEffect(() => { draw(); }, [w, h, draw]); // redimensionar limpa o canvas: redesenha já
  return <canvas ref={ref} width={w} height={h} aria-hidden="true" data-testid="cenario" className="pw-backdrop"
    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', imageRendering: 'pixelated', filter: BACKDROP_FILTER }} />;
}
