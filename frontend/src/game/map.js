// DEPRECATED (SPEC-VIS-001): o mundo vai migrar para tileset LimeZu + Tiled + Phaser 3. Não acrescente móveis
// nem paredes desenhados por código aqui; veja docs/SPEC-VIS-001.md. Mantido até a Fase 2 ser validada.
// Mapa da sede, vista de cima (RPG 2D). Só dados: salas, paredes, portas, móveis, cadeiras e pontos de interação.
// Formato 16:9 compacto, para a sede inteira caber na tela com os tiles grandes (referência: Gather).
// Coordenadas em tiles; 1 tile = T pixels de mundo. O desenho fica em game/pixel/, a colisão em game/geometry.js.

export const T = 16;
export const GRID = { C: 52, R: 30, T, W: 52 * T, H: 30 * T };
// Prédio dentro do mundo; o que sobra na borda é jardim (só visual).
export const BUILD = { x0: 2, y0: 1, x1: 49, y1: 28 };

// Salas (interior, sem as paredes). desk = estação do agente; seat/visitor = cadeiras de frente para a mesa (olhando para cima).
export const ROOMS = [
  { id: 'planejamento', floor: 'lav', name: 'Planejamento', hint: 'Briefing, produtos e organização', agent: 'nina', tab: 'produto', x0: 3, y0: 3, x1: 16, y1: 11,
    desk: { x: 7, y: 4, w: 4, h: 2, screens: ['planning', 'sheet'] }, seat: [8, 6], visitor: [10, 6], entry: [9, 11] },
  { id: 'direcao', floor: 'blue', name: 'Direção criativa', hint: 'Referências, roteiros e storyboard', agent: 'theo', tab: 'direcao', x0: 18, y0: 3, x1: 32, y1: 11,
    desk: { x: 23, y: 4, w: 4, h: 2, screens: ['story', 'script'] }, seat: [24, 6], visitor: [26, 6], entry: [25, 11] },
  { id: 'imagens', floor: 'gray', name: 'Imagens', hint: 'Design e geração de imagens', agent: 'iris', tab: 'imagens', x0: 34, y0: 3, x1: 48, y1: 11,
    desk: { x: 39, y: 4, w: 4, h: 2, screens: ['image', 'palette'] }, seat: [40, 6], visitor: [42, 6], entry: [41, 11] },
  { id: 'meu', floor: 'lime', name: 'Meu escritório', hint: 'Seu setup e acompanhamento geral', agent: null, tab: null, x0: 3, y0: 19, x1: 12, y1: 27,
    desk: { x: 5, y: 21, w: 4, h: 2 }, seat: [6, 23], visitor: null, entry: [8, 19] },
  { id: 'videos', floor: 'lav', name: 'Vídeos', hint: 'Cenário, câmera, luz e trilhas', agent: 'lia', tab: 'videos', x0: 14, y0: 19, x1: 23, y1: 27,
    desk: { x: 18, y: 24, w: 4, h: 2, screens: ['video', 'wave'] }, seat: [19, 26], visitor: [21, 26], entry: [19, 19] },
  { id: 'edicao', floor: 'slate', name: 'Edição', hint: 'Timeline, montagem e áudio', agent: 'beto', tab: 'entrega', x0: 25, y0: 19, x1: 35, y1: 27,
    desk: { x: 27, y: 21, w: 6, h: 2, screens: ['timeline', 'timelineWide', 'timeline'] }, seat: [29, 23], visitor: [31, 23], entry: [30, 19] },
  { id: 'revisao', floor: 'gray', name: 'Revisão', hint: 'Comparação e aprovação', agent: 'rui', tab: 'revisao', x0: 37, y0: 19, x1: 48, y1: 27,
    desk: { x: 41, y: 22, w: 4, h: 2, screens: ['review', 'checklist'] }, seat: [42, 24], visitor: [44, 24], entry: [43, 19] },
];
export const COMMON = { id: 'comum', name: 'Área comum', x0: 3, y0: 13, x1: 48, y1: 17 };

// Portas: tiles livres nas paredes internas (3 tiles cada)
export const DOORS = [
  ...[8, 9, 10, 24, 25, 26, 40, 41, 42].map((x) => [x, 12]),
  ...[7, 8, 9, 18, 19, 20, 29, 30, 31, 42, 43, 44].map((x) => [x, 18]),
];

// Paredes: externas (a de cima tem 2 tiles para janelas e quadros) e internas
function buildWalls() {
  const set = new Map();
  const add = (x, y, kind) => set.set(x + ',' + y, { x, y, kind });
  for (let x = BUILD.x0; x <= BUILD.x1; x++) {
    add(x, BUILD.y0, 'outerTop'); add(x, BUILD.y0 + 1, 'outerTop'); add(x, BUILD.y1, 'outerBottom');
    add(x, 12, 'h'); add(x, 18, 'h');
  }
  for (let y = BUILD.y0; y <= BUILD.y1; y++) { add(BUILD.x0, y, 'side'); add(BUILD.x1, y, 'side'); }
  for (let y = 3; y <= 11; y++) { add(17, y, 'v'); add(33, y, 'v'); }
  for (let y = 19; y <= 27; y++) { add(13, y, 'v'); add(24, y, 'v'); add(36, y, 'v'); }
  DOORS.forEach(([x, y]) => set.delete(x + ',' + y));
  return [...set.values()];
}
export const WALLS = buildWalls();

// Móveis: [tipo, x, y, largura, altura, opções]. Todos bloqueiam a passagem.
const F = (kind, x, y, w = 1, h = 1, opts = {}) => ({ kind, x, y, w, h, opts });
export const FURNITURE = [
  // Planejamento
  F('bookshelf', 3, 3, 3, 1), F('cabinet', 12, 3), F('plant', 16, 3, 1, 1, { v: 1 }), F('plant', 3, 11, 1, 1, { v: 2 }),
  F('boxes', 15, 10, 2, 1), F('meetingTable', 4, 8, 4, 2), F('flipchart', 12, 8),
  // Direção criativa
  F('plant', 18, 3), F('artShelf', 29, 3, 3, 1), F('plant', 32, 3, 1, 1, { v: 1 }),
  F('refTable', 19, 8, 4, 2), F('easel', 30, 8), F('plant', 32, 11, 1, 1, { v: 2 }),
  // Imagens
  F('plant', 34, 3, 1, 1, { v: 1 }), F('paintShelf', 45, 3, 3, 1), F('plant', 48, 3),
  F('printer', 34, 8, 2, 1), F('tabletDesk', 45, 8, 2, 2), F('plant', 48, 11, 1, 1, { v: 2 }),
  // Meu escritório
  F('bookshelf', 9, 19, 3, 1), F('plant', 3, 19), F('plant', 12, 19, 1, 1, { v: 1 }), F('plant', 3, 27, 1, 1, { v: 2 }), F('sideTable', 11, 25),
  // Área comum: y=14 fica sempre livre, é o corredor que liga a sede inteira
  F('prodBoard', 4, 13, 2, 1), F('coffeeBar', 20, 13, 5, 1), F('roundTable', 21, 16, 2, 2),
  F('sofa', 28, 15, 3, 1), F('lowTable', 28, 17, 3, 1), F('floorLamp', 32, 15), F('gamesTable', 38, 16),
  F('bookshelf', 43, 13, 3, 1), F('waterCooler', 47, 13),
  F('plant', 3, 13), F('plant', 8, 13, 1, 1, { v: 1 }), F('plant', 34, 13, 1, 1, { v: 2 }), F('plant', 48, 13),
  F('plant', 15, 17, 1, 1, { v: 2 }), F('plant', 26, 17), F('plant', 48, 17, 1, 1, { v: 1 }),
  // Vídeos
  F('greenScreen', 15, 21, 6, 1), F('pedestal', 17, 22), F('softbox', 14, 22, 1, 1, { face: 'right' }), F('softbox', 22, 22, 1, 1, { face: 'left' }),
  F('camera', 18, 23), F('musicShelf', 14, 27, 3, 1), F('speaker', 23, 27), F('plant', 23, 19, 1, 1, { v: 1 }),
  // Edição
  F('rack', 33, 19, 3, 1), F('speaker', 26, 21), F('speaker', 33, 21), F('mixer', 27, 26, 4, 1),
  F('plant', 25, 19, 1, 1, { v: 2 }), F('plant', 35, 27), F('plant', 25, 27, 1, 1, { v: 1 }),
  // Revisão
  F('compareScreen', 38, 19, 4, 1), F('checklistBoard', 45, 19, 3, 1), F('meetingTable', 38, 26, 4, 2, { review: true }),
  F('plant', 37, 19), F('plant', 48, 19, 1, 1, { v: 2 }), F('plant', 48, 27, 1, 1, { v: 1 }),
];

// Cadeiras: o jogador pode sentar em todas, menos nas cadeiras de trabalho dos agentes. face = para onde a pessoa olha.
const CH = (x, y, face, kind = 'office', extra = {}) => ({ id: `c${x}_${y}`, x, y, face, kind, ...extra });
export const CHAIRS = [
  ...ROOMS.filter((r) => r.agent).map((r) => CH(r.seat[0], r.seat[1], 'up', 'agent', { agent: r.agent, room: r.id })),
  ...ROOMS.filter((r) => r.agent).map((r) => CH(r.visitor[0], r.visitor[1], 'up', 'visitor', { room: r.id })),
  CH(6, 23, 'up', 'mine', { room: 'meu' }),
  // reuniões
  CH(3, 8, 'right', 'meeting'), CH(8, 9, 'left', 'meeting'), CH(5, 7, 'down', 'meeting'), CH(6, 7, 'down', 'meeting'), CH(5, 10, 'up', 'meeting'), CH(6, 10, 'up', 'meeting'),
  CH(37, 26, 'right', 'meeting'), CH(42, 27, 'left', 'meeting'), CH(39, 25, 'down', 'meeting'), CH(40, 25, 'down', 'meeting'),
  CH(18, 8, 'right', 'meeting'), CH(23, 9, 'left', 'meeting'), CH(44, 9, 'right', 'stool'), CH(47, 10, 'up', 'stool'),
  // área comum
  CH(20, 16, 'right', 'cafe'), CH(23, 16, 'left', 'cafe'), CH(21, 15, 'down', 'cafe'), CH(22, 15, 'down', 'cafe'),
  CH(37, 16, 'right', 'stool'), CH(39, 16, 'left', 'stool'),
  CH(28, 15, 'down', 'sofa'), CH(29, 15, 'down', 'sofa'), CH(30, 15, 'down', 'sofa'),
  CH(34, 16, 'down', 'beanbag', { color: '#B8B4DE' }), CH(12, 16, 'down', 'beanbag', { color: '#D5F45B' }), CH(10, 23, 'down', 'beanbag', { color: '#8ED8F8' }),
];

// Tapetes (chão) e decoração de parede (face visível das paredes)
export const RUGS = [
  { x: 4, y: 7, w: 5, h: 4, color: 'cream' }, { x: 19, y: 7, w: 5, h: 4, color: 'lime' }, { x: 43, y: 7, w: 5, h: 4, color: 'sky' },
  { x: 27, y: 14, w: 8, h: 4, color: 'lime' }, { x: 16, y: 23, w: 6, h: 3, color: 'cream' },
  { x: 26, y: 24, w: 8, h: 3, color: 'sky' }, { x: 38, y: 24, w: 6, h: 3, color: 'cream' },
];
export const WALL_DECOR = [
  { kind: 'window', x: 4, w: 4 }, { kind: 'kanban', x: 9, w: 6 }, { kind: 'window', x: 15, w: 2 },
  { kind: 'window', x: 19, w: 4 }, { kind: 'storyboard', x: 24, w: 6 }, { kind: 'window', x: 31, w: 2 },
  { kind: 'window', x: 35, w: 4 }, { kind: 'gallery', x: 40, w: 5 }, { kind: 'window', x: 46, w: 3 },
  // paredes internas (1 tile de face)
  { kind: 'frames', x: 5, y: 12, w: 3 }, { kind: 'tv', x: 36, y: 12, w: 3 }, { kind: 'frames', x: 45, y: 12, w: 3 },
  { kind: 'panels', x: 14, y: 18, w: 4 }, { kind: 'frames', x: 26, y: 18, w: 3 }, { kind: 'frames', x: 38, y: 18, w: 3 },
];
export const LOGO_WALL = { x: 28, y: 12, w: 4 }; // logo oficial com dois spots, na parede da área comum

// Jardim ao redor do prédio (só visual): [tipo, x, y]
export const OUTSIDE = [
  ['tree', 0, 3], ['bush', 0, 7], ['tree', 0, 11], ['bush', 1, 15], ['tree', 0, 19], ['bush', 0, 24], ['tree', 1, 27],
  ['tree', 50, 3], ['bush', 50, 8], ['tree', 50, 12], ['bush', 51, 16], ['tree', 50, 20], ['bush', 50, 25], ['tree', 51, 28],
  ['bush', 6, 29], ['tree', 12, 29], ['bush', 20, 29], ['tree', 30, 29], ['bush', 38, 29], ['tree', 45, 29],
  ['bush', 8, 0], ['bush', 22, 0], ['bush', 36, 0], ['bush', 46, 0],
];

export const MY_DESK = [6, 21];
export const MY_SEAT = [6, 23];
export const BOARD = [4, 13];
export const COFFEE = [22, 13];
export const GAMES_TILE = [38, 16];
export const MUSIC_SHELF = [14, 27];
export const SPAWN = [25, 15];

export const tilesOf = (f) => { const out = []; for (let a = 0; a < f.w; a++) for (let b = 0; b < f.h; b++) out.push([f.x + a, f.y + b]); return out; };
const byKind = (k) => FURNITURE.find((f) => f.kind === k);

// Objetos com interação e os tiles que ocupam
export const INTERACT = {
  board: tilesOf(byKind('prodBoard')),
  coffee: tilesOf(byKind('coffeeBar')),
  games: tilesOf(byKind('gamesTable')),
  music: tilesOf(byKind('musicShelf')),
  mine: tilesOf({ ...ROOMS.find((r) => r.id === 'meu').desk }),
};

// Bloqueios: jardim, paredes, móveis, mesas de trabalho e cadeiras (cadeira é destino, não passagem)
const outside = [];
for (let x = 0; x < GRID.C; x++) for (let y = 0; y < GRID.R; y++) {
  if (x < BUILD.x0 || x > BUILD.x1 || y < BUILD.y0 || y > BUILD.y1) outside.push([x, y]);
}
export const BLOCKED = [
  ...outside,
  ...WALLS.map((w) => [w.x, w.y]),
  ...FURNITURE.flatMap(tilesOf),
  ...ROOMS.flatMap((r) => tilesOf(r.desk)),
  ...CHAIRS.map((c) => [c.x, c.y]),
];

// Onde os agentes livres passeiam
export const SPOTS = [[6, 15], [11, 14], [16, 14], [26, 14], [31, 16], [35, 15], [41, 14], [46, 15], [9, 14], [44, 14]];
