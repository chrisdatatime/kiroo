// Mundo a partir do office.tmj (SPEC-VIS-001, Fase 2): devolve o mesmo formato que game/map.js exporta
// (GRID, ROOMS, CHAIRS, FURNITURE, INTERACT, BLOCKED, SPOTS, SPAWN), para o App.jsx seguir igual.
// Função pura: sem Vite nem DOM, testada em tests/tmj.test.mjs.
//
// - Colisão: retângulos da camada `collision` + todo tile sem chão (o vazio fora das salas).
// - `objects`: room (id, agent, tab), seat, interact (monitor), entry, spawn, spot.
// - Salas que ainda não estão no .tmj (Fase 2b) entram só com os metadados (placed: false): continuam no HUD,
//   nos Setores e nas janelas, mas não têm mesa, cadeira nem posição no mapa.

const props = (o) => { const out = {}; (o.properties || []).forEach((p) => { out[p.name] = p.value; }); return out; };

export function buildWorld(tmj, meta) {
  const T = tmj.tilewidth, C = tmj.width, R = tmj.height;
  const GRID = { C, R, T, W: C * T, H: R * T };
  const layer = (name) => tmj.layers.find((l) => l.name === name);
  const cell = (o) => [Math.floor(o.x / T), Math.floor(o.y / T)];
  const rect = (o) => ({ x: Math.floor(o.x / T), y: Math.floor(o.y / T), w: Math.round(o.width / T), h: Math.round(o.height / T) });

  // colisão
  const blocked = new Set();
  const floor = layer('floor');
  for (let j = 0; j < R; j++) for (let i = 0; i < C; i++) if (!floor || !floor.data[j * C + i]) blocked.add(i + ',' + j);
  (layer('collision') || { objects: [] }).objects.forEach((o) => {
    const r = rect(o);
    for (let a = 0; a < r.w; a++) for (let b = 0; b < r.h; b++) blocked.add((r.x + a) + ',' + (r.y + b));
  });

  const objs = ((layer('objects') || { objects: [] }).objects).map((o) => ({ ...o, p: props(o) }));
  const ofType = (t) => objs.filter((o) => o.type === t);

  const CHAIRS = ofType('seat').map((o) => {
    const [x, y] = cell(o);
    return { id: `c${x}_${y}`, x, y, face: o.p.face || 'down', kind: o.p.kind || 'free', room: o.p.room, ...(o.p.agent ? { agent: o.p.agent } : {}), monitor: !!o.p.monitor };
  });
  CHAIRS.forEach((c) => blocked.add(c.x + ',' + c.y)); // cadeira é destino, não passagem

  const placed = {};
  ofType('room').forEach((o) => {
    const r = rect(o), id = o.p.id;
    const seat = CHAIRS.find((c) => c.room === id && c.kind === 'agent');
    const visitor = CHAIRS.find((c) => c.room === id && c.kind === 'visitor');
    const mon = objs.find((x) => x.type === 'interact' && x.p.action === 'monitor' && x.p.room === id);
    const entry = objs.find((x) => x.type === 'entry' && x.p.room === id);
    placed[id] = {
      placed: true, x0: r.x, y0: r.y, x1: r.x + r.w - 1, y1: r.y + r.h - 1,
      agent: o.p.agent || null, tab: o.p.tab || null, name: o.p.nome || o.name,
      desk: mon ? rect(mon) : null, seat: seat ? [seat.x, seat.y] : null, visitor: visitor ? [visitor.x, visitor.y] : null,
      entry: entry ? cell(entry) : [r.x + Math.floor(r.w / 2), r.y + r.h - 2],
    };
  });

  // metadados (nome, dica, agente) vêm da lista de salas do jogo; a geometria vem só do .tmj
  const ROOMS = meta.map(({ id, name, hint, agent, tab, floor: fl }) => {
    const p = placed[id];
    return p ? { id, hint, floor: fl, ...p, name: name || p.name, agent: p.agent || agent, tab: p.tab || tab } : { id, name, hint, agent, tab, floor: fl, placed: false };
  });
  Object.keys(placed).forEach((id) => { if (!meta.some((m) => m.id === id)) ROOMS.push({ id, hint: '', ...placed[id] }); });

  const spawnObj = ofType('spawn')[0];
  const SPAWN = spawnObj ? cell(spawnObj) : (ROOMS.find((r) => r.placed) || { entry: [0, 0] }).entry;
  const SPOTS = ofType('spot').map(cell);
  const BLOCKED = [...blocked].map((k) => k.split(',').map(Number));

  return { GRID, ROOMS, CHAIRS, FURNITURE: [], INTERACT: {}, BLOCKED, SPOTS, SPAWN };
}

// Tilesets realmente usados pelo mapa (camadas de tile e tile-objects). O Interiors_32x32.png tem 34.048 px de
// altura e passa do limite de textura WebGL: só pode ser carregado se algum GID dele for usado (Fase 2b: atlas).
export function usedTilesets(tmj) {
  const gids = new Set();
  tmj.layers.forEach((l) => {
    if (l.type === 'tilelayer') l.data.forEach((g) => { if (g) gids.add(g & 0x1fffffff); });
    else (l.objects || []).forEach((o) => { if (o.gid) gids.add(o.gid & 0x1fffffff); });
  });
  const sets = [...tmj.tilesets].sort((a, b) => a.firstgid - b.firstgid);
  return sets.filter((t) => [...gids].some((g) => g >= t.firstgid && g < t.firstgid + t.tilecount));
}
