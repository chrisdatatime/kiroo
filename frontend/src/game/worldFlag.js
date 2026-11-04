// Feature flag do renderizador do mundo (SPEC-VIS-001, Fase 2).
//   canvas = renderizador antigo em Canvas 2D (padrão até a validação)   phaser = .tmj do Tiled no Phaser 3
// Escolha: ?world=phaser|canvas na URL (fica salvo) ou o botão em Minha conta. Lido uma vez, ao carregar a página.
const KEY = 'bc.world';

function read() {
  try {
    const q = new URLSearchParams(window.location.search).get('world');
    if (q === 'phaser' || q === 'canvas') { localStorage.setItem(KEY, q); return q; }
    return localStorage.getItem(KEY) === 'phaser' ? 'phaser' : 'canvas';
  } catch { return 'canvas'; }
}

export const WORLD = typeof window === 'undefined' ? 'canvas' : read();

// Troca o renderizador: o mapa muda de grade (16 → 32 px), então recarrega a página.
export function setWorld(mode) {
  try { localStorage.setItem(KEY, mode === 'phaser' ? 'phaser' : 'canvas'); } catch { /* sem armazenamento */ }
  const u = new URL(window.location.href); u.searchParams.delete('world');
  window.location.replace(u.toString());
}
