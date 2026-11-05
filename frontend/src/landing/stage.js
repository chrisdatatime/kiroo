// Lógica pura da home (sem React), testada em tests/landing.test.mjs.
// A "câmera" da home é um quadro (frame) que mostra um recorte da sede.webp; tudo em px da imagem (1216x1024, tiles de 32 px).

export const IMG = { w: 1216, h: 1024 };

// Atos dos bastidores: cada um enquadra salas vizinhas da sede. rect = [x, y, largura, altura] em px da imagem.
export const ACTS = [
  { id: 'pre', n: 1, name: 'Pré-produção', title: 'Plano e direção', crew: ['nina', 'theo'], rect: [0, 0, 800, 300] },
  { id: 'prod', n: 2, name: 'Produção', title: 'Imagens e vídeos', crew: ['iris', 'lia'], rect: [880, 0, 336, 640] },
  { id: 'pos', n: 3, name: 'Pós-produção', title: 'Revisão e montagem', crew: ['rui', 'beto'], rect: [400, 720, 816, 304] },
];
export const WIDE = [0, 0, IMG.w, IMG.h];

// Salas da sede (px da imagem), para recortes estáticos.
export const ROOMS = {
  nina: [0, 0, 320, 256], theo: [416, 0, 384, 256], iris: [896, 0, 320, 256],
  lia: [896, 352, 320, 288], rui: [416, 736, 384, 288], beto: [896, 736, 320, 288], comum: [320, 256, 576, 480],
};

export const clamp01 = (t) => (t < 0 ? 0 : t > 1 ? 1 : t);
export const mix = (a, b, t) => a + (b - a) * t;
export const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const mixRect = (a, b, t) => ({ x: mix(a.x, b.x, t), y: mix(a.y, b.y, t), w: mix(a.w, b.w, t), h: mix(a.h, b.h, t) });

// Câmera que enquadra rect num quadro fw x fh. 'contain' mostra o rect inteiro; 'cover' preenche o quadro com ele.
// Nunca afasta tanto que apareça o fundo além da imagem.
export function fitCamera([x, y, w, h], fw, fh, mode = 'contain') {
  const k = mode === 'cover' ? Math.max(fw / w, fh / h) : Math.min(fw / w, fh / h);
  return { s: Math.max(k, fw / IMG.w, fh / IMG.h), cx: x + w / 2, cy: y + h / 2 };
}

// Mistura de câmeras: escala em log (o zoom parece linear ao olho), centro linear.
export const mixCam = (a, b, t) => ({ s: Math.exp(mix(Math.log(a.s), Math.log(b.s), t)), cx: mix(a.cx, b.cx, t), cy: mix(a.cy, b.cy, t) });

// Deslocamento da imagem para centrar a câmera no quadro, preso às bordas da imagem.
export function pan({ s, cx, cy }, fw, fh) {
  const lim = (v, lo, hi) => (lo > hi ? (lo + hi) / 2 : Math.min(hi, Math.max(lo, v)));
  return { x: lim(fw / 2 - cx * s, fw - IMG.w * s, 0), y: lim(fh / 2 - cy * s, fh - IMG.h * s, 0) };
}

// segundos → "MM:SS" (timecode); valores inválidos viram "--:--"
export function fmtTC(s) {
  if (!Number.isFinite(s) || s < 0) return '--:--';
  const t = Math.floor(s);
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
}

// largura/altura do arquivo → "Vertical 9:16", "Quadrado 1:1"... (proporções comuns com 2% de tolerância)
const RATIOS = [[9, 16], [3, 4], [4, 5], [1, 1], [5, 4], [4, 3], [16, 9]];
export function fmtFormat(w, h) {
  if (!(w > 0 && h > 0)) return null;
  const r = w / h;
  const hit = RATIOS.find(([a, b]) => Math.abs(r / (a / b) - 1) < 0.02);
  const ratio = hit ? `${hit[0]}:${hit[1]}` : `${w}×${h}`;
  const kind = Math.abs(r - 1) < 0.02 ? 'Quadrado' : r < 1 ? 'Vertical' : 'Horizontal';
  return `${kind} ${ratio}`;
}
