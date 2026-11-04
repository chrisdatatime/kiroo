// Zoom da câmera (2b-2 + Fase 4). Pixel art: o zoom FINAL é sempre inteiro em pixels do dispositivo (sem blur).
// O usuário escolhe um nível 1x–4x (em px CSS); o Phaser usa floor(nível x DPR). Entre dois níveis a câmera anima
// (~150 ms) com zoom fracionário e, no fim, trava no inteiro e arredonda a posição.
// Automático (sem escolha salva): 1 em telas com 1280 px CSS ou mais (mapa quase inteiro), 2 nas menores.
const WIDE_PX = 1280;
export const LEVELS = [1, 2, 3, 4];
export const MIN_LEVEL = LEVELS[0], MAX_LEVEL = LEVELS[LEVELS.length - 1];

export function clampLevel(l) { return Math.min(MAX_LEVEL, Math.max(MIN_LEVEL, Math.round(Number(l) || MIN_LEVEL))); }
export function stepLevel(l, dir) { return clampLevel(clampLevel(l) + Math.sign(dir)); }
export function pickLevel(wCss) { return wCss >= WIDE_PX ? 1 : 2; }
export function deviceZoom(level, dpr = 1) { return Math.max(1, Math.floor(clampLevel(level) * dpr)); }
export function pickZoom(wDev, dpr = 1) { return deviceZoom(pickLevel(wDev / dpr), dpr); }

// Zoom ancorado num ponto da tela (sx em px do canvas): mantém o ponto do mundo sob o cursor.
// Câmera do Phaser com origem 0.5: mundo = scroll + w/2 + (sx - w/2) / zoom.
export function anchorScroll(scroll, sx, w, z0, z1) { return scroll + (sx - w / 2) * (1 / z0 - 1 / z1); }
// Ao travar num zoom inteiro, a posição vai para o pixel do dispositivo mais próximo.
export function snapScroll(scroll, z) { return Math.round(scroll * z) / z; }

// Roda do mouse / trackpad → passos de nível. Acumula o delta; um passo quando passa do limiar, e depois ignora o
// resto do gesto por `lock` ms (o trackpad manda dezenas de eventos pequenos: sem isso pularia vários níveis).
// Retorna +1 (aproximar, delta negativo), -1 (afastar) ou 0.
export function wheelAccumulator({ threshold = 40, lock = 200, idle = 250 } = {}) {
  let acc = 0, last = -Infinity, lockedUntil = -Infinity;
  return (delta, now) => {
    if (now - last > idle) acc = 0;
    last = now;
    if (now < lockedUntil) return 0;
    acc += delta;
    if (Math.abs(acc) < threshold) return 0;
    const dir = acc < 0 ? 1 : -1;
    acc = 0; lockedUntil = now + lock;
    return dir;
  };
}
// deltaMode do WheelEvent: 0 = px, 1 = linhas, 2 = páginas
export function wheelPx(e) { return e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1); }

// Nível escolhido pelo usuário (null = automático). localStorage pode faltar ou lançar (aba privada): tudo em try/catch.
const KEY = 'bc.zoom';
function store(s) { try { return s || (typeof localStorage !== 'undefined' ? localStorage : null); } catch { return null; } }
export function loadLevel(s) {
  try { const st = store(s); const raw = st && st.getItem(KEY); const n = Number(raw); return raw != null && LEVELS.includes(n) ? n : null; } catch { return null; }
}
export function saveLevel(level, s) {
  try { const st = store(s); if (!st) return; if (level == null) st.removeItem(KEY); else st.setItem(KEY, String(clampLevel(level))); } catch { /* sem armazenamento */ }
}

// Nome do personagem (OfficeScene): escala dpr/zoom mantém o tamanho na tela; a posição é o sprite arredondado
// mais um deslocamento que só depende de S e do zoom, então o offset nome↔sprite é constante enquanto anda.
export function tagScale(zoom, dpr = 1) { return dpr / zoom; }
export function tagPos(rx, ry, S, inv) { return [rx, Math.round(ry - 23 * S - inv)]; }
// mesmo princípio para sprites com altura em px do mundo (humanos LimeZu): headPx = pé → topo da cabeça
export function tagPosTop(rx, ry, headPx, inv) { return [rx, Math.round(ry - headPx - inv)]; }
