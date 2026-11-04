// Mapa novo (assets/maps/office.tmj, SPEC-VIS-001 Fase 2): rodar com  node tests/tmj.test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildWorld, usedTilesets } from '../src/game/world/tmjWorld.js';
import { ROOMS as META, tilesOf } from '../src/game/map.js';
import { bfs } from '../src/game/geometry.js';
import { pickZoom, tagScale, tagPos } from '../src/game/phaser/zoom.js';
import { initialAgent, stepSeated } from '../src/game/agentLife.js';

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

// Fase 2b-1: a sede inteira está no mapa. Toda sala do jogo (e as novas) está colocada, ligada ao agente certo,
// com a entrada alcançável a partir do spawn e sem tile útil isolado nas salas vazias.
const SETORES = { planejamento: 'nina', direcao: 'theo', imagens: 'iris', videos: 'lia', edicao: 'beto', revisao: 'rui' };
Object.entries(SETORES).forEach(([id, agent]) => assert.equal(ROOMS.find((r) => r.id === id).agent, agent, `${id} -> ${agent}`));
['entrada', 'jogos', 'patio', 'meu'].forEach((id) => assert.ok(ROOMS.some((r) => r.id === id), `sala ${id} no mapa`));
ROOMS.forEach((r) => {
  assert.ok(r.placed, `${r.id} está no mapa (sem sala fora do mapa)`);
  assert.ok(pass(...r.entry), `entrada de ${r.id} livre`);
  assert.ok(reach(SPAWN, r.entry), `entrada de ${r.id} alcançável a partir do spawn`);
  if (!r.desk && r.id !== 'meu') {
    for (let j = r.y0; j <= r.y1; j++) for (let i = r.x0; i <= r.x1; i++)
      if (pass(i, j)) assert.ok(reach(SPAWN, [i, j]), `${r.id}: tile (${i},${j}) isolado`);
  }
});
// cada sala tem porta: o corredor mais próximo é alcançável sem atravessar parede (já coberto pelo BFS acima);
// a Entrada contém o spawn e o mapa tem uma única trilha de corredores ligando tudo
const ent = ROOMS.find((r) => r.id === 'entrada');
assert.ok(SPAWN[0] >= ent.x0 && SPAWN[0] <= ent.x1 && SPAWN[1] >= ent.y0 && SPAWN[1] <= ent.y1, 'spawn na Entrada');

// a mesa (monitor) é acessível: algum vizinho livre e alcançável
const near = (tiles) => (u, v) => pass(u, v) && tiles.some(([x, y]) => Math.max(Math.abs(x - u), Math.abs(y - v)) <= 1);
assert.ok(bfs(SPAWN, near(tilesOf(ed.desk)), pass), 'mesa da edição acessível');

// cadeiras: bloqueiam a passagem, mas dá para chegar e sentar; o agente alcança a própria a partir dos spots
CHAIRS.forEach((c) => {
  assert.ok(blocked.has(c.x + ',' + c.y), `cadeira ${c.id} bloqueia`);
  const p = (u, v) => pass(u, v) || (u === c.x && v === c.y);
  assert.ok(reach(SPAWN, [c.x, c.y], p), `cadeira ${c.id} (${c.kind}) alcançável`);
});
// assentos (cadeiras, sofás, puffs, cabine): todos alcançáveis do spawn e com um tile livre ao lado (alcançável) para levantar
CHAIRS.forEach((c) => {
  const ok = [[0, 1], [0, -1], [1, 0], [-1, 0]].some(([di, dj]) => pass(c.x + di, c.y + dj) && reach(SPAWN, [c.x + di, c.y + dj]));
  assert.ok(ok, `assento ${c.id} (${c.kind}, ${c.room}) sem tile livre alcançável ao lado para levantar`);
  assert.ok(c.room && ROOMS.some((r) => r.id === c.room), `assento ${c.id} sem sala`);
});
// os móveis de sentar da sede têm assento: pelo menos um por sala de descanso, e a cabine tem o dela (kind mine)
const seatsIn = (id, kind) => CHAIRS.filter((c) => c.room === id && (!kind || c.kind === kind));
['entrada', 'jogos', 'patio', 'direcao'].forEach((id) => assert.ok(seatsIn(id, 'free').length >= 1, `${id} tem assento livre`));
assert.ok(seatsIn('jogos', 'free').length >= 7, 'jogos: 2 sofás (2 lugares) + 4 puffs');
assert.ok(seatsIn('patio', 'free').length >= 6, 'pátio: sofá de 3 (2 lugares) + 2 namoradeiras (2 lugares)');
assert.equal(seatsIn('meu', 'mine').length, 1, 'cabine tem a cadeira (kind mine)');
assert.ok(seatsIn('videos', 'visitor').length === 1, 'vídeos tem cadeira de visita');
assert.equal(new Set(CHAIRS.map((c) => c.id)).size, CHAIRS.length, 'assentos com ids únicos');
const agentSeat = CHAIRS.find((c) => c.kind === 'agent' && c.agent === 'beto');
assert.ok(agentSeat, 'cadeira do Beto');
// Fase 6: agentes fixos. Cada um fica sempre na cadeira (kind agent) da própria sala, em qualquer estado e por muitos passos;
// spots de corredor/pátio não são mais usados por agente (só o jogador navega).
const inRoom = (r, i, j) => i >= r.x0 && i <= r.x1 && j >= r.y0 && j <= r.y1;
let seed = 7; const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
Object.entries(SETORES).forEach(([id, agent]) => {
  const r = ROOMS.find((q) => q.id === id);
  assert.ok(r.seat && inRoom(r, r.seat[0], r.seat[1]), `cadeira de ${agent} dentro de ${id}`);
  const chair = CHAIRS.find((c) => c.kind === 'agent' && c.agent === agent);
  assert.ok(chair && chair.room === id && chair.x === r.seat[0] && chair.y === r.seat[1], `${agent}: assento do mapa = estação`);
  let st = initialAgent(r.seat, rand);
  for (let k = 0; k < 400; k++) {
    st = stepSeated(r.seat, st, ['idle', 'work', 'need'][Math.floor(rand() * 3)], rand);
    assert.ok(st.i === r.seat[0] && st.j === r.seat[1] && !st.path.length && !st.moving, `${agent} saiu da cadeira no passo ${k}`);
    assert.ok(inRoom(r, st.i, st.j), `${agent} fora de ${id}`);
    assert.ok(!SPOTS.some((s) => s[0] === st.i && s[1] === st.j), `${agent} num spot`);
  }
});

// Fase 2b-2: escala compacta (salas ~10x8, corredores de 3 tiles) e câmera 1x em telas largas
assert.ok(GRID.C <= 40 && GRID.R <= 32, `mapa compacto (${GRID.C}x${GRID.R})`);
['planejamento', 'imagens', 'edicao', 'entrada'].forEach((id) => {
  const r = ROOMS.find((q) => q.id === id);
  assert.ok(r.x1 - r.x0 + 1 === 10, `${id} tem 10 de largura`);
});
assert.equal(pickZoom(1280, 1), 1, 'zoom 1 em 1280 px');
assert.equal(pickZoom(1920, 1), 1, 'zoom 1 em 1920 px');
assert.equal(pickZoom(1024, 1), 2, 'zoom 2 em 1024 px');
assert.equal(pickZoom(1920, 1.5), 1, 'zoom 1 em 1920 CSS px com DPR 1,5 (inteiro em px do dispositivo)');
// nome do personagem: offset nome↔sprite constante em qualquer posição (andando) e tamanho constante na tela (escala = dpr/zoom)
[[1, 1], [2, 1], [1, 1.5], [3, 2]].forEach(([z, dpr]) => {
  const inv = tagScale(z, dpr), S = 2, off = [];
  for (let x = 100; x < 140; x += 0.37) { const rx = Math.round(x), ry = Math.round(300 + x * 0.61); const [tx, ty] = tagPos(rx, ry, S, inv); off.push((tx - rx) + ',' + (ty - ry)); }
  assert.equal(new Set(off).size, 1, `offset do nome constante (zoom ${z}, dpr ${dpr})`);
  assert.ok(Math.abs(inv * z - dpr) < 1e-9, 'nome com tamanho constante na tela');
});
// textura: nenhum tileset usado pode passar de 16384 px (limite comum de WebGL); o Interiors entra só pelo atlas
usedTilesets(tmj).forEach((t) => assert.ok(t.imageheight <= 16384 && t.imagewidth <= 16384, `${t.name} cabe numa textura`));

console.log(`ok: mapa ${GRID.C}x${GRID.R} (tile ${GRID.T}), ${ROOMS.filter((r) => r.placed).length}/${ROOMS.length} salas no mapa, ${CHAIRS.length} cadeiras, ${SPOTS.length} spots, tilesets: ${usedTilesets(tmj).map((t) => t.name).join(', ')}`);
