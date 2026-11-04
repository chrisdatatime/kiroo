// Minijogos da mesa de jogos: Jogo da Velha e Damas (regras brasileiras). Lógica pura, sem React.

// ------------------------------------------------------------------ Jogo da Velha
export const TTT_LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

export function tttResult(b) {
  for (const [a, c, d] of TTT_LINES) if (b[a] && b[a] === b[c] && b[a] === b[d]) return { who: b[a], line: [a, c, d] };
  return b.every(Boolean) ? { who: 'empate', line: [] } : null;
}

function minimax(b, turn, ai) {
  const r = tttResult(b);
  if (r) return { score: r.who === ai ? 10 : r.who === 'empate' ? 0 : -10 };
  let best = { score: turn === ai ? -Infinity : Infinity, move: -1 };
  for (let k = 0; k < 9; k++) {
    if (b[k]) continue;
    b[k] = turn;
    const { score } = minimax(b, turn === 'X' ? 'O' : 'X', ai);
    b[k] = null;
    const adj = score - Math.sign(score) * 0.01;  // prefere vencer cedo / perder tarde
    if (turn === ai ? adj > best.score : adj < best.score) best = { score: adj, move: k };
  }
  return best;
}

// skill 0..1: chance de jogar a melhor jogada (o resto é aleatório) — dá para ganhar do agente.
export function tttAiMove(board, ai = 'O', skill = 0.7, rnd = Math.random) {
  const empty = board.map((v, k) => (v ? null : k)).filter((k) => k !== null);
  if (!empty.length) return -1;
  if (rnd() > skill) return empty[Math.floor(rnd() * empty.length)];
  return minimax(board.slice(), ai, ai).move;
}

// ------------------------------------------------------------------ Damas (regras brasileiras)
// Tabuleiro 8x8 (índice = linha*8 + coluna). Peças: 'w' (você, de baixo) e 'b' (agente, de cima); maiúscula = dama.
// Captura obrigatória; deve-se escolher a sequência que captura MAIS peças; peão captura para frente e para trás;
// dama anda e captura à distância; peças capturadas saem só no fim da jogada; só promove se TERMINAR na última linha.
const DIRS = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
const inb = (r, c) => r >= 0 && r < 8 && c >= 0 && c < 8;
const at = (r, c) => r * 8 + c;
export const rc = (i) => [Math.floor(i / 8), i % 8];
export const sideOf = (p) => (p ? p.toLowerCase() : null);
export const isKing = (p) => !!p && p === p.toUpperCase();
const opp = (p, side) => !!p && sideOf(p) !== side;

export function damasInitial() {
  const b = Array(64).fill(null);
  for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
    if ((r + c) % 2 === 0) continue;
    if (r < 3) b[at(r, c)] = 'b';
    if (r > 4) b[at(r, c)] = 'w';
  }
  return b;
}

function captureSeqs(b, pos, side, king, caps, path) {
  const out = [];
  const [r, c] = rc(pos);
  for (const [dr, dc] of DIRS) {
    if (!king) {
      const mr = r + dr, mc = c + dc, lr = r + 2 * dr, lc = c + 2 * dc;
      if (!inb(lr, lc)) continue;
      const mid = at(mr, mc), land = at(lr, lc);
      if (opp(b[mid], side) && !caps.includes(mid) && b[land] === null)
        out.push(...captureSeqs(b, land, side, king, caps.concat(mid), path.concat(land)));
    } else {
      let rr = r + dr, cc = c + dc;
      while (inb(rr, cc) && b[at(rr, cc)] === null) { rr += dr; cc += dc; }
      if (!inb(rr, cc)) continue;
      const mid = at(rr, cc);
      if (!opp(b[mid], side) || caps.includes(mid)) continue;
      rr += dr; cc += dc;
      while (inb(rr, cc) && b[at(rr, cc)] === null) {
        const land = at(rr, cc);
        out.push(...captureSeqs(b, land, side, king, caps.concat(mid), path.concat(land)));
        rr += dr; cc += dc;
      }
    }
  }
  if (!out.length && caps.length) return [{ path, caps }];
  return out;
}

export function damasMoves(board, side) {
  const caps = [], simple = [];
  for (let i = 0; i < 64; i++) {
    const p = board[i];
    if (sideOf(p) !== side) continue;
    const king = isKing(p);
    const b = board.slice(); b[i] = null;  // a casa de saída fica livre durante a jogada
    for (const s of captureSeqs(b, i, side, king, [], [i])) caps.push({ from: i, to: s.path[s.path.length - 1], path: s.path, caps: s.caps });
    const [r, c] = rc(i);
    const fwd = side === 'w' ? -1 : 1;
    for (const [dr, dc] of DIRS) {
      if (!king) {
        if (dr !== fwd) continue;
        const nr = r + dr, nc = c + dc;
        if (inb(nr, nc) && board[at(nr, nc)] === null) simple.push({ from: i, to: at(nr, nc), path: [i, at(nr, nc)], caps: [] });
      } else {
        let nr = r + dr, nc = c + dc;
        while (inb(nr, nc) && board[at(nr, nc)] === null) { simple.push({ from: i, to: at(nr, nc), path: [i, at(nr, nc)], caps: [] }); nr += dr; nc += dc; }
      }
    }
  }
  if (caps.length) {
    const max = Math.max(...caps.map((m) => m.caps.length));
    return caps.filter((m) => m.caps.length === max);  // lei da maioria
  }
  return simple;
}

export function damasApply(board, m) {
  const b = board.slice();
  let p = b[m.from];
  b[m.from] = null;
  for (const k of m.caps) b[k] = null;
  const [r] = rc(m.to);
  if (!isKing(p) && ((p === 'w' && r === 0) || (p === 'b' && r === 7))) p = p.toUpperCase();
  b[m.to] = p;
  return b;
}

const material = (b, side) => b.reduce((s, p) => s + (sideOf(p) === side ? (isKing(p) ? 3 : 1) : 0), 0);

export function damasResult(board, toMove) {
  if (!board.some((p) => sideOf(p) === 'w')) return 'b';
  if (!board.some((p) => sideOf(p) === 'b')) return 'w';
  if (!damasMoves(board, toMove).length) return toMove === 'w' ? 'b' : 'w';  // sem jogadas = derrota
  return null;
}

// IA simples: maximiza material após a resposta do adversário (1 nível de antecipação) + avanço dos peões.
export function damasAiMove(board, side = 'b', rnd = Math.random) {
  const moves = damasMoves(board, side);
  if (!moves.length) return null;
  const other = side === 'w' ? 'b' : 'w';
  let best = [], bestScore = -Infinity;
  for (const m of moves) {
    const b1 = damasApply(board, m);
    const replies = damasMoves(b1, other);
    let worst = Infinity;
    for (const rpl of replies.length ? replies : [null]) {
      const b2 = rpl ? damasApply(b1, rpl) : b1;
      const advance = b2.reduce((s, p, i) => s + (p === side ? (side === 'b' ? rc(i)[0] : 7 - rc(i)[0]) * 0.02 : 0), 0);
      worst = Math.min(worst, material(b2, side) - material(b2, other) + advance);
    }
    if (worst > bestScore + 1e-9) { bestScore = worst; best = [m]; } else if (Math.abs(worst - bestScore) < 1e-9) best.push(m);
  }
  return best[Math.floor(rnd() * best.length)];
}
