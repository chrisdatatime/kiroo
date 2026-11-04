import { GRID } from './map.js';

// Geometria da vista de cima: o tile (i, j) ocupa o quadrado [i*T, (i+1)*T) x [j*T, (j+1)*T) em pixels de mundo.
const { T } = GRID;

export const P = (i, j) => [i * T, j * T];
// Centro do tile
export const cen = (i, j) => [(i + 0.5) * T, (j + 0.5) * T];

// Converte coordenada de tela (no espaço do mundo) para tile; tile = 32 no mapa novo (Phaser)
export function screenToTile(x, y, tile = T) {
  return [Math.floor(x / tile), Math.floor(y / tile)];
}

// Direção de um passo na grade: o eixo dominante decide para onde o personagem olha
export function facing(di, dj, prev = 'down') {
  if (!di && !dj) return prev;
  if (Math.abs(di) > Math.abs(dj)) return di > 0 ? 'right' : 'left';
  return dj > 0 ? 'down' : 'up';
}

// BFS 8 direções sem cortar quinas
export function bfs(start, isGoal, pass) {
  const k = (i, j) => i + ',' + j;
  const prev = {}; prev[k(start[0], start[1])] = null; const q = [start];
  const D = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
  while (q.length) {
    const cur = q.shift();
    if (!(cur[0] === start[0] && cur[1] === start[1]) && isGoal(cur[0], cur[1])) {
      const path = []; let c = cur;
      while (c && !(c[0] === start[0] && c[1] === start[1])) { path.unshift(c); c = prev[k(c[0], c[1])]; }
      return path;
    }
    for (const d of D) {
      const ni = cur[0] + d[0], nj = cur[1] + d[1]; const kk = k(ni, nj);
      if (kk in prev || !pass(ni, nj)) continue;
      if (d[0] && d[1] && (!pass(cur[0] + d[0], cur[1]) || !pass(cur[0], cur[1] + d[1]))) continue;
      prev[kk] = cur; q.push([ni, nj]);
    }
  }
  return null;
}
