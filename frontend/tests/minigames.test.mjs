import assert from 'node:assert/strict';
const m = await import(process.argv[2]);
const at = (r, c) => r * 8 + c, empty = () => Array(64).fill(null);
// abertura: 7 jogadas simples para as brancas, sem capturas
const b0 = m.damasInitial();
assert.equal(m.damasMoves(b0, 'w').length, 7);
assert.equal(b0.filter(Boolean).length, 24);
// captura obrigatória
let b = empty(); b[at(5,2)] = 'w'; b[at(4,3)] = 'b'; b[at(5,6)] = 'w';
let mv = m.damasMoves(b, 'w');
assert.ok(mv.every(x => x.caps.length === 1) && mv.length === 1 && mv[0].to === at(3,4));
// lei da maioria: dupla captura vence a simples
b = empty(); b[at(6,1)] = "w"; b[at(5,2)] = "b"; b[at(3,4)] = "b"; b[at(6,7)] = "w"; b[at(5,6)] = "b"; b[at(2,3)] = "b";
mv = m.damasMoves(b, 'w');
assert.ok(mv.length === 1 && mv[0].caps.length === 2 && mv[0].to === at(2,5));
// peão captura para trás
b = empty(); b[at(3,2)] = 'w'; b[at(4,3)] = 'b';
assert.equal(m.damasMoves(b, 'w')[0].to, at(5,4));
// dama voa e captura à distância
b = empty(); b[at(7,0)] = 'W'; b[at(4,3)] = 'b';
mv = m.damasMoves(b, 'w');
assert.ok(mv.length === 4 && mv.every(x => x.caps[0] === at(4,3)));
// promoção só ao terminar na última linha
b = empty(); b[at(1,2)] = 'w';
const after = m.damasApply(b, m.damasMoves(b, 'w')[0]);
assert.ok(after.includes('W'));
// derrota sem peças
b = empty(); b[at(5,2)] = 'w';
assert.equal(m.damasResult(b, 'b'), 'w');
// IA sempre devolve jogada legal
let board = m.damasInitial(), side = 'w';
for (let k = 0; k < 60 && !m.damasResult(board, side); k++) {
  const legal = m.damasMoves(board, side), pick = m.damasAiMove(board, side);
  assert.ok(legal.some(x => x.from === pick.from && x.to === pick.to));
  board = m.damasApply(board, pick); side = side === 'w' ? 'b' : 'w';
}
// velha: IA perfeita não perde e bloqueia
const t = ['X','X',null, null,'O',null, null,null,null];
assert.equal(m.tttAiMove(t, 'O', 1), 2);
assert.deepEqual(m.tttResult(['X','X','X',null,null,null,null,null,null]).line, [0,1,2]);
console.log('regras ok');
