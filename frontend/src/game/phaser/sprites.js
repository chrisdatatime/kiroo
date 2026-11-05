// Personagens humanos do LimeZu (Character Generator 2.0, versão 32x32) no mundo Phaser (SPEC-VIS-001, Fase 3).
// Só o renderer Phaser usa isto. characters.js (feijão Kiroo), Boneco.jsx e o renderer canvas seguem intactos.
//
// Folha (conferida nos PNGs reais, ver assets/characters/contact-sheet.png): 1792x1312, quadro 32x64, 56 colunas.
// A grade começa em (0,0); 1312 = 20 faixas de 64 + 32 px vazios no fim (o Phaser descarta o resto).
// Índices 0-based. Direções (idle/walk, 6 quadros cada): direita 0-5, cima/costas 6-11, esquerda 12-17, baixo/frente 18-23.
//   faixa 1 idle (24)   faixa 2 walk (24, 1 ciclo = 2 passos)   faixa 4 sit (12: direita 0-5, esquerda 6-11, perna visível)
//   faixa 5 sit2 (12: direita 0-5, esquerda 6-11, perna escondida)   faixa 6 phone (12, de frente: 0-2 início, 3-8 loop, 9-11 fim)
// Só existe sentado de lado (sit); por isso sofá/puff e cadeira de mesa usam idle rebaixado (ver SEAT/seatMode abaixo). Nas faixas 6 e 7 os quadros 12+ são rótulos do guia, não usar.
// Pé: a última linha opaca é y=63 (andando/parado) ou y=61 (sentado); a cabeça começa em y=16 (topo do corpo = 48 px acima do pé).
// Dois formatos coexistem: o jogador ainda usa a folha LimeZu 32x64; os seis agentes usam as folhas Kiroo
// 512x1536 = 16 colunas x 48 linhas de quadros 32x32 (grade exata, sem margem). Corpo ocupa y 3..29 do quadro.
// 8 direções em sentido horário a partir da frente: S, SW, W, NW, N, NE, E, SE (só as 4 cardeais são usadas).
//   linhas 0-3   espera (idle): 8 quadros por direção, 2 direções por linha (S/SW, W/NW, N/NE, E/SE)
//   linhas 4-11  caminhada: 16 quadros por direção, 1 direção por linha (S, SW, W, NW, N, NE, E, SE)
//   linha 20     de frente com prancheta, 16 quadros (usada como "trabalhando" quando virado para baixo)
export const FW = 32, FH = 64, COLS = 56;
export const PIVOO_FW = 32, PIVOO_FH = 32, PIVOO_COLS = 16, PIVOO_FOOT = 29, PIVOO_HEAD = 27;
export const PIVOO_SCALE = 2; // corpo de ~52 px no mundo, com pixels inteiros
export const HEAD = 48;      // px do pé ao topo da cabeça (nome fica acima disso)
export const STAND_DY = 4;   // pé 4 px acima da base do tile (como o sprite antigo)
export const SIT_DY = 6;     // sentado: a sprite sit termina em y=61, então desce 2 px a menos que o pé em pé (ajustar vendo o jogo)
// Sentado (decisão do Chris): sofá/puff/poltrona (encosto ao norte) = idle de FRENTE rebaixado; cadeira de mesa (agent/visitor) = idle de COSTAS
// rebaixado; assento virado para left/right = sit de lado. Rebaixado = corpo alinhado pela última linha opaca do tile do assento, `cut` px de
// perna escondidos e a faixa de baixo do tile (`cover` px) redesenhada por cima. Sem tile de assento no mapa, cai no sit de lado.
export const SEAT = { cut: 4, cover: 8, rimUp: 2 };
export function seatMode(kind, face) {
  if (face === 'left' || face === 'right') return 'C';
  return kind === 'agent' || kind === 'visitor' ? 'B' : 'A';
}
export const DIRS ={ right: 0, up: 1, left: 2, down: 3 };

// agente (ou '__player') → arquivo em assets/characters/
export const CHARACTER_SHEETS = { nina: 'nina', theo: 'theo', iris: 'iris', rui: 'rui', lia: 'lia', beto: 'beto', __player: 'voce' };
const PIVOO_IDS = new Set(['nina', 'theo', 'iris', 'rui', 'lia', 'beto']);

export function characterSheetSpec(id) {
  return PIVOO_IDS.has(id)
    ? { kind: 'pivoo', frameWidth: PIVOO_FW, frameHeight: PIVOO_FH, head: PIVOO_HEAD, scale: PIVOO_SCALE }
    : { kind: 'human', frameWidth: FW, frameHeight: FH, head: HEAD, scale: 1 };
}

const PIVOO_DIR = { down: 0, left: 2, up: 4, right: 6 };
export function pivooFrame(dir, phase = 0, action = 'idle') {
  const d = PIVOO_DIR[dir] != null ? PIVOO_DIR[dir] : 0;
  const ph = ((phase % 1) + 1) % 1;
  if (action === 'walk') return (4 + d) * PIVOO_COLS + Math.min(15, Math.floor(ph * 16));
  if (action === 'work' && d === 0) return 20 * PIVOO_COLS + Math.min(15, Math.floor(ph * 16));
  return (d >> 1) * PIVOO_COLS + (d & 1) * 8 + Math.min(7, Math.floor(ph * 8));
}

const at = (row, col) => row * COLS + col;
const dirOf = (d) => (DIRS[d] != null ? DIRS[d] : DIRS.down);

export function idleFrame(dir, k) { return at(1, dirOf(dir) * 6 + (((k % 6) + 6) % 6)); }
// phase 0..1 = fração de um ciclo (6 quadros)
export function walkFrame(dir, phase) { return at(2, dirOf(dir) * 6 + Math.min(5, Math.floor((((phase % 1) + 1) % 1) * 6))); }
// só há esquerda/direita; cadeiras viradas para cima/baixo usam a direita
export function sitSide(face) { return face === 'left' ? 'left' : 'right'; }
export function sitFrame(side, k) { return at(5, (side === 'left' ? 6 : 0) + (((k % 6) + 6) % 6)); }
// phone: tocar o início (0-2) uma vez e depois o loop (3-8). `s` = segundos desde que a pose começou
export function phoneFrame(s, fps = 8, startSec = 0.3) {
  if (s < startSec) return at(6, Math.min(2, Math.floor(s / startSec * 3)));
  return at(6, 3 + Math.floor((s - startSec) * fps) % 6);
}
// distância andada (px) → fase do ciclo. Jogador: 1 ciclo a cada 2 tiles; agentes: 1 ciclo por tile.
export function walkPhase(dist, tilePx, tilesPerCycle) { return (dist / (tilePx * tilesPerCycle)) % 1; }
