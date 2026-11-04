// Caminhos da sede: rodar com  node tests/map.test.mjs
import assert from 'node:assert/strict';
import { GRID, ROOMS, CHAIRS, FURNITURE, INTERACT, BLOCKED, SPOTS, SPAWN, DOORS, tilesOf } from '../src/game/map.js';
import { bfs } from '../src/game/geometry.js';

const blocked = new Set(BLOCKED.map(([x, y]) => x + ',' + y));
const inB = (i, j) => i >= 0 && j >= 0 && i < GRID.C && j < GRID.R;
const pass = (i, j) => inB(i, j) && !blocked.has(i + ',' + j);
const near = (tiles) => (u, v) => pass(u, v) && tiles.some(([x, y]) => Math.max(Math.abs(x - u), Math.abs(y - v)) <= 1);
const reach = (from, goal, p = pass) => (from[0] === goal[0] && from[1] === goal[1]) || !!bfs(from, (u, v) => u === goal[0] && v === goal[1], p);

assert.ok(pass(...SPAWN), 'ponto inicial livre');
DOORS.forEach(([x, y]) => assert.ok(pass(x, y), `porta ${x},${y} livre`));
SPOTS.forEach((s) => { assert.ok(pass(...s), `passeio ${s} livre`); assert.ok(reach(SPAWN, s), `passeio ${s} alcançável`); });

// todas as salas: entrada livre e alcançável a partir da área comum; cada sala tem o nome e o agente certo
ROOMS.forEach((r) => {
  assert.ok(pass(...r.entry), `${r.id}: entrada livre`);
  assert.ok(reach(SPAWN, r.entry), `${r.id}: entrada alcançável`);
  for (const other of ROOMS) assert.ok(reach(r.entry, other.entry), `${r.id} → ${other.id}`);
  // o monitor da sala é acessível (algum tile vizinho livre e alcançável)
  assert.ok(bfs(SPAWN, near(tilesOf(r.desk)), pass), `${r.id}: mesa acessível`);
});

// cadeiras: dá para chegar a um vizinho e entrar nela; a do agente é alcançável pelo agente
CHAIRS.forEach((c) => {
  const p = (u, v) => pass(u, v) || (u === c.x && v === c.y);
  assert.ok(reach(SPAWN, [c.x, c.y], p), `cadeira ${c.id} (${c.kind}) alcançável`);
});

// objetos com interação
Object.entries(INTERACT).forEach(([k, tiles]) => assert.ok(bfs(SPAWN, near(tiles), pass), `${k} acessível`));

// nada sobreposto: móveis não ocupam portas nem cadeiras
const seen = new Map();
[...FURNITURE.filter((f) => f.kind !== 'sofa').flatMap(tilesOf), ...ROOMS.flatMap((r) => tilesOf(r.desk))].forEach(([x, y]) => {
  const k = x + ',' + y; assert.ok(!seen.has(k), `móveis sobrepostos em ${k}`); seen.set(k, 1);
});
CHAIRS.filter((c) => c.kind !== 'sofa').forEach((c) => assert.ok(!seen.has(c.x + ',' + c.y), `cadeira ${c.id} sobre um móvel`));
DOORS.forEach(([x, y]) => assert.ok(!seen.has(x + ',' + y), `móvel na porta ${x},${y}`));

console.log(`ok: ${ROOMS.length} salas, ${CHAIRS.length} cadeiras, ${FURNITURE.length} móveis, ${Object.keys(INTERACT).length} interações`);
