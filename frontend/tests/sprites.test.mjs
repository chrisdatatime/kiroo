// Quadros dos personagens LimeZu (game/phaser/sprites.js): índices 0-based conforme a folha de contato.
import assert from 'node:assert/strict';
import { stepSeated, IDLE_LOOKS } from '../src/game/agentLife.js';
import { COLS, idleFrame, walkFrame, sitFrame, sitSide, phoneFrame, walkPhase, CHARACTER_SHEETS, characterSheetSpec, kirooFrame, seatMode } from '../src/game/phaser/sprites.js';

const at = (r, c) => r * COLS + c;
assert.equal(idleFrame('right', 0), at(1, 0)); assert.equal(idleFrame('up', 0), at(1, 6));
assert.equal(idleFrame('left', 0), at(1, 12)); assert.equal(idleFrame('down', 5), at(1, 23));
assert.equal(idleFrame('down', 6), at(1, 18), 'ciclo de 6 quadros');
// walk: 6 quadros por direção, todos distintos, sempre dentro da faixa 2
for (const [d, c0] of [['right', 0], ['up', 6], ['left', 12], ['down', 18]]) {
  const fs = Array.from({ length: 6 }, (_, k) => walkFrame(d, k / 6 + 0.01));
  assert.deepEqual(fs, [0, 1, 2, 3, 4, 5].map((k) => at(2, c0 + k)));
}
assert.equal(walkFrame('down', 0.999), at(2, 23)); assert.equal(walkFrame('down', 1.0), at(2, 18));
// fase pela distância: jogador 1 ciclo a cada 2 tiles, agente 1 por tile
assert.equal(walkPhase(64, 32, 2), 0); assert.ok(Math.abs(walkPhase(32, 32, 2) - 0.5) < 1e-9); assert.ok(Math.abs(walkPhase(16, 32, 1) - 0.5) < 1e-9);
// sentado só de lado
assert.equal(sitSide('up'), 'right'); assert.equal(sitSide('down'), 'right'); assert.equal(sitSide('left'), 'left');
assert.equal(sitFrame('right', 0), at(5, 0)); assert.equal(sitFrame('left', 0), at(5, 6)); assert.equal(sitFrame('left', 7), at(5, 7));
// phone: início 0-2 uma vez, depois loop 3-8 (nunca 9+ nem os rótulos 12+)
assert.equal(phoneFrame(0), at(6, 0)); assert.equal(phoneFrame(0.29), at(6, 2));
for (let s = 0.3; s < 5; s += 0.01) { const f = phoneFrame(s) - at(6, 0); assert.ok(f >= 3 && f <= 8, 'loop ' + f); }
assert.deepEqual(Object.keys(CHARACTER_SHEETS).sort(), ['__player', 'beto', 'iris', 'lia', 'nina', 'rui', 'theo']);
// Os agentes usam a folha Kiroo 16x48 (32x32); só o jogador mantém a folha LimeZu 32x64.
assert.deepEqual(characterSheetSpec('nina'), { kind: 'kiroo', frameWidth: 32, frameHeight: 32, head: 27, scale: 2 });
assert.deepEqual(characterSheetSpec('__player'), { kind: 'human', frameWidth: 32, frameHeight: 64, head: 48, scale: 1 });
// espera: linhas 0-3, 8 quadros por direção (frente/esq/costas/dir = linhas 0,1,2,3 colunas 0-7)
assert.equal(kirooFrame('down', 0, 'idle'), 0); assert.equal(kirooFrame('down', 0.999, 'idle'), 7);
assert.equal(kirooFrame('left', 0, 'idle'), 16); assert.equal(kirooFrame('up', 0, 'idle'), 32); assert.equal(kirooFrame('right', 0.5, 'idle'), 48 + 4);
// caminhada: linhas 4 (S), 6 (W), 8 (N), 10 (E), 16 quadros cada
assert.equal(kirooFrame('down', 0, 'walk'), 64); assert.equal(kirooFrame('down', 0.999, 'walk'), 79);
assert.equal(kirooFrame('left', 0, 'walk'), 96); assert.equal(kirooFrame('up', 0, 'walk'), 128); assert.equal(kirooFrame('right', 0, 'walk'), 160);
// trabalho: prancheta (linha 20) só de frente; nas outras direções cai na espera
assert.equal(kirooFrame('down', 0, 'work'), 320); assert.equal(kirooFrame('up', 0, 'work'), 32);
// sentado: cadeira de mesa (agent/visitor) = costas, sofá/puff (free) = frente, assento virado de lado = sit de lado
assert.equal(seatMode('agent', 'down'), 'B'); assert.equal(seatMode('visitor', 'down'), 'B');
assert.equal(seatMode('free', 'down'), 'A'); assert.equal(seatMode(undefined, 'down'), 'A');
assert.equal(seatMode('free', 'left'), 'C'); assert.equal(seatMode('agent', 'right'), 'C');
// Fase 6: na cadeira, trabalhando = costas (monitor, quadro de prancheta só de frente cai na espera), precisa de você = de frente;
// livre troca só a direção do olhar (nunca de costas), sem mudar de tile
const seat = [3, 4];
assert.equal(stepSeated(seat, { dir: 'left', rest: 3 }, 'work').dir, 'up');
assert.equal(stepSeated(seat, { dir: 'left', rest: 3 }, 'need').dir, 'down');
const seen = new Set(); let st = { dir: 'down', rest: 1 }; let r = 0.1;
for (let k = 0; k < 200; k++) { st = stepSeated(seat, st, 'idle', () => (r = (r * 7.31) % 1)); seen.add(st.dir); assert.deepEqual([st.i, st.j], seat); }
assert.ok([...seen].every((d) => IDLE_LOOKS.includes(d)) && seen.size > 1, 'pose de espera varia, sem costas');
console.log('sprites ok');
