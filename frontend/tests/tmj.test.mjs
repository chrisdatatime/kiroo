// Mapa novo (assets/maps/office.tmj, SPEC-VIS-001 Fase 2): rodar com  node tests/tmj.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildWorld, usedTilesets } from '../src/game/world/tmjWorld.js';
import { ROOMS as META, tilesOf } from '../src/game/map.js';
import { bfs } from '../src/game/geometry.js';

const tmj = JSON.parse(readFileSync(new URL('../../assets/maps/office.tmj', import.meta.url), 'utf-8'));
const { GRID, ROOMS, CHAIRS, BLOCKED, SPOTS, SPAWN } = buildWorld(tmj, META);

// ordem das camadas: móveis em pé entre os de trás e os da frente
const order = tmj.layers.map((l) => l.name);
assert.deepEqual(order, ['floor', 'walls', 'furniture_below', 'furniture_sorted', 'furniture_above', 'collision', 'objects']);
assert.equal(GRID.T, 32);

const blocked = new Set(BLOCKED.map(([x, y]) => x + ',' + y));
const inB = (i, j) => i >= 0 && j >= 0 && i < GRID.C && j < GRID.R;
const pass = (i, j) => inB(i, j) && !blocked.has(i + ',' + j);
const reach = (from, goal, p = pass) => (from[0] === goal[0] && from[1] === goal[1]) || !!bfs(from, (u, v) => u === goal[0] && v === goal[1], p);

assert.ok(pass(...SPAWN), 'spawn livre');
assert.ok(SPOTS.length >= 1, 'pelo menos um spot');
SPOTS.forEach((s) => { assert.ok(pass(...s), `spot ${s} livre`); assert.ok(reach(SPAWN, s), `spot ${s} alcançável`); });

// salas: todas as do jogo continuam listadas; a Edição está no mapa e ligada ao Beto
META.forEach((m) => assert.ok(ROOMS.some((r) => r.id === m.id), `${m.id} nos metadados`));
const ed = ROOMS.find((r) => r.id === 'edicao');
assert.ok(ed.placed, 'edicao no mapa');
assert.equal(ed.agent, 'beto');
assert.equal(ed.tab, 'entrega');
assert.ok(ed.desk && ed.seat, 'edicao tem mesa e cadeira do agente');
assert.ok(reach(SPAWN, ed.entry), 'entrada da edição alcançável');
ROOMS.filter((r) => !r.placed).forEach((r) => assert.ok(!r.desk && !r.seat, `${r.id} fora do mapa sem geometria antiga`));

// a mesa (monitor) é acessível: algum vizinho livre e alcançável
const near = (tiles) => (u, v) => pass(u, v) && tiles.some(([x, y]) => Math.max(Math.abs(x - u), Math.abs(y - v)) <= 1);
assert.ok(bfs(SPAWN, near(tilesOf(ed.desk)), pass), 'mesa da edição acessível');

// cadeiras: bloqueiam a passagem, mas dá para chegar e sentar; o agente alcança a própria a partir dos spots
CHAIRS.forEach((c) => {
  assert.ok(blocked.has(c.x + ',' + c.y), `cadeira ${c.id} bloqueia`);
  const p = (u, v) => pass(u, v) || (u === c.x && v === c.y);
  assert.ok(reach(SPAWN, [c.x, c.y], p), `cadeira ${c.id} (${c.kind}) alcançável`);
});
const agentSeat = CHAIRS.find((c) => c.kind === 'agent' && c.agent === 'beto');
assert.ok(agentSeat, 'cadeira do Beto');
SPOTS.forEach((s) => assert.ok(reach(s, [agentSeat.x, agentSeat.y], (u, v) => pass(u, v) || (u === agentSeat.x && v === agentSeat.y)), `Beto volta de ${s}`));

// textura: nenhum tileset usado pode passar de 16384 px (limite comum de WebGL); hoje o Interiors não é usado
usedTilesets(tmj).forEach((t) => assert.ok(t.imageheight <= 16384 && t.imagewidth <= 16384, `${t.name} cabe numa textura`));

console.log(`ok: mapa ${GRID.C}x${GRID.R} (tile ${GRID.T}), ${ROOMS.filter((r) => r.placed).length}/${ROOMS.length} salas no mapa, ${CHAIRS.length} cadeiras, ${SPOTS.length} spots, tilesets: ${usedTilesets(tmj).map((t) => t.name).join(', ')}`);
