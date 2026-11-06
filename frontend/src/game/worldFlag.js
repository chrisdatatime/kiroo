// Feature flag do renderizador do mundo (SPEC-VIS-001, Fase 2).
//   phaser = .tmj do Tiled no Phaser 3 (padrão)   canvas = renderizador antigo em Canvas 2D (opt-in: ?world=canvas ou o botão)
// Escolha: ?world=phaser|canvas na URL (fica salvo em localStorage 'bc.world') ou o botão em Minha conta. Lido uma vez, ao carregar a página.
// Só quem escolheu 'canvas' explicitamente continua nele; sem escolha salva, o mundo é o Phaser.
const KEY = 'bc.world';

function read() {
  try {
    const q = new URLSearchParams(window.location.search).get('world');
    if (q === 'phaser' || q === 'canvas') { localStorage.setItem(KEY, q); return q; }
    return localStorage.getItem(KEY) === 'canvas' ? 'canvas' : 'phaser';
  } catch { return 'phaser'; }
}

export const WORLD = typeof window === 'undefined' ? 'phaser' : read();

// Troca o renderizador: o mapa muda de grade (16 → 32 px), então recarrega a página.
export function setWorld(mode) {
  try { localStorage.setItem(KEY, mode === 'phaser' ? 'phaser' : 'canvas'); } catch { /* sem armazenamento */ }
  const u = new URL(window.location.href); u.searchParams.delete('world');
  window.location.replace(u.toString());
}
