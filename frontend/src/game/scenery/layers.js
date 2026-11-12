// Camadas do cenário como canvases nativos (back 160x272, middle 384x272): dos PNGs do autor, se existirem em
// assets/cenarios/<pasta>/, ou geradas por código. O restante do pipeline (escala inteira, repetição, parallax) é o mesmo.
import { LAYER_H, SCENERY_DIR, SCENERY_FILES, GEN, skyline, treeLine, sampleEdges, rgb } from './scenery.js';

// PNGs fora do git (licença do autor; ver docs/ASSETS.md). Sem arquivos, o glob fica vazio e o fallback entra.
const FILES = import.meta.glob('../../../../assets/cenarios/*/*.png', { query: '?url', import: 'default', eager: true });
export function sceneryUrls(dir = SCENERY_DIR) {
  const out = {};
  Object.entries(FILES).forEach(([p, url]) => { const [d, f] = p.split('/').slice(-2); if (d === dir) out[f] = url; });
  const back = out[SCENERY_FILES.back], middle = out[SCENERY_FILES.middle];
  return back && middle ? { back, middle } : null;
}

const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
const loadImg = (url) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });

// Cenário gerado: céu em degradê (papel → toque do laranja), colinas e silhueta de floresta.
export function generatedLayers() {
  const back = mk(160, LAYER_H), middle = mk(384, LAYER_H);
  const b = back.getContext('2d');
  const g = b.createLinearGradient(0, 0, 0, LAYER_H);
  g.addColorStop(0, rgb(GEN.skyTop)); g.addColorStop(1, rgb(GEN.skyBottom));
  b.fillStyle = g; b.fillRect(0, 0, 160, LAYER_H);
  b.fillStyle = rgb(GEN.hillFar);
  for (let x = 0; x < 160; x += 1) { const y = skyline(x, 160, 170, 12, 1); b.fillRect(x, y, 1, LAYER_H - y); }
  const m = middle.getContext('2d');
  m.fillStyle = rgb(GEN.hillNear);
  for (let x = 0; x < 384; x += 1) { const y = skyline(x, 384, 205, 14, 2); m.fillRect(x, y, 1, LAYER_H - y); }
  m.fillStyle = rgb(GEN.tree);
  for (let x = 0; x < 384; x += 1) { const y = treeLine(x, 384, 250, 3); m.fillRect(x, y, 1, LAYER_H - y); }
  m.fillStyle = rgb(GEN.ground); m.fillRect(0, 252, 384, LAYER_H - 252);
  return { back, middle };
}

// { back, middle, top, bottom }: top/bottom = cores das bordas do back (para preencher acima/abaixo da faixa).
export async function loadLayers(theme) {
  let layers = null;
  const urls = theme === 'floresta' ? sceneryUrls() : null;
  if (urls) {
    try { const [back, middle] = await Promise.all([loadImg(urls.back), loadImg(urls.middle)]); layers = { back, middle }; }
    catch { layers = null; } // arquivo corrompido: cai no gerado
  }
  if (!layers) layers = generatedLayers();
  const w = layers.back.width, h = layers.back.height;
  const c = mk(w, h), x = c.getContext('2d'); x.drawImage(layers.back, 0, 0);
  const { top, bottom } = sampleEdges(x.getImageData(0, 0, w, h).data, w, h);
  return { ...layers, top, bottom };
}
