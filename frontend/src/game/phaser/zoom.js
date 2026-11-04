// Zoom da câmera (2b-2): 1 em telas com 1280 px CSS ou mais (mapa quase inteiro), 2 nas menores.
// Inteiro em pixels do dispositivo (sem blur): (1 ou 2) x DPR, arredondado para baixo.
const WIDE_PX = 1280;
export function pickZoom(wDev, dpr = 1) { return Math.max(1, Math.floor((wDev / dpr >= WIDE_PX ? 1 : 2) * dpr)); }

// Nome do personagem (OfficeScene): escala dpr/zoom mantém o tamanho na tela; a posição é o sprite arredondado
// mais um deslocamento que só depende de S e do zoom, então o offset nome↔sprite é constante enquanto anda.
export function tagScale(zoom, dpr = 1) { return dpr / zoom; }
export function tagPos(rx, ry, S, inv) { return [rx, Math.round(ry - 23 * S - inv)]; }
